from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional

import pandas as pd
import requests

from ...base.errors import ExchangeError
from ...models.market import Market
from .polymarket_core import PublicTrade


class PolymarketData:
    """Data API mixin: public trades, leaderboard, activity, holders, open interest."""

    def fetch_public_trades(
        self,
        market: Market | str | None = None,
        *,
        limit: int = 100,
        offset: int = 0,
        event_id: int | None = None,
        user: str | None = None,
        side: Literal["BUY", "SELL"] | None = None,
        taker_only: bool = True,
        filter_type: Literal["CASH", "TOKENS"] | None = None,
        filter_amount: float | None = None,
        as_dataframe: bool = False,
        log: bool = False,
    ) -> List[PublicTrade] | pd.DataFrame:
        total_limit = int(limit)
        if total_limit <= 0:
            return []

        if offset < 0 or offset > 10000:
            raise ValueError("offset must be between 0 and 10000")

        initial_offset = int(offset)
        default_page_size_trades = 500
        page_size = min(default_page_size_trades, total_limit)

        # ---------- condition_id resolve ----------
        condition_id: str | None = None
        if isinstance(market, Market):
            condition_id = str(market.metadata.get("conditionId", market.id))
        elif isinstance(market, str):
            condition_id = market

        base_params: Dict[str, Any] = {
            "takerOnly": "true" if taker_only else "false",
        }

        if condition_id:
            base_params["market"] = condition_id
        if event_id is not None:
            base_params["eventId"] = event_id
        if user:
            base_params["user"] = user
        if side:
            base_params["side"] = side

        if filter_type or filter_amount is not None:
            if not filter_type or filter_amount is None:
                raise ValueError("filter_type and filter_amount must be provided together")
            base_params["filterType"] = filter_type
            base_params["filterAmount"] = filter_amount

        # ---------- pagination via helper ----------
        @self._retry_on_failure
        def _fetch_page(offset_: int, limit_: int) -> List[Dict[str, Any]]:
            params = {
                **base_params,
                "limit": limit_,
                "offset": offset_,
            }

            resp = requests.get(
                f"{self.DATA_API_URL}/trades",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, list):
                raise ExchangeError("Data-API /trades response must be a list.")
            return data

        def _dedup_key(row: Dict[str, Any]) -> tuple[Any, ...]:
            # transactionHash + timestamp + side + asset + size + price
            return (row.get("transactionHash"), row.get("outcomeIndex"))

        raw_trades: List[Dict[str, Any]] = self._collect_paginated(
            _fetch_page,
            total_limit=total_limit,
            initial_offset=initial_offset,
            page_size=page_size,
            dedup_key=_dedup_key,
            log=log,
        )

        # ---------- Dict -> PublicTrade ----------
        trades: List[PublicTrade] = []

        for row in raw_trades[:total_limit]:
            ts = row.get("timestamp")
            if isinstance(ts, (int, float)):
                ts_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            elif isinstance(ts, str) and ts.isdigit():
                ts_dt = datetime.fromtimestamp(int(ts), tz=timezone.utc)
            else:
                ts_dt = datetime.fromtimestamp(0, tz=timezone.utc)

            trades.append(
                PublicTrade(
                    proxy_wallet=row.get("proxyWallet", ""),
                    side=row.get("side", ""),
                    asset=row.get("asset", ""),
                    condition_id=row.get("conditionId", ""),
                    size=float(row.get("size", 0) or 0),
                    price=float(row.get("price", 0) or 0),
                    timestamp=ts_dt,
                    title=row.get("title"),
                    slug=row.get("slug"),
                    icon=row.get("icon"),
                    event_slug=row.get("eventSlug"),
                    outcome=row.get("outcome"),
                    outcome_index=row.get("outcomeIndex"),
                    name=row.get("name"),
                    pseudonym=row.get("pseudonym"),
                    bio=row.get("bio"),
                    profile_image=row.get("profileImage"),
                    profile_image_optimized=row.get("profileImageOptimized"),
                    transaction_hash=row.get("transactionHash"),
                )
            )

        if not as_dataframe:
            return trades

        # ---------- as_dataframe=True: Convert to DataFrame----------

        df = pd.DataFrame(
            [
                {
                    "timestamp": t.timestamp,
                    "side": t.side,
                    "asset": t.asset,
                    "condition_id": t.condition_id,
                    "size": t.size,
                    "price": t.price,
                    "proxy_wallet": t.proxy_wallet,
                    "title": t.title,
                    "slug": t.slug,
                    "event_slug": t.event_slug,
                    "outcome": t.outcome,
                    "outcome_index": t.outcome_index,
                    "name": t.name,
                    "pseudonym": t.pseudonym,
                    "bio": t.bio,
                    "profile_image": t.profile_image,
                    "profile_image_optimized": t.profile_image_optimized,
                    "transaction_hash": t.transaction_hash,
                }
                for t in trades
            ]
        )

        return df.sort_values("timestamp").reset_index(drop=True)

    # =========================================================================
    # New Data API methods
    # =========================================================================

    def fetch_leaderboard(
        self, limit: int = 100, offset: int = 0, sort_by: str = "volume"
    ) -> List[Dict]:
        """
        Fetch the trader leaderboard rankings from the Data API.

        Note: The exact endpoint path for leaderboard is not publicly documented
        in the REST API. This method may need updating when the endpoint is confirmed.

        Args:
            limit: Maximum number of entries to return
            offset: Pagination offset
            sort_by: Sort criteria (e.g., "volume", "pnl")

        Returns:
            List of leaderboard entry dictionaries

        Raises:
            ExchangeError: If the endpoint is not available
        """

        @self._retry_on_failure
        def _fetch():
            params = {"limit": limit, "offset": offset, "sortBy": sort_by}
            resp = requests.get(
                f"{self.DATA_API_URL}/leaderboard",
                params=params,
                timeout=self.timeout,
            )
            if resp.status_code == 404:
                raise ExchangeError(
                    "Leaderboard endpoint not found. "
                    "The API path may have changed — check Polymarket docs."
                )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

        return _fetch()

    def fetch_user_activity(
        self, address: str, limit: int = 100, offset: int = 0
    ) -> List[Dict]:
        """
        Fetch user activity from the Data API.

        Args:
            address: User wallet address
            limit: Maximum number of entries to return
            offset: Pagination offset

        Returns:
            List of activity entry dictionaries
        """

        @self._retry_on_failure
        def _fetch():
            params = {"user": address, "limit": limit, "offset": offset}
            resp = requests.get(
                f"{self.DATA_API_URL}/activity",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

        return _fetch()

    def fetch_top_holders(
        self, condition_id: str, limit: int = 100, offset: int = 0
    ) -> List[Dict]:
        """
        Fetch top token holders for a market from the Data API.

        Args:
            condition_id: The market condition ID
            limit: Maximum number of entries to return
            offset: Pagination offset

        Returns:
            List of holder dictionaries
        """

        @self._retry_on_failure
        def _fetch():
            params = {"market": condition_id, "limit": limit, "offset": offset}
            resp = requests.get(
                f"{self.DATA_API_URL}/holders",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

        return _fetch()

    def fetch_open_interest(self, condition_id: str) -> Dict:
        """
        Fetch open interest for a market from the Data API.

        Args:
            condition_id: The market condition ID

        Returns:
            Open interest dictionary
        """

        @self._retry_on_failure
        def _fetch():
            params = {"market": condition_id}
            resp = requests.get(
                f"{self.DATA_API_URL}/oi",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            return resp.json()

        return _fetch()

    def fetch_closed_positions(
        self, address: str, limit: int = 100, offset: int = 0
    ) -> List[Dict]:
        """
        Fetch closed positions for a user from the Data API.

        Args:
            address: User wallet address
            limit: Maximum number of entries to return
            offset: Pagination offset

        Returns:
            List of closed position dictionaries
        """

        @self._retry_on_failure
        def _fetch():
            params = {"user": address, "limit": limit, "offset": offset}
            resp = requests.get(
                f"{self.DATA_API_URL}/closed-positions",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

        return _fetch()

    def fetch_accounting_snapshot(self, address: str) -> bytes:
        """
        Download an accounting snapshot (ZIP of CSVs) for a user.

        Note: The exact endpoint path is not publicly confirmed.
        This method may need updating when the endpoint is verified.

        Args:
            address: User wallet address

        Returns:
            Raw bytes of the accounting snapshot (ZIP file)

        Raises:
            ExchangeError: If the endpoint is not available
        """

        @self._retry_on_failure
        def _fetch():
            params = {"user": address}
            resp = requests.get(
                f"{self.DATA_API_URL}/accounting",
                params=params,
                timeout=self.timeout,
            )
            if resp.status_code == 404:
                raise ExchangeError(
                    "Accounting snapshot endpoint not found. "
                    "The API path may have changed — check Polymarket docs."
                )
            resp.raise_for_status()
            return resp.content

        return _fetch()
