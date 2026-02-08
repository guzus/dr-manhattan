from __future__ import annotations

import base64
import hashlib
import hmac
import time
from typing import Any, Dict, List, Optional

import requests
from eth_abi import encode as abi_encode
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from ...base.errors import AuthenticationError, ExchangeError
from ...models.market import Market


class PolymarketCTF:
    """CTF (Conditional Token Framework) mixin: split, merge, redeem operations."""

    # =========================================================================
    # Web3 / Safe Helpers
    # =========================================================================

    def _get_web3(self) -> Web3:
        """Get or initialize Web3 instance"""
        if self._w3 is None:
            rpc_url = self.config.get("rpc_url", self.POLYGON_RPC_URL)
            self._w3 = Web3(Web3.HTTPProvider(rpc_url))
        return self._w3

    def _get_eoa_address(self) -> str:
        """Get EOA address from private key"""
        if not self.private_key:
            raise AuthenticationError("Private key required for CTF operations")
        pk = self.private_key
        if pk.startswith("0x"):
            pk = pk[2:]
        account = Account.from_key(pk)
        return account.address

    def _get_safe_nonce(self) -> int:
        """Get current nonce from Safe contract on-chain"""
        if not self.funder:
            raise AuthenticationError("Funder (Safe) address required for CTF operations")
        w3 = self._get_web3()
        safe = w3.eth.contract(
            address=Web3.to_checksum_address(self.funder), abi=self.SAFE_ABI
        )
        return safe.functions.nonce().call()

    def _compute_safe_tx_hash(
        self,
        to: str,
        data: bytes,
        nonce: int,
    ) -> bytes:
        """Compute EIP-712 Safe transaction hash"""
        # Safe Transaction TypeHash
        safe_tx_typehash = Web3.keccak(
            text="SafeTx(address to,uint256 value,bytes data,uint8 operation,"
            "uint256 safeTxGas,uint256 baseGas,uint256 gasPrice,address gasToken,"
            "address refundReceiver,uint256 nonce)"
        )

        # Domain separator
        domain_separator_typehash = Web3.keccak(
            text="EIP712Domain(uint256 chainId,address verifyingContract)"
        )

        domain_separator = Web3.keccak(
            abi_encode(
                ["bytes32", "uint256", "address"],
                [
                    domain_separator_typehash,
                    self.CHAIN_ID,
                    Web3.to_checksum_address(self.funder),
                ],
            )
        )

        # Encode transaction data
        data_hash = Web3.keccak(data)

        safe_tx_data = abi_encode(
            [
                "bytes32",
                "address",
                "uint256",
                "bytes32",
                "uint8",
                "uint256",
                "uint256",
                "uint256",
                "address",
                "address",
                "uint256",
            ],
            [
                safe_tx_typehash,
                Web3.to_checksum_address(to),
                0,  # value
                data_hash,
                0,  # operation (Call)
                0,  # safeTxGas
                0,  # baseGas
                0,  # gasPrice
                Web3.to_checksum_address(self.ZERO_ADDRESS),  # gasToken
                Web3.to_checksum_address(self.ZERO_ADDRESS),  # refundReceiver
                nonce,
            ],
        )

        safe_tx_hash = Web3.keccak(safe_tx_data)

        # Final hash
        final_hash = Web3.keccak(b"\x19\x01" + domain_separator + safe_tx_hash)

        return final_hash

    def _sign_safe_transaction(self, to: str, data: str, nonce: int) -> str:
        """Sign a Safe transaction and return the signature"""
        if not self.private_key:
            raise AuthenticationError("Private key required for signing")

        pk = self.private_key
        if pk.startswith("0x"):
            pk = pk[2:]

        # Convert data to bytes
        data_bytes = (
            bytes.fromhex(data[2:]) if data.startswith("0x") else bytes.fromhex(data)
        )

        # Compute hash
        tx_hash = self._compute_safe_tx_hash(to=to, data=data_bytes, nonce=nonce)

        # Sign with eth_sign style (adds prefix)
        account = Account.from_key(pk)
        message = encode_defunct(primitive=tx_hash)
        signed = account.sign_message(message)

        # Adjust v for Safe (add 4)
        v = signed.v + 4
        signature = (
            signed.r.to_bytes(32, "big")
            + signed.s.to_bytes(32, "big")
            + v.to_bytes(1, "big")
        )

        return "0x" + signature.hex()

    # =========================================================================
    # Builder API / Relayer Helpers
    # =========================================================================

    def _build_hmac_signature(
        self, secret: str, timestamp: str, method: str, request_path: str, body: str = None
    ) -> str:
        """Creates HMAC signature for Builder API authentication"""
        base64_secret = base64.urlsafe_b64decode(secret)
        message = str(timestamp) + str(method) + str(request_path)
        if body:
            message += str(body).replace("'", '"')
        h = hmac.new(base64_secret, bytes(message, "utf-8"), hashlib.sha256)
        return base64.urlsafe_b64encode(h.digest()).decode("utf-8")

    def _get_builder_headers(
        self, method: str, path: str, body: dict = None
    ) -> Dict[str, str]:
        """Generate Builder API authentication headers"""
        if not all([self.builder_api_key, self.builder_secret, self.builder_passphrase]):
            raise AuthenticationError(
                "Builder API credentials required "
                "(builder_api_key, builder_secret, builder_passphrase)"
            )

        timestamp = str(int(time.time()))

        body_str = None
        if body:
            body_str = str(body).replace("'", '"')

        signature = self._build_hmac_signature(
            self.builder_secret, timestamp, method, path, body_str
        )

        return {
            "POLY_BUILDER_API_KEY": self.builder_api_key,
            "POLY_BUILDER_SIGNATURE": signature,
            "POLY_BUILDER_TIMESTAMP": timestamp,
            "POLY_BUILDER_PASSPHRASE": self.builder_passphrase,
            "Content-Type": "application/json",
        }

    def _submit_to_relayer(
        self, to: str, data: str, nonce: int, signature: str
    ) -> Dict[str, Any]:
        """Submit transaction to Polymarket Relayer"""
        path = "/submit"

        eoa_address = self._get_eoa_address()

        payload = {
            "type": "SAFE",
            "from": eoa_address.lower(),
            "to": to.lower(),
            "proxyWallet": self.funder.lower(),
            "data": data,
            "nonce": str(nonce),
            "value": "",
            "signature": signature,
            "signatureParams": {
                "gasPrice": "0",
                "operation": "0",
                "safeTxnGas": "0",
                "baseGas": "0",
                "gasToken": self.ZERO_ADDRESS,
                "refundReceiver": self.ZERO_ADDRESS,
            },
        }

        headers = self._get_builder_headers("POST", path, payload)

        response = requests.post(
            f"{self.RELAYER_URL}{path}",
            json=payload,
            headers=headers,
            timeout=30,
        )

        if response.status_code != 200:
            raise ExchangeError(
                f"Relayer error: {response.status_code} - {response.text}"
            )

        return response.json()

    def _poll_transaction(
        self, transaction_id: str, max_polls: int = 20
    ) -> Optional[Dict[str, Any]]:
        """Poll for transaction status"""
        path = f"/transaction?id={transaction_id}"

        for _ in range(max_polls):
            try:
                response = requests.get(f"{self.RELAYER_URL}{path}", timeout=10)
                if response.status_code == 200:
                    txns = response.json()
                    if txns and len(txns) > 0:
                        state = txns[0].get("state")
                        if state in ["STATE_MINED", "STATE_CONFIRMED", "STATE_EXECUTED"]:
                            return txns[0]
                        if state == "STATE_FAILED":
                            return None
            except Exception:
                pass
            time.sleep(2)

        return None

    # =========================================================================
    # CTF Encoding Helpers
    # =========================================================================

    def _encode_split_position(self, condition_id: str, amount_wei: int) -> str:
        """Encode splitPosition function call"""
        # Function selector for splitPosition
        selector = Web3.keccak(
            text="splitPosition(address,bytes32,bytes32,uint256[],uint256)"
        )[:4]

        if condition_id.startswith("0x"):
            condition_id_bytes = bytes.fromhex(condition_id[2:])
        else:
            condition_id_bytes = bytes.fromhex(condition_id)

        encoded_params = abi_encode(
            ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
            [
                self.USDC_E,
                bytes.fromhex("00" * 32),  # parentCollectionId = 0
                condition_id_bytes,
                [1, 2],  # partition for binary markets
                amount_wei,
            ],
        )

        return "0x" + selector.hex() + encoded_params.hex()

    def _encode_merge_positions(self, condition_id: str, amount_wei: int) -> str:
        """Encode mergePositions function call"""
        # Function selector for mergePositions
        selector = Web3.keccak(
            text="mergePositions(address,bytes32,bytes32,uint256[],uint256)"
        )[:4]

        if condition_id.startswith("0x"):
            condition_id_bytes = bytes.fromhex(condition_id[2:])
        else:
            condition_id_bytes = bytes.fromhex(condition_id)

        encoded_params = abi_encode(
            ["address", "bytes32", "bytes32", "uint256[]", "uint256"],
            [
                self.USDC_E,
                bytes.fromhex("00" * 32),  # parentCollectionId = 0
                condition_id_bytes,
                [1, 2],  # partition for binary markets
                amount_wei,
            ],
        )

        return "0x" + selector.hex() + encoded_params.hex()

    def _encode_redeem_positions(self, condition_id: str) -> str:
        """Encode redeemPositions function call"""
        # Function selector (verified: 0x01b7037c)
        selector = bytes.fromhex("01b7037c")

        if condition_id.startswith("0x"):
            condition_id_bytes = bytes.fromhex(condition_id[2:])
        else:
            condition_id_bytes = bytes.fromhex(condition_id)

        encoded_params = abi_encode(
            ["address", "bytes32", "bytes32", "uint256[]"],
            [
                self.USDC_E,
                bytes.fromhex("00" * 32),  # parentCollectionId = 0
                condition_id_bytes,
                [1, 2],  # Both outcomes
            ],
        )

        return "0x" + selector.hex() + encoded_params.hex()

    # =========================================================================
    # Public CTF Methods: Split, Merge, Redeem
    # =========================================================================

    def split(
        self,
        market: Market | str,
        amount: float,
        wait_for_confirmation: bool = True,
    ) -> Dict[str, Any]:
        """
        Split USDC into Yes and No conditional tokens.

        Args:
            market: Market object or condition_id string (hex)
            amount: Amount of USDC to split (e.g., 10.0 = $10)
            wait_for_confirmation: If True, wait for transaction to be mined

        Returns:
            Dict with transaction details:
            - tx_id: Relayer transaction ID
            - tx_hash: On-chain transaction hash (if confirmed)
            - status: Transaction status
            - condition_id: The condition ID
            - amount: Amount split

        Example:
            >>> result = exchange.split("0x123...", 10.0)
            >>> print(f"Split {result['amount']} USDC, tx: {result['tx_hash']}")
        """
        # Validate credentials
        condition_id = self._resolve_condition_id(market)
        if not self.funder:
            raise AuthenticationError("Funder (Safe) address required for split")

        # Convert amount to wei (USDC has 6 decimals)
        amount_wei = int(amount * 1e6)

        # Get Safe nonce
        nonce = self._get_safe_nonce()

        # Encode transaction data
        data = self._encode_split_position(condition_id, amount_wei)

        # Sign transaction
        signature = self._sign_safe_transaction(
            to=self.CTF_CONTRACT, data=data, nonce=nonce
        )

        # Submit to relayer
        result = self._submit_to_relayer(
            to=self.CTF_CONTRACT, data=data, nonce=nonce, signature=signature
        )

        tx_id = result.get("transactionID")

        response = {
            "tx_id": tx_id,
            "tx_hash": None,
            "status": "submitted",
            "condition_id": condition_id,
            "amount": amount,
        }

        # Poll for confirmation if requested
        if wait_for_confirmation and tx_id:
            final = self._poll_transaction(tx_id)
            if final:
                response["tx_hash"] = final.get("transactionHash")
                response["status"] = final.get("state", "confirmed")
            else:
                response["status"] = "timeout_or_failed"

        return response

    def merge(
        self,
        market: Market | str,
        amount: float,
        wait_for_confirmation: bool = True,
    ) -> Dict[str, Any]:
        """
        Merge Yes and No conditional tokens back into USDC.

        Args:
            market: Market object or condition_id string (hex)
            amount: Amount of token pairs to merge (e.g., 10.0 = 10 Yes + 10 No -> 10 USDC)
            wait_for_confirmation: If True, wait for transaction to be mined

        Returns:
            Dict with transaction details:
            - tx_id: Relayer transaction ID
            - tx_hash: On-chain transaction hash (if confirmed)
            - status: Transaction status
            - condition_id: The condition ID
            - amount: Amount merged

        Example:
            >>> result = exchange.merge("0x123...", 10.0)
            >>> print(f"Merged {result['amount']} tokens, tx: {result['tx_hash']}")
        """
        # Validate credentials
        condition_id = self._resolve_condition_id(market)
        if not self.funder:
            raise AuthenticationError("Funder (Safe) address required for merge")

        # Convert amount to wei (USDC has 6 decimals)
        amount_wei = int(amount * 1e6)

        # Get Safe nonce
        nonce = self._get_safe_nonce()

        # Encode transaction data
        data = self._encode_merge_positions(condition_id, amount_wei)

        # Sign transaction
        signature = self._sign_safe_transaction(
            to=self.CTF_CONTRACT, data=data, nonce=nonce
        )

        # Submit to relayer
        result = self._submit_to_relayer(
            to=self.CTF_CONTRACT, data=data, nonce=nonce, signature=signature
        )

        tx_id = result.get("transactionID")

        response = {
            "tx_id": tx_id,
            "tx_hash": None,
            "status": "submitted",
            "condition_id": condition_id,
            "amount": amount,
        }

        # Poll for confirmation if requested
        if wait_for_confirmation and tx_id:
            final = self._poll_transaction(tx_id)
            if final:
                response["tx_hash"] = final.get("transactionHash")
                response["status"] = final.get("state", "confirmed")
            else:
                response["status"] = "timeout_or_failed"

        return response

    def redeem(
        self,
        market: Market | str,
        wait_for_confirmation: bool = True,
    ) -> Dict[str, Any]:
        """
        Redeem winning tokens from a resolved market.

        Args:
            market: Market object or condition_id string (hex) of a resolved market
            wait_for_confirmation: If True, wait for transaction to be mined

        Returns:
            Dict with transaction details:
            - tx_id: Relayer transaction ID
            - tx_hash: On-chain transaction hash (if confirmed)
            - status: Transaction status
            - condition_id: The condition ID

        Example:
            >>> result = exchange.redeem("0x123...")
            >>> print(f"Redeemed, tx: {result['tx_hash']}")
        """
        # Validate credentials
        condition_id = self._resolve_condition_id(market)
        if not self.funder:
            raise AuthenticationError("Funder (Safe) address required for redeem")

        # Get Safe nonce
        nonce = self._get_safe_nonce()

        # Encode transaction data
        data = self._encode_redeem_positions(condition_id)

        # Sign transaction
        signature = self._sign_safe_transaction(
            to=self.CTF_CONTRACT, data=data, nonce=nonce
        )

        # Submit to relayer
        result = self._submit_to_relayer(
            to=self.CTF_CONTRACT, data=data, nonce=nonce, signature=signature
        )

        tx_id = result.get("transactionID")

        response = {
            "tx_id": tx_id,
            "tx_hash": None,
            "status": "submitted",
            "condition_id": condition_id,
        }

        # Poll for confirmation if requested
        if wait_for_confirmation and tx_id:
            final = self._poll_transaction(tx_id)
            if final:
                response["tx_hash"] = final.get("transactionHash")
                response["status"] = final.get("state", "confirmed")
            else:
                response["status"] = "timeout_or_failed"

        return response

    def fetch_redeemable_positions(self) -> List[Dict[str, Any]]:
        """
        Fetch positions that can be redeemed (from resolved markets).

        Returns:
            List of redeemable position dictionaries with fields:
            - conditionId: The condition ID
            - title: Market title
            - outcome: Winning outcome
            - size: Token amount
            - currentValue: Value in USDC

        Example:
            >>> positions = exchange.fetch_redeemable_positions()
            >>> for pos in positions:
            ...     print(f"{pos['title']}: {pos['outcome']} - ${pos['currentValue']}")
        """
        if not self.funder:
            raise AuthenticationError(
                "Funder (Safe) address required to fetch redeemable positions"
            )

        url = f"{self.DATA_API_URL}/positions"
        params = {"user": self.funder.lower(), "redeemable": "true"}

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            data = response.json()
            return data if isinstance(data, list) else []
        except Exception as e:
            raise ExchangeError(f"Failed to fetch redeemable positions: {e}")

    def redeem_all(
        self,
        wait_for_confirmation: bool = True,
    ) -> List[Dict[str, Any]]:
        """
        Redeem all redeemable positions.

        Args:
            wait_for_confirmation: If True, wait for each transaction to be mined

        Returns:
            List of redemption results for each condition

        Example:
            >>> results = exchange.redeem_all()
            >>> for r in results:
            ...     print(f"{r['condition_id']}: {r['status']}")
        """
        positions = self.fetch_redeemable_positions()
        if not positions:
            return []

        # Extract unique condition IDs
        condition_ids = list(
            set(pos.get("conditionId") for pos in positions if pos.get("conditionId"))
        )

        results = []
        for condition_id in condition_ids:
            try:
                result = self.redeem(
                    condition_id=condition_id,
                    wait_for_confirmation=wait_for_confirmation,
                )
                results.append(result)
            except Exception as e:
                results.append(
                    {
                        "condition_id": condition_id,
                        "status": "error",
                        "error": str(e),
                    }
                )

        return results
