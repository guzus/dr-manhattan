from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Literal, Optional, Sequence, Tuple, Union

import requests

import dr_manhattan
from dr_manhattan.base.errors import ExchangeError, MarketNotFound
from dr_manhattan.models.market import Market


@dataclass
class PricePoint:
    timestamp: datetime
    price: float
    raw: Dict[str, Any]


@dataclass
class Tag:
    id: str
    label: str | None
    slug: str | None
    force_show: bool | None
    force_hide: bool | None
    is_carousel: bool | None
    published_at: str | None
    created_at: str | None
    updated_at: str | None
    raw: dict


@dataclass
class PublicTrade:
    proxy_wallet: str
    side: str
    asset: str
    condition_id: str
    size: float
    price: float
    timestamp: datetime
    title: str | None
    slug: str | None
    icon: str | None
    event_slug: str | None
    outcome: str | None
    outcome_index: int | None
    name: str | None
    pseudonym: str | None
    bio: str | None
    profile_image: str | None
    profile_image_optimized: str | None
    transaction_hash: str | None


class PolymarketFetcher(dr_manhattan.Polymarket):
    PRICES_HISTORY_URL = f"{dr_manhattan.Polymarket.CLOB_URL}/prices-history"
    DATA_API_URL = "https://data-api.polymarket.com"
    SUPPORTED_INTERVALS: Sequence[str] = ("1m", "1h", "6h", "1d", "1w", "max")

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------
    def _ensure_market(self, market: Market | str) -> Market:
        if isinstance(market, Market):
            return market
        fetched = self.fetch_market(market)
        if not fetched:
            raise MarketNotFound(f"Market {market} not found")
        return fetched

    @staticmethod
    def _extract_token_ids(market: Market) -> List[str]:
        raw_ids = market.metadata.get("clobTokenIds", [])
        if isinstance(raw_ids, str):
            try:
                raw_ids = json.loads(raw_ids)
            except json.JSONDecodeError:
                raw_ids = [raw_ids]
        return [str(token_id) for token_id in raw_ids if token_id]

    def _lookup_token_id(self, market: Market, outcome: int | str | None) -> str:
        token_ids = self._extract_token_ids(market)
        if not token_ids:
            raise ExchangeError("Cannot fetch price history without token IDs in metadata.")

        if outcome is None:
            outcome_index = 0
        elif isinstance(outcome, int):
            outcome_index = outcome
        else:
            try:
                outcome_index = market.outcomes.index(outcome)
            except ValueError as err:
                raise ExchangeError(f"Outcome {outcome} not found in market {market.id}") from err

        if outcome_index < 0 or outcome_index >= len(token_ids):
            raise ExchangeError(f"Outcome index {outcome_index} out of range for market {market.id}")

        return token_ids[outcome_index]

    # -------------------------------------------------------------------------
    # Price history (CLOB /prices-history)
    # -------------------------------------------------------------------------
    def fetch_price_history(
        self,
        market: Market | str,
        *,
        outcome: int | str | None = None,
        interval: Literal["1m", "1h", "6h", "1d", "1w", "max"] = "1m",
        fidelity: int = 10,
        as_dataframe: bool = False,
    ) -> List[PricePoint] | "pandas.DataFrame":
        if interval not in self.SUPPORTED_INTERVALS:
            raise ValueError(f"Unsupported interval '{interval}'. Pick from {self.SUPPORTED_INTERVALS}.")

        market_obj = self._ensure_market(market)
        token_id = self._lookup_token_id(market_obj, outcome)

        params = {
            "market": token_id,
            "interval": interval,
            "fidelity": fidelity,
        }

        @self._retry_on_failure
        def _fetch() -> List[Dict[str, Any]]:
            resp = requests.get(self.PRICES_HISTORY_URL, params=params, timeout=self.timeout)
            resp.raise_for_status()
            payload = resp.json()
            history = payload.get("history", [])
            if not isinstance(history, list):
                raise ExchangeError("Invalid response: 'history' must be a list.")
            return history

        history = _fetch()
        points = self._parse_history(history)

        if as_dataframe:
            try:
                import pandas as pd
            except ImportError as exc:
                raise RuntimeError("pandas is required when as_dataframe=True.") from exc

            data = {
                "timestamp": [p.timestamp for p in points],
                "price": [p.price for p in points],
            }
            return pd.DataFrame(data).sort_values("timestamp").reset_index(drop=True)

        return points

    # -------------------------------------------------------------------------
    # Gamma /markets search
    # -------------------------------------------------------------------------
    def search_markets(
        self,
        *,
        # Gamma-side
        limit: int = 200,
        page_size: int = 200,
        offset: int = 0,

        order: str | None = "id",
        ascending: bool | None = False,

        closed: bool | None = False,
        tag_id: int | None = None,

        ids: Sequence[int] | None = None,
        slugs: Sequence[str] | None = None,
        clob_token_ids: Sequence[str] | None = None,
        condition_ids: Sequence[str] | None = None,
        market_maker_addresses: Sequence[str] | None = None,

        liquidity_num_min: float | None = None,
        liquidity_num_max: float | None = None,
        volume_num_min: float | None = None,
        volume_num_max: float | None = None,

        start_date_min: datetime | None = None,
        start_date_max: datetime | None = None,
        end_date_min: datetime | None = None,
        end_date_max: datetime | None = None,

        related_tags: bool | None = None,
        cyom: bool | None = None,
        uma_resolution_status: str | None = None,
        game_id: str | None = None,
        sports_market_types: Sequence[str] | None = None,
        rewards_min_size: float | None = None,
        question_ids: Sequence[str] | None = None,
        include_tag: bool | None = None,
        extra_params: Dict[str, Any] | None = None,

        # Client-side
        query: str | None = None,
        keywords: Sequence[str] | None = None,
        binary: bool | None = None,
        min_liquidity: float = 0.0,
        categories: Sequence[str] | None = None,
        outcomes: Sequence[str] | None = None,
        predicate: Callable[[Market], bool] | None = None,
    ) -> List[Market]:

        # 0) Preprocess
        if limit <= 0:
            return []

        total_limit = int(limit)
        page_size = max(1, min(int(page_size), total_limit))
        current_offset = max(0, int(offset))

        def _dt(v: datetime | None) -> str | None:
            return v.isoformat() if isinstance(v, datetime) else None

        def _lower_list(values: Sequence[str] | None) -> List[str]:
            return [v.lower() for v in values] if values else []

        query_lower = query.lower() if query else None
        keyword_lowers = _lower_list(keywords)
        category_lowers = _lower_list(categories)
        outcome_lowers = _lower_list(outcomes)

        # 1) Gamma-side params
        gamma_params: Dict[str, Any] = {
            "limit": page_size,
            "offset": current_offset,
        }

        if order is not None:
            gamma_params["order"] = order
        if ascending is not None:
            gamma_params["ascending"] = ascending

        if closed is not None:
            gamma_params["closed"] = closed
        if tag_id is not None:
            gamma_params["tag_id"] = tag_id

        if ids:
            gamma_params["id"] = list(ids)
        if slugs:
            gamma_params["slug"] = list(slugs)
        if clob_token_ids:
            gamma_params["clob_token_ids"] = list(clob_token_ids)
        if condition_ids:
            gamma_params["condition_ids"] = list(condition_ids)
        if market_maker_addresses:
            gamma_params["market_maker_address"] = list(market_maker_addresses)

        if liquidity_num_min is not None:
            gamma_params["liquidity_num_min"] = liquidity_num_min
        if liquidity_num_max is not None:
            gamma_params["liquidity_num_max"] = liquidity_num_max
        if volume_num_min is not None:
            gamma_params["volume_num_min"] = volume_num_min
        if volume_num_max is not None:
            gamma_params["volume_num_max"] = volume_num_max

        if (v := _dt(start_date_min)):
            gamma_params["start_date_min"] = v
        if (v := _dt(start_date_max)):
            gamma_params["start_date_max"] = v
        if (v := _dt(end_date_min)):
            gamma_params["end_date_min"] = v
        if (v := _dt(end_date_max)):
            gamma_params["end_date_max"] = v

        if related_tags is not None:
            gamma_params["related_tags"] = related_tags
        if cyom is not None:
            gamma_params["cyom"] = cyom
        if uma_resolution_status is not None:
            gamma_params["uma_resolution_status"] = uma_resolution_status
        if game_id is not None:
            gamma_params["game_id"] = game_id
        if sports_market_types:
            gamma_params["sports_market_types"] = list(sports_market_types)
        if rewards_min_size is not None:
            gamma_params["rewards_min_size"] = rewards_min_size
        if question_ids:
            gamma_params["question_ids"] = list(question_ids)
        if include_tag is not None:
            gamma_params["include_tag"] = include_tag
        if extra_params:
            gamma_params.update(extra_params)

        # 2) Gamma Pagenation
        gamma_results: List[Market] = []

        while len(gamma_results) < total_limit:
            remaining = total_limit - len(gamma_results)
            gamma_params["limit"] = min(page_size, remaining)
            gamma_params["offset"] = current_offset

            @self._retry_on_failure
            def _fetch_page() -> List[Market]:
                resp = requests.get(f"{self.BASE_URL}/markets", params=gamma_params, timeout=self.timeout)
                resp.raise_for_status()
                raw = resp.json()
                if not isinstance(raw, list):
                    raise ExchangeError("Gamma /markets response must be a list.")
                return [self._parse_market(m) for m in raw]

            page = _fetch_page()
            if not page:
                break

            gamma_results.extend(page)
            current_offset += len(page)

        # 3) Client-side post filtering
        filtered: List[Market] = []

        for m in gamma_results:
            if binary is not None and m.is_binary != binary:
                continue
            if m.liquidity < min_liquidity:
                continue
            if outcome_lowers:
                outs = [o.lower() for o in m.outcomes]
                if not all(x in outs for x in outcome_lowers):
                    continue
            if category_lowers:
                cats = self._extract_categories(m)
                if not cats or not any(c in cats for c in category_lowers):
                    continue
            if query_lower or keyword_lowers:
                text = self._build_search_text(m)
                if query_lower and query_lower not in text:
                    continue
                if any(k not in text for k in keyword_lowers):
                    continue
            if predicate and not predicate(m):
                continue
            filtered.append(m)
        if len(filtered) > total_limit:
            filtered = filtered[:total_limit]
        return filtered

    # -------------------------------------------------------------------------
    # Data-API /trades (global public trade history)
    # -------------------------------------------------------------------------
    def fetch_public_trades(
        self,
        market: Market | str | None = None,
        *,
        event_id: int | None = None,
        user: str | None = None,
        side: Literal["BUY", "SELL"] | None = None,
        taker_only: bool = True,
        limit: int = 100,
        offset: int = 0,
        filter_type: Literal["CASH", "TOKENS"] | None = None,
        filter_amount: float | None = None,
    ) -> List[PublicTrade]:
        """
        Fetch global trade history from the Data-API /trades endpoint.
        """

        if limit < 0 or limit > 10_000:
            raise ValueError("limit must be between 0 and 10_000")
        if offset < 0 or offset > 10_000:
            raise ValueError("offset must be between 0 and 10_000")

        total_limit = max(1, int(limit))

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

        current_offset = int(offset)

        DEFAULT_PAGE_SIZE = 200
        page_size = min(DEFAULT_PAGE_SIZE, total_limit)

        raw_trades: List[Dict[str, Any]] = []

        while len(raw_trades) < total_limit:
            remaining = total_limit - len(raw_trades)
            page_limit = min(page_size, remaining)

            params = {
                **base_params,
                "limit": page_limit,
                "offset": current_offset,
            }

            @self._retry_on_failure
            def _fetch_page() -> List[Dict[str, Any]]:
                resp = requests.get(f"{self.DATA_API_URL}/trades", params=params, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                if not isinstance(data, list):
                    raise ExchangeError("Data-API /trades response must be a list.")
                return data

            page = _fetch_page()

            if not page:
                break

            raw_trades.extend(page)

            current_offset += len(page)

        trades: List[PublicTrade] = []

        for row in raw_trades:
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

        return trades

    # -------------------------------------------------------------------------
    # Metadata helpers
    # -------------------------------------------------------------------------
    @staticmethod
    def _extract_categories(market: Market) -> List[str]:
        buckets: List[str] = []
        meta = market.metadata

        raw_cat = meta.get("category")
        if isinstance(raw_cat, str):
            buckets.append(raw_cat.lower())

        for key in ("categories", "topics"):
            raw = meta.get(key)
            if isinstance(raw, str):
                buckets.append(raw.lower())
            elif isinstance(raw, Iterable):
                buckets.extend(str(item).lower() for item in raw)

        return buckets

    @staticmethod
    def _build_search_text(market: Market) -> str:
        meta = market.metadata

        base_fields = [
            market.question or "",
            meta.get("description", ""),
        ]

        extra_keys = [
            "slug",
            "category",
            "subtitle",
            "seriesSlug",
            "series",
            "seriesTitle",
            "seriesDescription",
            "tags",
            "topics",
            "categories",
        ]

        extras: List[str] = []
        for key in extra_keys:
            value = meta.get(key)
            if value is None:
                continue
            if isinstance(value, str):
                extras.append(value)
            elif isinstance(value, Iterable):
                extras.extend(str(item).lower() for item in value)
            else:
                extras.append(str(value))

        return " ".join(str(field) for field in (base_fields + extras)).lower()

    @staticmethod
    def _parse_history(history: Iterable[Dict[str, Any]]) -> List[PricePoint]:
        parsed: List[PricePoint] = []
        for row in history:
            t = row.get("t")
            p = row.get("p")
            if t is None or p is None:
                continue
            parsed.append(
                PricePoint(
                    timestamp=datetime.fromtimestamp(int(t), tz=timezone.utc),
                    price=float(p),
                    raw=row,
                )
            )
        return sorted(parsed, key=lambda item: item.timestamp)

    # -------------------------------------------------------------------------
    # Tags (Gamma /tags/slug/{slug})
    # -------------------------------------------------------------------------
    def get_tag_by_slug(self, slug: str) -> Tag:
        if not slug:
            raise ValueError("slug must be a non-empty string")

        url = f"{self.BASE_URL}/tags/slug/{slug}"

        @self._retry_on_failure
        def _fetch() -> dict:
            resp = requests.get(url, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            if not isinstance(data, dict):
                raise ExchangeError("Gamma get_tag_by_slug response must be an object.")
            return data

        data = _fetch()

        return Tag(
            id=str(data.get("id", "")),
            label=data.get("label"),
            slug=data.get("slug"),
            force_show=data.get("forceShow"),
            force_hide=data.get("forceHide"),
            is_carousel=data.get("isCarousel"),
            published_at=data.get("publishedAt"),
            created_at=data.get("createdAt"),
            updated_at=data.get("UpdatedAt") if "UpdatedAt" in data else data.get("updatedAt"),
            raw=data,
        )
