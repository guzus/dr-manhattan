"""Tests for dr_manhattan.base.signer and the Limitless signer seam."""

import json
import unittest
from unittest.mock import MagicMock, patch

from eth_account import Account
from eth_account.messages import encode_defunct, encode_typed_data

from dr_manhattan.base.errors import AuthenticationError
from dr_manhattan.base.exchange_config import LimitlessConfig
from dr_manhattan.base.exchange_factory import _attach_signer, _validate_config
from dr_manhattan.base.signer import LocalPrivateKeySigner, PrivySigner

TEST_KEY = "0x" + "ab" * 32

ORDER_TYPED_DATA = {
    "types": {
        "EIP712Domain": [
            {"name": "name", "type": "string"},
            {"name": "version", "type": "string"},
            {"name": "chainId", "type": "uint256"},
            {"name": "verifyingContract", "type": "address"},
        ],
        "Order": [
            {"name": "salt", "type": "uint256"},
            {"name": "maker", "type": "address"},
        ],
    },
    "primaryType": "Order",
    "domain": {
        "name": "Limitless CTF Exchange",
        "version": "1",
        "chainId": 8453,
        "verifyingContract": "0x0000000000000000000000000000000000000001",
    },
    "message": {
        "salt": 1,
        "maker": "0x0000000000000000000000000000000000000002",
    },
}


class TestLocalPrivateKeySigner(unittest.TestCase):
    """The local signer must be signature-identical to direct eth-account use."""

    def setUp(self):
        self.signer = LocalPrivateKeySigner(TEST_KEY)
        self.account = Account.from_key(TEST_KEY)

    def test_address_matches_eth_account(self):
        self.assertEqual(self.signer.address, self.account.address)

    def test_personal_message_parity(self):
        expected = self.account.sign_message(encode_defunct(text="hello")).signature.hex()
        if not expected.startswith("0x"):
            expected = "0x" + expected
        self.assertEqual(self.signer.sign_personal_message("hello"), expected)

    def test_typed_data_parity(self):
        encoded = encode_typed_data(full_message=ORDER_TYPED_DATA)
        expected = self.account.sign_message(encoded).signature.hex()
        if not expected.startswith("0x"):
            expected = "0x" + expected
        self.assertEqual(self.signer.sign_typed_data(ORDER_TYPED_DATA), expected)


class TestPrivySigner(unittest.TestCase):
    def _make_signer(self, session):
        with patch("dr_manhattan.base.signer.requests.Session", return_value=session):
            return PrivySigner(
                app_id="app-1",
                app_secret="secret-1",
                wallet_id="wallet-1",
                address="0x0000000000000000000000000000000000000009",
            )

    @staticmethod
    def _response(payload, status=200):
        response = MagicMock()
        response.status_code = status
        response.json.return_value = payload
        response.raise_for_status.return_value = None
        return response

    def test_requires_credentials(self):
        with self.assertRaises(AuthenticationError):
            PrivySigner(app_id="", app_secret="s", wallet_id="w")

    def test_sign_typed_data_converts_shape_and_normalizes(self):
        session = MagicMock()
        session.request.return_value = self._response(
            {"method": "eth_signTypedData_v4", "data": {"signature": "abc123", "encoding": "hex"}}
        )
        signer = self._make_signer(session)

        signature = signer.sign_typed_data(ORDER_TYPED_DATA)

        self.assertEqual(signature, "0xabc123")
        method, url = session.request.call_args[0]
        self.assertEqual(method, "POST")
        self.assertTrue(url.endswith("/v1/wallets/wallet-1/rpc"))
        body = session.request.call_args[1]["json"]
        self.assertEqual(body["method"], "eth_signTypedData_v4")
        typed = body["params"]["typed_data"]
        # Privy uses snake_case primary_type; everything else passes through.
        self.assertEqual(typed["primary_type"], "Order")
        self.assertNotIn("primaryType", typed)
        self.assertEqual(typed["domain"]["name"], "Limitless CTF Exchange")

    def test_uint256_fields_serialize_as_strings_not_bare_numbers(self):
        # Regression: a uint256 tokenId sent as a bare JSON number is parsed
        # into a float64 by the receiver and loses precision, corrupting the
        # signed digest. It must go out as a decimal string.
        big_token = 2**255 + 12345  # 78-digit uint256, far above float64 exactness
        typed_data = {
            "types": ORDER_TYPED_DATA["types"],
            "primaryType": "Order",
            "domain": {**ORDER_TYPED_DATA["domain"], "chainId": 8453},
            "message": {"salt": 987654321987654321, "maker": "0x00", "tokenId": big_token},
        }
        session = MagicMock()
        session.request.return_value = self._response(
            {"method": "eth_signTypedData_v4", "data": {"signature": "0xok"}}
        )
        signer = self._make_signer(session)

        signer.sign_typed_data(typed_data)

        typed = session.request.call_args[1]["json"]["params"]["typed_data"]
        self.assertEqual(typed["message"]["tokenId"], str(big_token))
        self.assertEqual(typed["domain"]["chainId"], "8453")
        # The actual wire bytes must preserve the value exactly - the failure
        # mode is a float64 round-trip, so assert against the serialized JSON.
        wire = json.dumps(session.request.call_args[1]["json"])
        self.assertIn(f'"{big_token}"', wire)
        self.assertNotIn(str(big_token) + ",", wire)  # never a bare numeric literal

    def test_sign_personal_message(self):
        session = MagicMock()
        session.request.return_value = self._response(
            {"method": "personal_sign", "data": {"signature": "0xdef", "encoding": "hex"}}
        )
        signer = self._make_signer(session)

        self.assertEqual(signer.sign_personal_message("login me"), "0xdef")
        body = session.request.call_args[1]["json"]
        self.assertEqual(body["method"], "personal_sign")
        self.assertEqual(body["params"], {"message": "login me", "encoding": "utf-8"})

    def test_auth_failure_raises(self):
        session = MagicMock()
        session.request.return_value = self._response({"error": "nope"}, status=401)
        signer = self._make_signer(session)
        with self.assertRaises(AuthenticationError):
            signer.sign_personal_message("x")

    def test_address_lazy_fetch(self):
        session = MagicMock()
        session.request.return_value = self._response(
            {"id": "wallet-1", "address": "0x00000000000000000000000000000000000000AA"}
        )
        with patch("dr_manhattan.base.signer.requests.Session", return_value=session):
            signer = PrivySigner(app_id="a", app_secret="s", wallet_id="wallet-1")

        self.assertEqual(signer.address, "0x00000000000000000000000000000000000000AA")
        method, url = session.request.call_args[0]
        self.assertEqual(method, "GET")
        self.assertTrue(url.endswith("/v1/wallets/wallet-1"))
        # Cached: a second read must not re-fetch.
        session.request.reset_mock()
        _ = signer.address
        session.request.assert_not_called()


