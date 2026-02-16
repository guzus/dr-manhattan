from __future__ import annotations

import io
import os
import re
import time

try:
    import orjson as json
except ImportError:
    import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional, Set

import boto3
import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import requests
from botocore.config import Config as BotoConfig


class BinanceManager:
    def __init__(self, base_dir: str = "."):
        self.base_dir = base_dir
        os.makedirs(base_dir, exist_ok=True)

    def _to_ms(self, t) -> Optional[int]:
        if t is None:
            return None
        return int(pd.to_datetime(t, utc=True).timestamp() * 1000)

    def fetch(
        self, market: str, symbol: str, interval: str, limit: int = 1000, start=None, end=None
    ) -> pd.DataFrame:
        base = {
            "spot": "https://api.binance.com/api/v3/klines",
            "usdm": "https://fapi.binance.com/fapi/v1/klines",
            "coinm": "https://dapi.binance.com/dapi/v1/klines",
        }.get(market)

        if not base:
            raise ValueError("market must be 'spot', 'usdm', or 'coinm'")

        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start:
            params["startTime"] = self._to_ms(start)
        if end:
            params["endTime"] = self._to_ms(end)

        r = requests.get(base, params=params, timeout=10)
        r.raise_for_status()
        data = r.json()

        cols = [
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "num_trades",
            "taker_buy_base_asset_volume",
            "taker_buy_quote_asset_volume",
            "ignore",
        ]
        df = pd.DataFrame(data, columns=cols)
        df["open_time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df["close_time"] = pd.to_datetime(df["close_time"], unit="ms", utc=True)

        num_cols = cols[1:6] + cols[7:11]
        df[num_cols] = df[num_cols].apply(pd.to_numeric, errors="coerce")
        df["open_time"] = df["open_time"].dt.tz_localize(None)
        df["close_time"] = df["close_time"].dt.tz_localize(None)
        df = df.set_index("open_time")

        return df

    def _get_path(self, market: str, symbol: str, interval: str) -> str:
        return os.path.join(self.base_dir, f"{market}_{symbol}_{interval}.csv")

    def fetch_klines(
        self,
        market: str = "usdm",
        symbol: str = "BTCUSDT",
        interval: str = "1h",
        start: str = "2019-01-01",
        limit: int = 1000,
    ) -> pd.DataFrame:
        path = self._get_path(market, symbol, interval)

        if os.path.exists(path):
            old = pd.read_csv(path, parse_dates=True, index_col="open_time")
            last = old.index[-1]
            start = last
            old = old.iloc[:-1]
        else:
            old = pd.DataFrame()

        all_data = []
        while True:
            df = self.fetch(market, symbol, interval, limit, start)
            if df.empty:
                break
            all_data.append(df)
            start = df.index[-1] + pd.to_timedelta(interval)
            if len(df) < limit:
                break
            time.sleep(0.1)

        if all_data:
            new = pd.concat(all_data)
            data = pd.concat([old, new])
            data = data[~data.index.duplicated(keep="last")].sort_index()
            data.to_csv(path)
            return data

        return old

    def _fetch_funding(
        self, market: str, symbol: str, limit: int = 1000, start=None, end=None
    ) -> pd.DataFrame:
        base = {
            "usdm": "https://fapi.binance.com/fapi/v1/fundingRate",
            "coinm": "https://dapi.binance.com/dapi/v1/fundingRate",
        }.get(market)

        if not base:
            raise ValueError("market must be 'usdm' or 'coinm' for funding rate")

        params = {"symbol": symbol, "limit": limit}
        if start:
            params["startTime"] = self._to_ms(start)
        if end:
            params["endTime"] = self._to_ms(end)

        r = requests.get(base, params=params, timeout=10)
        if r.status_code != 200:
            return pd.DataFrame()
        data = r.json()

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df["fundingTime"] = pd.to_datetime(df["fundingTime"], unit="ms", utc=True)
        df["fundingTime"] = df["fundingTime"].dt.tz_localize(None)
        df["fundingRate"] = pd.to_numeric(df["fundingRate"], errors="coerce")
        if "markPrice" in df.columns:
            df["markPrice"] = pd.to_numeric(df["markPrice"], errors="coerce")
        df = df.set_index("fundingTime")

        return df

    def fetch_funding_rate(
        self,
        market: str = "usdm",
        symbol: str = "BTCUSDT",
        start: str = "2019-01-01",
        limit: int = 1000,
    ) -> pd.DataFrame:
        path = os.path.join(self.base_dir, f"{market}_{symbol}_funding.csv")

        if os.path.exists(path):
            old = pd.read_csv(path, parse_dates=True, index_col="fundingTime")
            last = old.index[-1]
            start = last
            old = old.iloc[:-1]
        else:
            old = pd.DataFrame()

        all_data = []
        while True:
            df = self._fetch_funding(market, symbol, limit, start)
            if df.empty:
                break
            all_data.append(df)
            start = df.index[-1] + pd.Timedelta(hours=8)
            if len(df) < limit:
                break
            time.sleep(0.1)

        if all_data:
            new = pd.concat(all_data)
            data = pd.concat([old, new])
            data = data[~data.index.duplicated(keep="last")].sort_index()
            data.to_csv(path)
            return data

        return old

    def _fetch_oi(
        self, market: str, symbol: str, period: str, limit: int = 500, start=None, end=None
    ) -> pd.DataFrame:
        base = {
            "usdm": "https://fapi.binance.com/futures/data/openInterestHist",
            "coinm": "https://dapi.binance.com/futures/data/openInterestHist",
        }.get(market)

        if not base:
            raise ValueError("market must be 'usdm' or 'coinm' for open interest")

        params = {"symbol": symbol, "period": period, "limit": limit}
        if start:
            params["startTime"] = self._to_ms(start)
        if end:
            params["endTime"] = self._to_ms(end)

        r = requests.get(base, params=params, timeout=10)
        if r.status_code != 200:
            return pd.DataFrame()
        data = r.json()

        if not data:
            return pd.DataFrame()

        df = pd.DataFrame(data)
        df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
        df["timestamp"] = df["timestamp"].dt.tz_localize(None)
        df["sumOpenInterest"] = pd.to_numeric(df["sumOpenInterest"], errors="coerce")
        df["sumOpenInterestValue"] = pd.to_numeric(df["sumOpenInterestValue"], errors="coerce")
        df = df.set_index("timestamp")

        return df

    def fetch_open_interest(
        self,
        market: str = "usdm",
        symbol: str = "BTCUSDT",
        period: str = "1h",
        start: str = "2022-01-01",
        limit: int = 500,
    ) -> pd.DataFrame:
        path = os.path.join(self.base_dir, f"{market}_{symbol}_{period}_oi.csv")
        start_ts = pd.to_datetime(start)

        if os.path.exists(path):
            old = pd.read_csv(path, parse_dates=True, index_col="timestamp")
            fetch_start = old.index[-1]
            all_data = []
            while True:
                df = self._fetch_oi(market, symbol, period, limit, start=fetch_start)
                if df.empty:
                    break
                all_data.append(df)
                if len(df) < limit:
                    break
                fetch_start = df.index[-1] + pd.to_timedelta(period)
                time.sleep(0.1)

            if all_data:
                new = pd.concat(all_data)
                data = pd.concat([old.iloc[:-1], new])
                data = data[~data.index.duplicated(keep="last")].sort_index()
                data.to_csv(path)
                return data
            return old

        all_data = []
        end = None
        while True:
            df = self._fetch_oi(market, symbol, period, limit, end=end)
            if df.empty:
                break
            all_data.append(df)
            oldest = df.index.min()
            if oldest <= start_ts:
                break
            if len(df) < limit:
                break
            end = oldest - pd.to_timedelta(period)
            time.sleep(0.1)

        if all_data:
            data = pd.concat(all_data)
            data = data[~data.index.duplicated(keep="last")].sort_index()
            data = data[data.index >= start_ts]
            data.to_csv(path)
            return data

        return pd.DataFrame()


class PolymarketManager:
    DEFAULT_AWS_REGION = os.environ.get("PM_S3_REGION", "us-east-1")
    DEFAULT_POLYMARKET_BUCKET = os.environ.get("PM_S3_BUCKET", "")
    DEFAULT_ORDERBOOK_BUCKET = os.environ.get("PM_S3_ORDERBOOK_BUCKET", "")
    DEFAULT_DIRECTION = "Up"
    DEFAULT_FILE = "book"
    DEFAULT_SNAP = "1min"
    DEFAULT_PARALLEL = True
    DEFAULT_ENSURE_FULL_WINDOW = True
    DEFAULT_ADD_RESOLUTION = True
    DEFAULT_RESOLUTION_THRESHOLD = 0.5
    WINDOW_START_COL = "start_time"
    WINDOW_END_COL = "end_time"
    LEGACY_WINDOW_COL = "window_time"

    QUOTE_NUMERIC_COLS = [
        "up_best_bid",
        "up_best_ask",
        "up_best_bid_size",
        "up_best_ask_size",
        "down_best_bid",
        "down_best_ask",
        "up_mid",
        "down_mid",
        "window_close_up_mid",
    ]
    QUOTE_DEFAULT_COLS = [
        "start_time",
        "end_time",
        "up_best_bid",
        "up_best_ask",
        "up_best_bid_size",
        "up_best_ask_size",
        "down_best_bid",
        "down_best_ask",
        "up_mid",
        "down_mid",
        "window_close_up_mid",
        "resolved",
    ]

    def __init__(
        self,
        base_dir: str = ".",
        max_workers: int = 30,
    ):
        self.base_dir = base_dir
        self.aws_region = self.DEFAULT_AWS_REGION
        self.polymarket_bucket = self.DEFAULT_POLYMARKET_BUCKET
        self.orderbook_bucket = self.DEFAULT_ORDERBOOK_BUCKET
        self.max_workers = max_workers
        self.s3_client = boto3.client(
            "s3",
            region_name=self.aws_region,
            config=BotoConfig(max_pool_connections=50),
        )
        os.makedirs(base_dir, exist_ok=True)

    def _list_keys(
        self,
        asset: str,
        freq: str,
        start: pd.Timestamp,
        end: pd.Timestamp,
        direction: str,
        file: str,
    ) -> List[tuple]:
        """List S3 keys by day-level prefix, returning (s3_key, end_time_str)."""

        def _list_day(day: pd.Timestamp) -> List[tuple]:
            prefix = (
                f"crypto/{asset}/freq={freq}/"
                f"year={day.year}/month={day.month:02d}/day={day.day:02d}/"
            )
            paginator = self.s3_client.get_paginator("list_objects_v2")
            pages = paginator.paginate(Bucket=self.polymarket_bucket, Prefix=prefix)
            keys: List[tuple] = []
            for page in pages:
                for obj in page.get("Contents", []):
                    key = obj["Key"]
                    if not key.endswith(".parquet"):
                        continue
                    parts = key.split("/")
                    if len(parts) < 4:
                        continue
                    filename = parts[-1]
                    dir_part = parts[-2]
                    timestamp_folder = parts[-3]
                    file_name = filename.rsplit(".", 1)[0]
                    if dir_part != direction or file_name != file:
                        continue
                    ts = self._parse_end_time(timestamp_folder)
                    if ts is None:
                        continue
                    keys.append((key, ts.strftime("%Y-%m-%dT%H:%M:%SZ")))
            return keys

        days = pd.date_range(start.normalize(), end.normalize(), freq="D")
        if len(days) <= 1:
            return _list_day(days[0]) if len(days) == 1 else []

        result: List[tuple] = []
        with ThreadPoolExecutor(max_workers=min(len(days), self.max_workers)) as ex:
            futures = {ex.submit(_list_day, d): d for d in days}
            for future in as_completed(futures):
                result.extend(future.result())
        result.sort(key=lambda x: x[1])
        return result

    @staticmethod
    def _parse_end_time(value) -> Optional[pd.Timestamp]:
        """
        Parse end_time from folder/token robustly.
        Accepts plain ISO strings and tokens like 'window_time=...'.
        Returns UTC minute-floor timestamp or None.
        """
        ts = pd.to_datetime(value, utc=True, errors="coerce")
        if pd.isna(ts):
            txt = str(value)
            m = re.search(
                r"(\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2})?(?:\.\d+)?Z?)",
                txt,
            )
            if m:
                ts = pd.to_datetime(m.group(1), utc=True, errors="coerce")
        if pd.isna(ts):
            return None
        return ts.floor("min")

    def _download_bytes(self, key: str) -> bytes:
        """Download raw bytes from S3 (I/O only, no parsing)."""
        obj = self.s3_client.get_object(Bucket=self.polymarket_bucket, Key=key)
        return obj["Body"].read()

    @staticmethod
    def _bytes_to_df(raw: bytes) -> pd.DataFrame:
        """Parse parquet bytes into a datetime-indexed DataFrame (CPU only)."""
        columns = ["timestamp_ms", "bids", "asks"]
        try:
            table = pq.read_table(io.BytesIO(raw), columns=columns)
        except (pa.ArrowInvalid, pa.ArrowKeyError):
            table = pq.read_table(io.BytesIO(raw))

        df = table.to_pandas()
        if "timestamp_ms" not in df.columns:
            return pd.DataFrame(columns=["bids", "asks"])
        if "bids" not in df.columns or "asks" not in df.columns:
            return pd.DataFrame(columns=["bids", "asks"])

        df["datetime"] = pd.to_datetime(df["timestamp_ms"], unit="ms", utc=True, errors="coerce")
        df = df.dropna(subset=["datetime"])
        if df.empty:
            return pd.DataFrame(columns=["bids", "asks"])

        df = df[["datetime", "bids", "asks"]].set_index("datetime").sort_index()
        return df

    @staticmethod
    def _parse_book_side(arr, is_bid: bool):
        """Extract best price/size from an array of order book entries."""
        n = len(arr)
        prices = np.full(n, np.nan, dtype=np.float64)
        sizes = np.full(n, np.nan, dtype=np.float64)
        _loads = json.loads

        for i in range(n):
            raw = arr[i]
            if raw is None or raw == "":
                continue
            if isinstance(raw, str):
                try:
                    raw = _loads(raw)
                except Exception:
                    continue
            if not isinstance(raw, list) or not raw:
                continue

            best_price = -np.inf if is_bid else np.inf
            best_size = np.nan
            found = False
            for level in raw:
                if not isinstance(level, dict):
                    continue
                price = level.get("price")
                size = level.get("size")
                if price is None or size is None:
                    continue
                try:
                    price_f = float(price)
                    size_f = float(size)
                except (TypeError, ValueError):
                    continue

                if (is_bid and price_f > best_price) or (not is_bid and price_f < best_price):
                    best_price = price_f
                    best_size = size_f
                    found = True

            if found:
                prices[i] = best_price
                sizes[i] = best_size

        return prices, sizes

    @staticmethod
    def _merge_book_parts(parts: List[pd.DataFrame]) -> pd.DataFrame:
        if not parts:
            return pd.DataFrame()

        full_df = pd.concat(parts)
        idx_name = full_df.index.name or "datetime"
        window_col = (
            PolymarketManager.WINDOW_END_COL
            if PolymarketManager.WINDOW_END_COL in full_df.columns
            else PolymarketManager.LEGACY_WINDOW_COL
        )
        full_df = (
            full_df.reset_index()
            .drop_duplicates(subset=[idx_name, window_col], keep="last")
            .set_index(idx_name)
            .sort_index()
        )
        return full_df

    @staticmethod
    def _normalize_book_df(
        df: pd.DataFrame,
        market_freq: Optional[str] = None,
    ) -> pd.DataFrame:
        if df is None or df.empty:
            return pd.DataFrame()

        out = df.copy()
        if not isinstance(out.index, pd.DatetimeIndex):
            out.index = pd.to_datetime(out.index, errors="coerce")
        out = out[~out.index.isna()]
        if out.empty:
            return pd.DataFrame()
        if out.index.tz is not None:
            out.index = out.index.tz_localize(None)
        out.index.name = out.index.name or "datetime"

        if (
            PolymarketManager.LEGACY_WINDOW_COL in out.columns
            and PolymarketManager.WINDOW_END_COL not in out.columns
        ):
            out[PolymarketManager.WINDOW_END_COL] = out[PolymarketManager.LEGACY_WINDOW_COL]

        if PolymarketManager.WINDOW_END_COL in out.columns:
            et = pd.to_datetime(out[PolymarketManager.WINDOW_END_COL], utc=True, errors="coerce")
            out[PolymarketManager.WINDOW_END_COL] = et.dt.tz_localize(None)

        if PolymarketManager.WINDOW_START_COL in out.columns:
            st = pd.to_datetime(out[PolymarketManager.WINDOW_START_COL], utc=True, errors="coerce")
            out[PolymarketManager.WINDOW_START_COL] = st.dt.tz_localize(None)
        elif market_freq is not None and PolymarketManager.WINDOW_END_COL in out.columns:
            td = PolymarketManager._freq_to_timedelta(market_freq)
            out[PolymarketManager.WINDOW_START_COL] = out[PolymarketManager.WINDOW_END_COL] - td

        if PolymarketManager.LEGACY_WINDOW_COL in out.columns:
            out = out.drop(columns=[PolymarketManager.LEGACY_WINDOW_COL])

        if "window_close_up_mid" not in out.columns:
            out["window_close_up_mid"] = np.nan

        for col in PolymarketManager.QUOTE_NUMERIC_COLS:
            if col in out.columns:
                out[col] = pd.to_numeric(out[col], errors="coerce")

        return out.sort_index()

    @staticmethod
    def _freq_to_timedelta(freq) -> pd.Timedelta:
        """Convert market/snap freq strings like 15M, 1min, 1H into Timedelta."""
        if isinstance(freq, pd.Timedelta):
            return freq
        if isinstance(freq, str):
            txt = freq.strip()
            m = re.fullmatch(r"(\d+)\s*([A-Za-z]+)", txt)
            if m:
                n = int(m.group(1))
                unit = m.group(2).lower()
                if unit in {"m", "min", "mins", "minute", "minutes", "t"}:
                    return pd.Timedelta(minutes=n)
                if unit in {"h", "hr", "hrs", "hour", "hours"}:
                    return pd.Timedelta(hours=n)
                if unit in {"d", "day", "days"}:
                    return pd.Timedelta(days=n)
                if unit in {"s", "sec", "secs", "second", "seconds"}:
                    return pd.Timedelta(seconds=n)
            return pd.to_timedelta(txt)
        return pd.to_timedelta(freq)

    def _enforce_window_grid(
        self,
        df: pd.DataFrame,
        market_freq: str,
        snap: Optional[str],
    ) -> pd.DataFrame:
        """
        Ensure each window has a complete snap grid.
        Example: market_freq=15M, snap=1min => 15 rows per window.
        Missing points are forward-filled.
        """
        if df is None or df.empty:
            return pd.DataFrame()
        if self.WINDOW_END_COL not in df.columns:
            return df
        if snap is None or snap == "last":
            return df

        market_td = self._freq_to_timedelta(market_freq)
        snap_td = self._freq_to_timedelta(snap)
        if market_td <= pd.Timedelta(0) or snap_td <= pd.Timedelta(0):
            return df

        out_parts: List[pd.DataFrame] = []
        for wt, group in df.groupby(self.WINDOW_END_COL, sort=True):
            wt_ts = pd.Timestamp(wt)
            start = wt_ts - market_td
            end = wt_ts - snap_td
            if end < start:
                continue

            target_idx = pd.date_range(start=start, end=end, freq=snap_td)
            if len(target_idx) == 0:
                continue

            g = group[~group.index.duplicated(keep="last")].sort_index()
            g = g[(g.index >= start) & (g.index <= end)]
            expanded = g.reindex(target_idx)
            expanded[self.WINDOW_START_COL] = start
            expanded[self.WINDOW_END_COL] = wt_ts
            # no ffill — keep NaN for minutes without actual PM data
            out_parts.append(expanded)

        if not out_parts:
            return df

        out = pd.concat(out_parts).sort_index()
        out.index.name = df.index.name or "datetime"
        return out

    @staticmethod
    def _add_resolution_columns(
        df: pd.DataFrame,
        threshold: float = 0.5,
    ) -> pd.DataFrame:
        """
        Add per-window resolution using:
        1) window_close_up_mid, then
        2) fallback to last up_mid within each end_time window.
        Resolution output is a single string column: "UP", "DOWN", "UNKNOWN".
        """
        if df is None or df.empty:
            return df
        if (
            PolymarketManager.WINDOW_END_COL not in df.columns
            or "window_close_up_mid" not in df.columns
        ):
            return df

        out = df.copy()
        for col in ["resolved_up", "resolved_down", "resolved_side", "resolved_up_mid_last"]:
            if col in out.columns:
                out = out.drop(columns=[col])

        close_mid = out.groupby(PolymarketManager.WINDOW_END_COL)["window_close_up_mid"].transform(
            "last"
        )
        fallback_mid = out.groupby(PolymarketManager.WINDOW_END_COL)["up_mid"].transform("last")
        decision_mid = close_mid.fillna(fallback_mid)
        has_mid = decision_mid.notna()
        side = pd.Series("UNKNOWN", index=out.index, dtype="object")
        side.loc[has_mid & (decision_mid > threshold)] = "UP"
        side.loc[has_mid & (decision_mid <= threshold)] = "DOWN"
        out["resolved"] = side
        return out

    def _parse_book_chunk(
        self,
        raw_df: pd.DataFrame,
        end_time,
        market_freq: str = "15M",
        snap: Optional[str] = "1min",
    ) -> pd.DataFrame:
        if raw_df.empty or "bids" not in raw_df.columns or "asks" not in raw_df.columns:
            return pd.DataFrame()

        raw_sub = raw_df[["bids", "asks"]]

        wt_utc = pd.Timestamp(end_time)
        if wt_utc.tz is None:
            wt_utc = wt_utc.tz_localize("UTC")
        else:
            wt_utc = wt_utc.tz_convert("UTC")
        market_td = self._freq_to_timedelta(market_freq)

        raw_idx = pd.DatetimeIndex(raw_sub.index)
        if raw_idx.tz is None:
            raw_idx = raw_idx.tz_localize("UTC")
        else:
            raw_idx = raw_idx.tz_convert("UTC")
        raw_sub = raw_sub.copy()
        raw_sub.index = raw_idx

        start_utc = wt_utc - market_td
        window_raw = raw_sub[(raw_sub.index >= start_utc) & (raw_sub.index <= wt_utc)]
        if window_raw.empty:
            return pd.DataFrame()

        if snap is None:
            snap = "1min"

        close_up_mid = np.nan
        if snap == "last":
            sampled_for_close = window_raw.iloc[[-1]]
            sub = sampled_for_close
        else:
            snap_td = self._freq_to_timedelta(snap)
            full_idx = pd.date_range(start=start_utc, end=wt_utc, freq=snap_td)
            if len(full_idx) < 2:
                return pd.DataFrame()

            # 0..15 minute grid, NO ffill — only real observations
            sampled_full = window_raw.resample(snap).first().reindex(full_idx)
            sampled_for_close = window_raw.iloc[[-1]]  # last actual observation for close
            # Save only 0..14 for strategy dataset
            sub = sampled_full.iloc[:-1]
            if sub.empty:
                return pd.DataFrame()

        close_row = sampled_for_close.iloc[0]
        one_bid = np.empty(1, dtype=object)
        one_bid[0] = close_row["bids"]
        one_ask = np.empty(1, dtype=object)
        one_ask[0] = close_row["asks"]
        c_bid, _ = self._parse_book_side(one_bid, is_bid=True)
        c_ask, _ = self._parse_book_side(one_ask, is_bid=False)
        if not np.isnan(c_bid[0]) and not np.isnan(c_ask[0]):
            close_up_mid = float((c_bid[0] + c_ask[0]) / 2.0)

        bid_p, bid_s = self._parse_book_side(sub["bids"].values, is_bid=True)
        ask_p, ask_s = self._parse_book_side(sub["asks"].values, is_bid=False)

        idx = pd.DatetimeIndex(sub.index)
        if idx.tz is not None:
            idx = idx.tz_localize(None)
        idx.name = "datetime"

        end_ts = wt_utc.tz_localize(None)
        start_ts = (wt_utc - market_td).tz_localize(None)
        end_values = np.full(len(sub), end_ts.to_datetime64())
        start_values = np.full(len(sub), start_ts.to_datetime64())

        df = pd.DataFrame(
            {
                self.WINDOW_START_COL: start_values,
                self.WINDOW_END_COL: end_values,
                "up_best_bid": bid_p,
                "up_best_ask": ask_p,
                "up_best_bid_size": bid_s,
                "up_best_ask_size": ask_s,
            },
            index=idx,
        )
        df["down_best_bid"] = 1 - df["up_best_ask"]
        df["down_best_ask"] = 1 - df["up_best_bid"]
        df["up_mid"] = (df["up_best_bid"] + df["up_best_ask"]) / 2
        df["down_mid"] = (df["down_best_bid"] + df["down_best_ask"]) / 2
        df["window_close_up_mid"] = close_up_mid
        return df

    def _parse_book(
        self,
        dataset: Dict[str, pd.DataFrame],
        direction: str = "Up",
        file: str = "book",
        market_freq: str = "15M",
        snap: str = "1min",
    ) -> pd.DataFrame:
        suffix = f"/{direction}/{file}"
        parts: List[pd.DataFrame] = []

        for key, raw_df in dataset.items():
            if raw_df.empty or suffix not in key:
                continue

            timestamp_str = key[: key.index(suffix)]
            chunk = self._parse_book_chunk(
                raw_df, timestamp_str, market_freq=market_freq, snap=snap
            )
            if not chunk.empty:
                parts.append(chunk)

        return self._merge_book_parts(parts)

    def save_best_quotes_csv(
        self,
        df: pd.DataFrame,
        csv_path: str,
    ) -> str:
        """Save best quote columns to CSV with deterministic sort/dedup and atomic replace."""
        include_down = True
        include_sizes = True
        include_resolution = self.DEFAULT_ADD_RESOLUTION
        resolution_threshold = self.DEFAULT_RESOLUTION_THRESHOLD
        float_format = "%.8f"

        normalized = self._normalize_book_df(df)
        if include_resolution:
            normalized = self._add_resolution_columns(normalized, threshold=resolution_threshold)
        if normalized.empty:
            empty_cols = [self.WINDOW_START_COL, self.WINDOW_END_COL, "up_best_bid", "up_best_ask"]
            if include_sizes:
                empty_cols.extend(["up_best_bid_size", "up_best_ask_size"])
            if include_down:
                empty_cols.extend(["down_best_bid", "down_best_ask", "down_mid"])
            empty_cols.extend(["up_mid", "window_close_up_mid"])
            if include_resolution:
                empty_cols.extend(["resolved"])
            export_df = pd.DataFrame(columns=empty_cols)
            export_df.index.name = "datetime"
        else:
            export_cols = [self.WINDOW_START_COL, self.WINDOW_END_COL, "up_best_bid", "up_best_ask"]
            if include_sizes:
                export_cols.extend(["up_best_bid_size", "up_best_ask_size"])
            if include_down:
                export_cols.extend(["down_best_bid", "down_best_ask"])
            export_cols.extend(["up_mid", "window_close_up_mid"])
            if include_down:
                export_cols.append("down_mid")
            if include_resolution:
                export_cols.extend(["resolved"])
            export_cols = [c for c in export_cols if c in normalized.columns]
            export_df = normalized[export_cols]

        os.makedirs(os.path.dirname(csv_path) or ".", exist_ok=True)
        tmp_path = f"{csv_path}.tmp.{os.getpid()}"
        export_df.to_csv(
            tmp_path,
            index=True,
            index_label=export_df.index.name or "datetime",
            date_format="%Y-%m-%d %H:%M:%S",
            float_format=float_format,
        )
        os.replace(tmp_path, csv_path)
        return csv_path

    def load_book_df(
        self,
        asset: str,
        freq: str,
        start_date,
        end_date,
        save_csv: bool = False,
        csv_path: Optional[str] = None,
        log: bool = False,
    ) -> pd.DataFrame:
        direction = self.DEFAULT_DIRECTION
        file = self.DEFAULT_FILE
        snap = self.DEFAULT_SNAP
        parallel = self.DEFAULT_PARALLEL
        ensure_full_window = self.DEFAULT_ENSURE_FULL_WINDOW
        add_resolution = self.DEFAULT_ADD_RESOLUTION
        resolution_threshold = self.DEFAULT_RESOLUTION_THRESHOLD

        t0 = time.time()
        cache_file = os.path.join(
            self.base_dir, f"{asset}_{freq}_{direction}_{file}_{snap}.parquet"
        )

        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)

        # 1. Load parquet cache + determine day-level gaps
        cached_df: Optional[pd.DataFrame] = None
        cached_wt_values: Set[int] = set()
        gaps: List[tuple] = []
        cache_rewrite_needed = False
        cache_has_window_close = True
        if os.path.exists(cache_file):
            raw_cached_df = pd.read_parquet(cache_file)
            raw_cached_rows = len(raw_cached_df)
            cache_has_window_close = "window_close_up_mid" in raw_cached_df.columns
            cached_df = self._normalize_book_df(raw_cached_df, market_freq=freq)
            if ensure_full_window and cached_df is not None and not cached_df.empty:
                cached_df = self._enforce_window_grid(cached_df, market_freq=freq, snap=snap)
            if cached_df is not None and len(cached_df) != raw_cached_rows:
                cache_rewrite_needed = True
            if not cache_has_window_close:
                cache_rewrite_needed = True
            if self.WINDOW_END_COL in cached_df.columns:
                wt_series = pd.to_datetime(
                    cached_df[self.WINDOW_END_COL], utc=True, errors="coerce"
                ).dropna()
                cached_wt_values = set(wt_series.dt.floor("min").astype("int64").tolist())

        if cached_df is not None and not cached_df.empty:
            cached_start_day = pd.Timestamp(cached_df.index.min()).normalize()
            cached_end_day = pd.Timestamp(cached_df.index.max()).normalize()
            if start.normalize() < cached_start_day:
                gaps.append((start, cached_start_day - pd.Timedelta(days=1)))
            if end.normalize() > cached_end_day:
                gaps.append((cached_end_day + pd.Timedelta(days=1), end))
        else:
            gaps.append((start, end))

        if log:
            cached_rows = len(cached_df) if cached_df is not None else 0
            cached_wt = len(cached_wt_values)
            gap_days = sum(
                len(pd.date_range(g[0].normalize(), g[1].normalize(), freq="D")) for g in gaps
            )
            print(
                f"[1/5] Cache: {cached_rows:,} rows, {cached_wt} windows | "
                f"Gaps: {gap_days} days  ({time.time() - t0:.1f}s)"
            )
            if not cache_has_window_close:
                print(
                    "[1/5] Cache lacks window_close_up_mid; "
                    "resolution falls back to last up_mid per end_time."
                )

        # 2. List S3 keys only for days outside cached range
        t1 = time.time()
        all_keys: List[tuple] = []
        for gap_start, gap_end in gaps:
            all_keys.extend(self._list_keys(asset, freq, gap_start, gap_end, direction, file))

        # 3. Filter out any windows already in cache (boundary safety)
        missing: List[tuple] = []
        seen_keys: Set[str] = set()
        seen_missing_wt: Set[int] = set()
        cache_hits = 0
        parse_fail = 0
        for key, wt_str in all_keys:
            wt = self._parse_end_time(wt_str)
            if wt is None:
                parse_fail += 1
                continue
            wt_ns = wt.value
            in_cache = wt_ns in cached_wt_values
            if in_cache:
                cache_hits += 1
            need_fetch = not in_cache
            if need_fetch and key not in seen_keys and wt_ns not in seen_missing_wt:
                missing.append((key, wt.strftime("%Y-%m-%dT%H:%M:%SZ")))
                seen_keys.add(key)
                seen_missing_wt.add(wt_ns)

        if log:
            print(
                f"[2/5] Listed {len(all_keys)} keys, {len(missing)} to fetch  "
                f"({time.time() - t1:.1f}s)"
            )
            print(f"[2/5] Cache hit windows: {cache_hits}, time-parse-fail: {parse_fail}")

        # 4. Parallel download (I/O) + streaming parse (CPU)
        t2 = time.time()
        new_parts: List[pd.DataFrame] = []
        if missing:
            workers = self.max_workers if parallel else 1
            total = len(missing)

            def _dl(item):
                k, wt = item
                try:
                    return wt, self._download_bytes(k)
                except Exception as e:
                    print(f"Error loading {k}: {e}")
                    return wt, None

            done = 0
            downloaded_ok = 0
            parsed_ok = 0
            with ThreadPoolExecutor(max_workers=workers) as executor:
                futures = {executor.submit(_dl, item): item for item in missing}
                for future in as_completed(futures):
                    wt_str, raw_bytes = future.result()
                    done += 1
                    if raw_bytes is not None:
                        downloaded_ok += 1
                        try:
                            raw_df = self._bytes_to_df(raw_bytes)
                            chunk = self._parse_book_chunk(
                                raw_df, wt_str, market_freq=freq, snap=snap
                            )
                            if not chunk.empty:
                                new_parts.append(chunk)
                                parsed_ok += 1
                        except Exception as e:
                            print(f"Error parsing window {wt_str}: {e}")
                    if log and done % 50 == 0:
                        print(f"  ... {done}/{total} processed  ({time.time() - t2:.1f}s)")

            if log:
                print(f"[3/5] Downloaded {downloaded_ok}/{total} files  ({time.time() - t2:.1f}s)")
                print(f"[3.5/5] Parsed {parsed_ok} parquet files  ({time.time() - t2:.1f}s)")
        else:
            if log:
                print("[3/5] Nothing to download")

        # 5. Parse + merge + save
        t3 = time.time()
        new_df = self._merge_book_parts(new_parts)

        if log:
            new_rows = len(new_df) if not new_df.empty else 0
            print(f"[4/5] Parsed {new_rows:,} new rows  ({time.time() - t3:.1f}s)")

        if new_df.empty:
            if log:
                print(f"[5/5] No new data, serving from cache  (total {time.time() - t0:.1f}s)")
            result = pd.DataFrame()
            if cached_df is not None and not cached_df.empty:
                result = cached_df.loc[start:end]
                if cache_rewrite_needed:
                    os.makedirs(os.path.dirname(cache_file) or ".", exist_ok=True)
                    tmp_cache_path = f"{cache_file}.tmp.{os.getpid()}"
                    cached_df.to_parquet(tmp_cache_path)
                    os.replace(tmp_cache_path, cache_file)
                    if log:
                        print(f"[5/5] Rewrote normalized cache: {cache_file}")
            if add_resolution:
                result = self._add_resolution_columns(result, threshold=resolution_threshold)
            if save_csv:
                out_csv = csv_path or os.path.join(
                    self.base_dir, f"{asset}_{freq}_{direction}_{file}_{snap}_best_quotes.csv"
                )
                self.save_best_quotes_csv(result, out_csv)
                if log:
                    print(f"[5.5/5] Saved best quotes CSV: {out_csv}")
            return result

        t4 = time.time()
        parts = [cached_df] if cached_df is not None and not cached_df.empty else []
        parts.append(new_df)

        full_df = self._merge_book_parts(parts)
        if ensure_full_window:
            full_df = self._enforce_window_grid(full_df, market_freq=freq, snap=snap)

        os.makedirs(os.path.dirname(cache_file) or ".", exist_ok=True)
        tmp_cache_path = f"{cache_file}.tmp.{os.getpid()}"
        full_df.to_parquet(tmp_cache_path)
        os.replace(tmp_cache_path, cache_file)

        if log:
            print(
                f"[5/5] Saved {len(full_df):,} rows to cache  "
                f"({time.time() - t4:.1f}s) | Total: {time.time() - t0:.1f}s"
            )

        result = full_df.loc[start:end]
        if add_resolution:
            result = self._add_resolution_columns(result, threshold=resolution_threshold)
        if save_csv:
            out_csv = csv_path or os.path.join(
                self.base_dir, f"{asset}_{freq}_{direction}_{file}_{snap}_best_quotes.csv"
            )
            self.save_best_quotes_csv(result, out_csv)
            if log:
                print(f"[5.5/5] Saved best quotes CSV: {out_csv}")

        return result
