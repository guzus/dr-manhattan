from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence

import requests

from ...base.errors import (
    ExchangeError,
    MarketNotFound,
    NetworkError,
)
from ...models import CryptoHourlyMarket
from ...models.market import Market
from ...utils import setup_logger
from .polymarket_core import PricePoint, Tag


class PolymarketGamma:
    """Gamma API mixin: market discovery, search, tags, crypto hourly markets."""

    def fetch_markets(self, params: Optional[Dict[str, Any]] = None) -> list[Market]:
        """
        Fetch all markets from Polymarket

        Uses CLOB API instead of Gamma API because CLOB includes token IDs
        which are required for trading.
        """

        @self._retry_on_failure
        def _fetch():
            # Fetch from CLOB API /sampling-markets (includes token IDs and live markets)
            try:
                response = requests.get(f"{self.CLOB_URL}/sampling-markets", timeout=self.timeout)

                if response.status_code == 200:
                    result = response.json()
                    markets_data = result.get("data", result if isinstance(result, list) else [])

                    markets = []
                    for item in markets_data:
                        market = self._parse_sampling_market(item)
                        if market:
                            markets.append(market)

                    # Apply filters if provided
                    query_params = params or {}
                    if query_params.get("active") or (not query_params.get("closed", True)):
                        markets = [m for m in markets if m.is_open]

                    # Apply limit if provided
                    limit = query_params.get("limit")
                    if limit:
                        markets = markets[:limit]

                    if self.verbose:
                        print(f"✓ Fetched {len(markets)} markets from CLOB API (sampling-markets)")

                    return markets

            except Exception as e:
                if self.verbose:
                    print(f"CLOB API fetch failed: {e}, falling back to Gamma API")

            # Fallback to Gamma API (but won't have token IDs)
            query_params = params or {}
            if "active" not in query_params and "closed" not in query_params:
                query_params = {"active": True, "closed": False, **query_params}

            data = self._request("GET", "/markets", query_params)
            markets = []
            for item in data:
                market = self._parse_market(item)
                markets.append(market)
            return markets

        return _fetch()

    def fetch_market(self, market: Market | str) -> Market:
        """Fetch specific market by ID with retry logic.

        Args:
            market: Market object, Gamma numeric ID, condition_id (0x...),
                    token_id (long numeric), or slug string.
        """
        if isinstance(market, Market):
            market_id = market.metadata.get("id", market.id)
        else:
            market_id = market

        logger = setup_logger(__name__)

        def _warn_multiple(results, identifier):
            if len(results) > 1:
                logger.warning(
                    f"Multiple markets ({len(results)}) matched '{identifier}'. "
                    f"Returning first: id={results[0].get('id')}, "
                    f"question='{results[0].get('question', '')[:50]}'"
                )

        @self._retry_on_failure
        def _fetch():
            identifier = str(market_id)

            # Gamma numeric ID → direct lookup
            if identifier.isdigit() and len(identifier) < 20:
                try:
                    data = self._request("GET", f"/markets/{identifier}")
                    return self._parse_market(data)
                except ExchangeError:
                    raise MarketNotFound(f"Market {identifier} not found")

            # Condition ID (0x...) → get token_ids from CLOB, then query Gamma by clob_token_ids
            if identifier.startswith("0x"):
                try:
                    token_ids = self.fetch_token_ids(identifier)
                    if token_ids:
                        gamma_resp = requests.get(
                            f"{self.BASE_URL}/markets",
                            params={"clob_token_ids": str(token_ids[0])},
                            timeout=self.timeout,
                        )
                        if gamma_resp.status_code == 200:
                            results = gamma_resp.json()
                            if results:
                                _warn_multiple(results, identifier)
                                return self._parse_market(results[0])
                except Exception:
                    pass
                raise MarketNotFound(f"Market {identifier} not found")

            # Long numeric string → token_id → query Gamma by clob_token_ids
            if identifier.isdigit() and len(identifier) >= 20:
                try:
                    resp = requests.get(
                        f"{self.BASE_URL}/markets",
                        params={"clob_token_ids": identifier},
                        timeout=self.timeout,
                    )
                    if resp.status_code == 200:
                        results = resp.json()
                        if results:
                            _warn_multiple(results, identifier)
                            return self._parse_market(results[0])
                except Exception:
                    pass
                raise MarketNotFound(f"Market {identifier} not found")

            # Slug → query by slug
            try:
                resp = requests.get(
                    f"{self.BASE_URL}/markets",
                    params={"slug": identifier},
                    timeout=self.timeout,
                )
                if resp.status_code == 200:
                    results = resp.json()
                    if results:
                        _warn_multiple(results, identifier)
                        return self._parse_market(results[0])
            except Exception:
                pass
            raise MarketNotFound(f"Market {identifier} not found")

        return _fetch()

    def fetch_markets_by_slug(self, slug_or_url: str) -> List[Market]:
        """
        Fetch all markets from an event by slug or URL.

        For events with multiple markets (e.g., "which day will X happen"),
        this returns all markets in the event.

        Args:
            slug_or_url: Event slug or full Polymarket URL

        Returns:
            List of Market objects with token IDs populated
        """
        slug = self.parse_market_identifier(slug_or_url)

        if not slug:
            raise ValueError("Empty slug provided")

        try:
            response = requests.get(f"{self.BASE_URL}/events?slug={slug}", timeout=self.timeout)
        except requests.Timeout as e:
            raise NetworkError(f"Request timeout: {e}")
        except requests.ConnectionError as e:
            raise NetworkError(f"Connection error: {e}")
        except requests.RequestException as e:
            raise NetworkError(f"Request failed: {e}")

        if response.status_code == 404:
            raise MarketNotFound(f"Event not found: {slug}")
        elif response.status_code != 200:
            raise ExchangeError(f"Failed to fetch event: HTTP {response.status_code}")

        event_data = response.json()
        if not event_data or len(event_data) == 0:
            raise MarketNotFound(f"Event not found: {slug}")

        event = event_data[0]
        markets_data = event.get("markets", [])

        if not markets_data:
            raise MarketNotFound(f"No markets found in event: {slug}")

        markets = []
        for market_data in markets_data:
            market = self._parse_market(market_data)

            # Compose readable_id: [event_slug, id]
            market.metadata["readable_id"] = [slug, market.id]

            # Get token IDs from market data
            clob_token_ids = market_data.get("clobTokenIds", [])
            if isinstance(clob_token_ids, str):
                try:
                    clob_token_ids = json.loads(clob_token_ids)
                except json.JSONDecodeError:
                    clob_token_ids = []

            if clob_token_ids:
                market.metadata["clobTokenIds"] = clob_token_ids

            markets.append(market)

        return markets

    def search_markets(
        self,
        *,
        # Gamma-side
        limit: int = 200,
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
        # Log
        log: bool | None = False,
    ) -> List[Market]:
        # ---------- 0) Pre-process ----------
        total_limit = int(limit)
        if total_limit <= 0:
            return []

        initial_offset = max(0, int(offset))
        default_page_size_markets = 200
        page_size = min(default_page_size_markets, total_limit)

        def _dt(v: datetime | None) -> str | None:
            return v.isoformat() if isinstance(v, datetime) else None

        def _lower_list(values: Sequence[str] | None) -> List[str]:
            return [v.lower() for v in values] if values else []

        query_lower = query.lower() if query else None
        keyword_lowers = _lower_list(keywords)
        category_lowers = _lower_list(categories)
        outcome_lowers = _lower_list(outcomes)

        # ---------- 1) Gamma-side params ----------
        gamma_params: Dict[str, Any] = {}

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

        if v := _dt(start_date_min):
            gamma_params["start_date_min"] = v
        if v := _dt(start_date_max):
            gamma_params["start_date_max"] = v
        if v := _dt(end_date_min):
            gamma_params["end_date_min"] = v
        if v := _dt(end_date_max):
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

        # ---------- 2) Gamma pagination via helper ----------
        @self._retry_on_failure
        def _fetch_page(offset_: int, limit_: int) -> List[Market]:
            params = {
                **gamma_params,
                "limit": limit_,
                "offset": offset_,
            }
            resp = requests.get(
                f"{self.BASE_URL}/markets",
                params=params,
                timeout=self.timeout,
            )
            resp.raise_for_status()
            raw = resp.json()
            if not isinstance(raw, list):
                raise ExchangeError("Gamma /markets response must be a list.")
            return [self._parse_market(m) for m in raw]

        gamma_results: List[Market] = self._collect_paginated(
            _fetch_page,
            total_limit=total_limit,
            initial_offset=initial_offset,
            page_size=page_size,
            dedup_key=None,
            log=log,
        )

        # ---------- 3) Client-side filtering ----------
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

    def find_crypto_hourly_market(
        self,
        token_symbol: Optional[str] = None,
        min_liquidity: float = 0.0,
        limit: int = 100,
        is_active: bool = True,
        is_expired: bool = False,
        params: Optional[Dict[str, Any]] = None,
    ) -> Optional[tuple[Market, Any]]:
        """
        Find crypto hourly markets on Polymarket using tag-based filtering.

        Polymarket uses TAG_1H for 1-hour crypto price markets, which is more
        efficient than pattern matching on all markets.

        Args:
            token_symbol: Filter by token (e.g., "BTC", "ETH", "SOL")
            min_liquidity: Minimum liquidity required
            limit: Maximum markets to fetch
            is_active: If True, only return markets currently in progress (expiring within 1 hour)
            is_expired: If True, only return expired markets. If False, exclude expired markets.
            params: Additional parameters (can include 'tag_id' to override default tag)

        Returns:
            Tuple of (Market, CryptoHourlyMarket) or None
        """
        logger = setup_logger(__name__)

        # Use tag-based filtering for efficiency
        tag_id = (params or {}).get("tag_id", self.TAG_1H)

        if self.verbose:
            logger.info(f"Searching for crypto hourly markets with tag: {tag_id}")

        all_markets = []
        offset = 0
        page_size = 100

        while len(all_markets) < limit:
            # Use gamma-api with tag filtering
            url = f"{self.BASE_URL}/markets"
            query_params = {
                "active": "true",
                "closed": "false",
                "limit": min(page_size, limit - len(all_markets)),
                "offset": offset,
                "order": "volume",
                "ascending": "false",
            }

            if tag_id:
                query_params["tag_id"] = tag_id

            try:
                response = requests.get(url, params=query_params, timeout=10)
                response.raise_for_status()
                data = response.json()

                markets_data = data if isinstance(data, list) else []
                if not markets_data:
                    break

                # Parse markets
                for market_data in markets_data:
                    market = self._parse_market(market_data)
                    if market:
                        all_markets.append(market)

                offset += len(markets_data)

                # If we got fewer markets than requested, we've reached the end
                if len(markets_data) < page_size:
                    break

            except Exception as e:
                if self.verbose:
                    logger.error(f"Failed to fetch tagged markets: {e}")
                break

        if self.verbose:
            logger.info(f"Found {len(all_markets)} markets with tag {tag_id}")

        # Now parse and filter the markets
        # Pattern for "Up or Down" markets (e.g., "Bitcoin Up or Down - November 2, 7AM ET")
        up_down_pattern = re.compile(
            r"(?P<token>Bitcoin|Ethereum|Solana|BTC|ETH|SOL|XRP)\s+Up or Down", re.IGNORECASE
        )

        # Pattern for strike price markets (e.g., "Will BTC be above $95,000 at 5:00 PM ET?")
        strike_pattern = re.compile(
            r"(?:(?P<token1>BTC|ETH|SOL|BITCOIN|ETHEREUM|SOLANA)\s+.*?"
            r"(?P<direction>above|below|over|under|reach)\s+"
            r"[\$]?(?P<price1>[\d,]+(?:\.\d+)?))|"
            r"(?:[\$]?(?P<price2>[\d,]+(?:\.\d+)?)\s+.*?"
            r"(?P<token2>BTC|ETH|SOL|BITCOIN|ETHEREUM|SOLANA))",
            re.IGNORECASE,
        )

        for market in all_markets:
            # Must be binary and open
            if not market.is_binary or not market.is_open:
                continue

            # Check liquidity
            if market.liquidity < min_liquidity:
                continue

            # Check expiry time filtering based on is_active and is_expired parameters
            if market.close_time:
                # Handle timezone-aware datetime
                if market.close_time.tzinfo is not None:
                    now = datetime.now(timezone.utc)
                else:
                    now = datetime.now()

                time_until_expiry = (market.close_time - now).total_seconds()

                # Apply is_expired filter
                if is_expired:
                    # Only include expired markets
                    if time_until_expiry > 0:
                        continue
                else:
                    # Exclude expired markets
                    if time_until_expiry <= 0:
                        continue

                # Apply is_active filter (only applies to non-expired markets)
                if is_active and not is_expired:
                    # For active hourly markets, only include if expiring within 1 hour
                    # This ensures we get currently active hourly candles
                    if time_until_expiry > 3600:  # 1 hour in seconds
                        continue

            # Try "Up or Down" pattern first
            up_down_match = up_down_pattern.search(market.question)
            if up_down_match:
                parsed_token = self.normalize_token(up_down_match.group("token"))

                # Apply token filter
                if token_symbol and parsed_token != self.normalize_token(token_symbol):
                    continue

                expiry = (
                    market.close_time if market.close_time else datetime.now() + timedelta(hours=1)
                )

                crypto_market = CryptoHourlyMarket(
                    token_symbol=parsed_token,
                    expiry_time=expiry,
                    strike_price=None,
                    market_type="up_down",
                )

                return (market, crypto_market)

            # Try strike price pattern
            strike_match = strike_pattern.search(market.question)
            if strike_match:
                parsed_token = self.normalize_token(
                    strike_match.group("token1") or strike_match.group("token2") or ""
                )
                parsed_price_str = (
                    strike_match.group("price1") or strike_match.group("price2") or "0"
                )
                parsed_price = float(parsed_price_str.replace(",", ""))

                # Apply filters
                if token_symbol and parsed_token != self.normalize_token(token_symbol):
                    continue

                expiry = (
                    market.close_time if market.close_time else datetime.now() + timedelta(hours=1)
                )

                crypto_market = CryptoHourlyMarket(
                    token_symbol=parsed_token,
                    expiry_time=expiry,
                    strike_price=parsed_price,
                    market_type="strike_price",
                )

                return (market, crypto_market)

        return None

    def _parse_sampling_market(self, data: Dict[str, Any]) -> Optional[Market]:
        """Parse market data from CLOB sampling-markets API response"""
        try:
            # sampling-markets includes more fields than simplified-markets
            condition_id = data.get("condition_id")
            if not condition_id:
                return None

            # Extract question and description
            question = data.get("question", "")

            # Extract tick size (minimum price increment)
            # The API returns minimum_tick_size (e.g., 0.01 or 0.001)
            # Note: minimum_order_size is different - it's the min shares per order
            # Default to 0.01 (standard Polymarket tick size) if not provided
            minimum_tick_size = data.get("minimum_tick_size", 0.01)

            # Extract tokens - sampling-markets has them in "tokens" array
            tokens_data = data.get("tokens", [])
            token_ids = []
            outcomes = []
            prices = {}

            for token in tokens_data:
                if isinstance(token, dict):
                    token_id = token.get("token_id")
                    outcome = token.get("outcome", "")
                    price = token.get("price")

                    if token_id:
                        token_ids.append(str(token_id))
                    if outcome:
                        outcomes.append(outcome)
                    if outcome and price is not None:
                        try:
                            prices[outcome] = float(price)
                        except (ValueError, TypeError):
                            pass

            # Build metadata with token IDs
            metadata = {
                **data,
                "clobTokenIds": token_ids,
                "condition_id": condition_id,
                "minimum_tick_size": minimum_tick_size,
            }

            return Market(
                id=condition_id,
                question=question,
                outcomes=outcomes if outcomes else ["Yes", "No"],
                close_time=None,  # Can parse if needed
                volume=0,  # Not in sampling-markets
                liquidity=0,  # Not in sampling-markets
                prices=prices,
                metadata=metadata,
                tick_size=minimum_tick_size,
                description=data.get("description", ""),
            )
        except Exception as e:
            if self.verbose:
                print(f"Error parsing sampling market: {e}")
            return None

    def _parse_clob_market(self, data: Dict[str, Any]) -> Optional[Market]:
        """Parse market data from CLOB API response"""
        try:
            # CLOB API structure
            condition_id = data.get("condition_id")
            if not condition_id:
                return None

            # Extract tokens (already have token_id, outcome, price, winner)
            tokens = data.get("tokens", [])
            token_ids = []
            outcomes = []
            prices = {}

            for token in tokens:
                if isinstance(token, dict):
                    token_id = token.get("token_id")
                    outcome = token.get("outcome", "")
                    price = token.get("price")

                    if token_id:
                        token_ids.append(str(token_id))
                    if outcome:
                        outcomes.append(outcome)
                    if outcome and price is not None:
                        try:
                            prices[outcome] = float(price)
                        except (ValueError, TypeError):
                            pass

            # Build metadata with token IDs already included
            # Default to 0.01 (standard Polymarket tick size) if not provided
            minimum_tick_size = data.get("minimum_tick_size", 0.01)
            metadata = {
                **data,
                "clobTokenIds": token_ids,
                "condition_id": condition_id,
                "minimum_tick_size": minimum_tick_size,
            }

            return Market(
                id=condition_id,
                question="",  # CLOB API doesn't include question text
                outcomes=outcomes if outcomes else ["Yes", "No"],
                close_time=None,  # CLOB API doesn't include end date
                volume=0,  # CLOB API doesn't include volume
                liquidity=0,  # CLOB API doesn't include liquidity
                prices=prices,
                metadata=metadata,
                tick_size=minimum_tick_size,
                description=data.get("description", ""),
            )
        except Exception as e:
            if self.verbose:
                print(f"Error parsing CLOB market: {e}")
            return None

    def _parse_market(self, data: Dict[str, Any]) -> Market:
        """Parse market data from API response"""
        # Parse outcomes - can be JSON string or list
        outcomes_raw = data.get("outcomes", [])
        if isinstance(outcomes_raw, str):
            try:
                outcomes = json.loads(outcomes_raw)
            except (json.JSONDecodeError, TypeError):
                outcomes = []
        else:
            outcomes = outcomes_raw

        # Parse outcome prices - can be JSON string, list, or None
        prices_raw = data.get("outcomePrices")
        prices_list = []

        if prices_raw is not None:
            if isinstance(prices_raw, str):
                try:
                    prices_list = json.loads(prices_raw)
                except (json.JSONDecodeError, TypeError):
                    prices_list = []
            else:
                prices_list = prices_raw

        # Create prices dictionary mapping outcomes to prices
        prices = {}
        if len(outcomes) == len(prices_list) and prices_list:
            for outcome, price in zip(outcomes, prices_list):
                try:
                    price_val = float(price)
                    # Only add non-zero prices
                    if price_val > 0:
                        prices[outcome] = price_val
                except (ValueError, TypeError):
                    pass

        # Fallback: use bestBid/bestAsk if available and no prices found
        if not prices and len(outcomes) == 2:
            best_bid = data.get("bestBid")
            best_ask = data.get("bestAsk")
            if best_bid is not None and best_ask is not None:
                try:
                    bid = float(best_bid)
                    ask = float(best_ask)
                    if 0 < bid < 1 and 0 < ask <= 1:
                        # For binary: Yes price ~ask, No price ~(1-ask)
                        prices[outcomes[0]] = ask
                        prices[outcomes[1]] = 1.0 - bid
                except (ValueError, TypeError):
                    pass

        # Parse close time - check both endDate and closed status
        close_time = self._parse_datetime(data.get("endDate"))

        # Use volumeNum if available, fallback to volume
        volume = float(data.get("volumeNum", data.get("volume", 0)))
        liquidity = float(data.get("liquidityNum", data.get("liquidity", 0)))

        # Try to extract token IDs from various possible fields
        # Gamma API sometimes includes these in the response
        metadata = dict(data)

        # Set match_id from groupItemTitle for cross-exchange matching
        if "groupItemTitle" in data:
            metadata["match_id"] = data["groupItemTitle"]

        if "tokens" in data and data["tokens"]:
            metadata["clobTokenIds"] = data["tokens"]
        elif "clobTokenIds" not in metadata and "tokenID" in data:
            # Single token ID - might be a simplified response
            metadata["clobTokenIds"] = [data["tokenID"]]

        # Ensure clobTokenIds is always a list, not a JSON string
        if "clobTokenIds" in metadata and isinstance(metadata["clobTokenIds"], str):
            try:
                metadata["clobTokenIds"] = json.loads(metadata["clobTokenIds"])
            except (json.JSONDecodeError, TypeError):
                # If parsing fails, remove it - will be fetched separately
                del metadata["clobTokenIds"]

        # Extract tick size - default to 0.01 (standard Polymarket tick size)
        # Gamma API may not include this field; CLOB API always does
        minimum_tick_size = data.get("minimum_tick_size", 0.01)
        metadata["minimum_tick_size"] = minimum_tick_size

        return Market(
            id=data.get("id", ""),
            question=data.get("question", ""),
            outcomes=outcomes,
            close_time=close_time,
            volume=volume,
            liquidity=liquidity,
            prices=prices,
            metadata=metadata,
            tick_size=minimum_tick_size,
            description=data.get("description", ""),
        )

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

    # =========================================================================
    # New Gamma API methods
    # =========================================================================

    def fetch_events(
        self,
        limit: int = 100,
        offset: int = 0,
        slug: Optional[str] = None,
        id: Optional[str] = None,
    ) -> List[Dict]:
        """
        Fetch events from the Gamma API.

        Args:
            limit: Maximum number of events to return
            offset: Pagination offset
            slug: Filter by event slug
            id: Filter by event ID

        Returns:
            List of event dictionaries
        """

        @self._retry_on_failure
        def _fetch():
            params: Dict[str, Any] = {"limit": limit, "offset": offset}
            if slug:
                params["slug"] = slug
            if id:
                params["id"] = id
            resp = requests.get(f"{self.BASE_URL}/events", params=params, timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

        return _fetch()

    def fetch_event(self, event_id: str) -> Dict:
        """
        Fetch a single event by ID from the Gamma API.

        Args:
            event_id: The event ID

        Returns:
            Event dictionary
        """

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(f"{self.BASE_URL}/events/{event_id}", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()

        return _fetch()

    def fetch_event_by_slug(self, slug: str) -> Dict:
        """
        Fetch an event by slug from the Gamma API.

        Args:
            slug: The event slug

        Returns:
            Event dictionary (first match)
        """

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(
                f"{self.BASE_URL}/events",
                params={"slug": slug},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            if isinstance(data, list) and data:
                return data[0]
            raise ExchangeError(f"Event not found: {slug}")

        return _fetch()

    def fetch_series(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """
        Fetch series from the Gamma API.

        Args:
            limit: Maximum number of series to return
            offset: Pagination offset

        Returns:
            List of series dictionaries
        """

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(
                f"{self.BASE_URL}/series",
                params={"limit": limit, "offset": offset},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

        return _fetch()

    def fetch_series_by_id(self, series_id: str) -> Dict:
        """
        Fetch a single series by ID from the Gamma API.

        Args:
            series_id: The series ID

        Returns:
            Series dictionary
        """

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(f"{self.BASE_URL}/series/{series_id}", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()

        return _fetch()

    def get_gamma_status(self) -> Dict:
        """
        Check Gamma API health.

        Returns:
            Status dictionary with at least 'status_code' and 'ok' keys.
            If the response body is valid JSON, its contents are merged in.
        """

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(f"{self.BASE_URL}/status", timeout=self.timeout)
            resp.raise_for_status()
            result: Dict[str, Any] = {"status_code": resp.status_code, "ok": resp.ok}
            try:
                body = resp.json()
                if isinstance(body, dict):
                    result.update(body)
            except Exception:
                result["body"] = resp.text
            return result

        return _fetch()

    def fetch_tags(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """
        Fetch tag list from the Gamma API.

        Args:
            limit: Maximum number of tags to return
            offset: Pagination offset

        Returns:
            List of tag dictionaries
        """

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(
                f"{self.BASE_URL}/tags",
                params={"limit": limit, "offset": offset},
                timeout=self.timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

        return _fetch()

    def fetch_tag_by_id(self, tag_id: str) -> Dict:
        """
        Fetch a tag by ID from the Gamma API.

        Args:
            tag_id: The tag ID

        Returns:
            Tag dictionary
        """

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(f"{self.BASE_URL}/tags/{tag_id}", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()

        return _fetch()

    def fetch_market_tags(self, market: Market | str) -> List[Dict]:
        """
        Fetch tags for a market from the Gamma API.

        Args:
            market: Market object or Gamma numeric ID string

        Returns:
            List of tag dictionaries
        """
        market_id = self._resolve_gamma_id(market)

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(f"{self.BASE_URL}/markets/{market_id}/tags", timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

        return _fetch()

    def fetch_event_tags(self, event_id: str) -> List[Dict]:
        """
        Fetch tags for an event from the Gamma API.

        Args:
            event_id: The event ID

        Returns:
            List of tag dictionaries
        """

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(f"{self.BASE_URL}/events/{event_id}/tags", timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

        return _fetch()

    def fetch_sports_market_types(self) -> List[Dict]:
        """
        Fetch valid sports market types from the Gamma API.

        Returns:
            List of sports market type dictionaries
        """

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(f"{self.BASE_URL}/sports/market-types", timeout=self.timeout)
            resp.raise_for_status()
            data = resp.json()
            return data if isinstance(data, list) else []

        return _fetch()

    def fetch_sports_metadata(self) -> Dict:
        """
        Fetch sports metadata from the Gamma API.

        Returns:
            Sports metadata dictionary
        """

        @self._retry_on_failure
        def _fetch():
            resp = requests.get(f"{self.BASE_URL}/sports", timeout=self.timeout)
            resp.raise_for_status()
            return resp.json()

        return _fetch()