class _StubSigner:
    address = "0x0000000000000000000000000000000000000123"

    def __init__(self):
        self.personal_messages = []
        self.typed_payloads = []

    def sign_personal_message(self, message):
        self.personal_messages.append(message)
        return "0xstub-personal"

    def sign_typed_data(self, typed_data):
        self.typed_payloads.append(typed_data)
        return "0xstub-typed"


class TestLimitlessSignerSeam(unittest.TestCase):
    def _make_exchange(self, stub):
        from dr_manhattan.exchanges.limitless import Limitless

        signing_message = MagicMock()
        signing_message.status_code = 200
        signing_message.text = "sign this to log in"
        signing_message.raise_for_status.return_value = None

        login = MagicMock()
        login.status_code = 200
        login.json.return_value = {"user": {"id": "user-1"}}
        login.raise_for_status.return_value = None

        session = MagicMock()
        session.get.return_value = signing_message
        session.post.return_value = login

        with patch("dr_manhattan.exchanges.limitless.requests.Session", return_value=session):
            exchange = Limitless({"signer": stub, "verbose": False})
        return exchange, session

    def test_auth_uses_injected_signer(self):
        stub = _StubSigner()
        exchange, session = self._make_exchange(stub)

        self.assertTrue(exchange._authenticated)
        self.assertEqual(exchange._address, stub.address)
        self.assertEqual(stub.personal_messages, ["sign this to log in"])
        headers = session.post.call_args[1]["headers"]
        self.assertEqual(headers["x-account"], stub.address)
        self.assertEqual(headers["x-signature"], "0xstub-personal")

    def test_order_signing_routes_through_signer(self):
        stub = _StubSigner()
        exchange, _ = self._make_exchange(stub)

        order = {
            "salt": 1,
            "maker": stub.address,
            "signer": stub.address,
            "taker": "0x0000000000000000000000000000000000000000",
            "tokenId": 7,
            "makerAmount": 100,
            "takerAmount": 100,
            "expiration": 0,
            "nonce": 0,
            "feeRateBps": 300,
            "side": 0,
            "signatureType": 0,
        }
        signature = exchange._sign_order_eip712(order, "0x0000000000000000000000000000000000000001")

        self.assertEqual(signature, "0xstub-typed")
        typed = stub.typed_payloads[0]
        self.assertEqual(typed["primaryType"], "Order")
        self.assertEqual(typed["domain"]["name"], "Limitless CTF Exchange")
        self.assertEqual(typed["message"]["maker"], stub.address)


class TestFactorySignerBackend(unittest.TestCase):
    def test_validate_privy_requires_env(self):
        config = LimitlessConfig(signer_backend="privy")
        empty = {"PRIVY_APP_ID": "", "PRIVY_APP_SECRET": "", "PRIVY_WALLET_ID": ""}
        with patch.dict("os.environ", empty):
            with self.assertRaises(ValueError) as ctx:
                _validate_config("limitless", config)
        self.assertIn("PRIVY_APP_ID", str(ctx.exception))

    def test_validate_privy_skips_private_key_requirement(self):
        config = LimitlessConfig(signer_backend="privy")
        env = {
            "PRIVY_APP_ID": "a",
            "PRIVY_APP_SECRET": "s",
            "PRIVY_WALLET_ID": "w",
        }
        with patch.dict("os.environ", env):
            _validate_config("limitless", config)  # must not raise

    def test_attach_signer_builds_privy(self):
        config = LimitlessConfig(signer_backend="privy")
        config_dict = config.to_dict()
        env = {
            "PRIVY_APP_ID": "a",
            "PRIVY_APP_SECRET": "s",
            "PRIVY_WALLET_ID": "w",
            "PRIVY_WALLET_ADDRESS": "0x0000000000000000000000000000000000000042",
        }
        with patch.dict("os.environ", env):
            _attach_signer("limitless", config, config_dict)
        self.assertIsInstance(config_dict["signer"], PrivySigner)

    def test_attach_signer_rejects_unknown_backend(self):
        config = LimitlessConfig(signer_backend="ledger")
        with self.assertRaises(ValueError):
            _attach_signer("limitless", config, config.to_dict())

    def test_attach_signer_noop_for_local(self):
        config = LimitlessConfig(private_key=TEST_KEY)
        config_dict = config.to_dict()
        _attach_signer("limitless", config, config_dict)
        self.assertNotIn("signer", config_dict)


if __name__ == "__main__":
    unittest.main()
