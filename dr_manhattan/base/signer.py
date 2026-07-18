"""Pluggable message signers.

A Signer owns exactly one job: produce Ethereum signatures for an address.
Exchanges keep owning payload construction (EIP-712 typed data, auth messages)
and hand the finished payload to their signer, so where the private key lives
becomes a deployment choice instead of a code path:

  - LocalPrivateKeySigner: the historical behavior - a raw key in process memory
    via eth-account. Default when config provides ``private_key``.
  - PrivySigner: signing delegated to a Privy server wallet over REST; the raw
    key never enters this process. Free tier covers 50k signatures/month.

Wired venues: Limitless (its signing lives fully in this repo). Polymarket,
Opinion, and Predict.fun construct signatures inside their vendor SDKs
(py-clob-client, opinion-clob-sdk, predict-sdk), so they still require raw keys
until those SDKs expose a signer seam.
"""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import requests

from .errors import AuthenticationError, ExchangeError, NetworkError

PRIVY_BASE_URL = "https://api.privy.io"


def _normalize_signature(signature: str) -> str:
    return signature if signature.startswith("0x") else f"0x{signature}"


class Signer(ABC):
    """Produces EIP-191 and EIP-712 signatures for a single address."""

    @property
    @abstractmethod
    def address(self) -> str:
        """Checksummed 0x address the signatures verify against."""

    @abstractmethod
    def sign_personal_message(self, message: str) -> str:
        """EIP-191 personal_sign over a text message; returns a 0x-hex signature."""

    @abstractmethod
    def sign_typed_data(self, typed_data: Dict[str, Any]) -> str:
        """EIP-712 signature over a full typed-data message; returns 0x-hex.

        ``typed_data`` uses the standard eth_signTypedData_v4 shape:
        {"types": {...incl. EIP712Domain}, "primaryType": ..., "domain": ...,
        "message": ...}.
        """


class LocalPrivateKeySigner(Signer):
    """Signs with a raw private key held in process memory (eth-account)."""

    def __init__(self, private_key: str):
        from eth_account import Account

        self._account = Account.from_key(private_key)

    @property
    def address(self) -> str:
        return self._account.address

    def sign_personal_message(self, message: str) -> str:
        from eth_account.messages import encode_defunct

        signed = self._account.sign_message(encode_defunct(text=message))
        return _normalize_signature(signed.signature.hex())

    def sign_typed_data(self, typed_data: Dict[str, Any]) -> str:
        from eth_account.messages import encode_typed_data

        signed = self._account.sign_message(encode_typed_data(full_message=typed_data))
        return _normalize_signature(signed.signature.hex())


class PrivySigner(Signer):
    """Signs through a Privy server wallet; the key stays inside Privy's TEEs.

    API: POST {base}/v1/wallets/{wallet_id}/rpc with HTTP basic auth
    (app_id, app_secret) plus the ``privy-app-id`` header. Privy's typed-data
    payload uses snake_case ``primary_type``; this class converts from the
    standard eth_signTypedData_v4 shape used across the codebase.
    """

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        wallet_id: str,
        address: Optional[str] = None,
        base_url: str = PRIVY_BASE_URL,
        timeout: int = 30,
    ):
        if not (app_id and app_secret and wallet_id):
            raise AuthenticationError("PrivySigner requires app_id, app_secret, and wallet_id")
        self._wallet_id = wallet_id
        self._address = address or ""
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = requests.Session()
        self._session.auth = (app_id, app_secret)
        self._session.headers.update({"privy-app-id": app_id, "Content-Type": "application/json"})

    def _request(self, method: str, path: str, body: Optional[Dict[str, Any]] = None) -> Any:
        url = f"{self._base_url}{path}"
        try:
            response = self._session.request(method, url, json=body, timeout=self._timeout)
            if response.status_code in (401, 403):
                raise AuthenticationError(f"Privy auth failed: {response.text}")
            response.raise_for_status()
            return response.json()
        except requests.Timeout as e:
            raise NetworkError(f"Privy request timeout: {e}") from e
        except requests.ConnectionError as e:
            raise NetworkError(f"Privy connection error: {e}") from e
        except requests.HTTPError as e:
            raise ExchangeError(f"Privy HTTP error: {e}: {e.response.text[:200]}") from e

    def _rpc(self, payload: Dict[str, Any]) -> str:
        result = self._request("POST", f"/v1/wallets/{self._wallet_id}/rpc", payload)
        signature = (result.get("data") or {}).get("signature", "")
        if not signature:
            raise ExchangeError(f"Privy returned no signature: {result}")
        return _normalize_signature(signature)

    @property
    def address(self) -> str:
        if not self._address:
            wallet = self._request("GET", f"/v1/wallets/{self._wallet_id}")
            self._address = wallet.get("address", "")
            if not self._address:
                raise ExchangeError(f"Privy wallet {self._wallet_id} has no address")
        return self._address

    def sign_personal_message(self, message: str) -> str:
        return self._rpc(
            {"method": "personal_sign", "params": {"message": message, "encoding": "utf-8"}}
        )

    def sign_typed_data(self, typed_data: Dict[str, Any]) -> str:
        privy_typed_data = {
            "types": typed_data["types"],
            "primary_type": typed_data["primaryType"],
            "domain": typed_data["domain"],
            "message": typed_data["message"],
        }
        return self._rpc(
            {"method": "eth_signTypedData_v4", "params": {"typed_data": privy_typed_data}}
        )
