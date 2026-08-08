import hashlib
import os
import re

import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

# Anchor the cache to the package, not the working directory. The old relative
# default produced a separate cache under every directory the code was run
# from -- hence cache/, analytics/cache/ and notebooks/cache/ all existing.
_PACKAGE_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_SAFE_TICKER = re.compile(r"[^A-Z0-9.\-]")


class MarketDataFetcher():
    """Price fetcher with a two-level cache (memory, then parquet on disk).

    The cache is merge-only: a request for a narrow window never replaces a
    wider cached history. That mattered less in a script and matters a great
    deal in a UI, where every widget change re-runs the pipeline.
    """

    # False means Close is the price that actually traded, adjusted for splits
    # but not for dividends. That is the same basis a transaction records, so
    # portfolio value and cash flows are directly comparable. Dividends are
    # handled as cash income instead of being folded into the price.
    #
    # Note yfinance always split-adjusts, under either setting. Quantities
    # recorded on transactions are therefore on a stale share basis after a
    # split, which PortfolioTimeSeries corrects.
    #
    # Pinned rather than inherited: the library default changed in 0.2.51 and
    # moved every historical number with it.
    AUTO_ADJUST = False

    def __init__(self, cache_directory = None, cache_expiry_days = 1):
        if cache_directory is None:
            cache_directory = os.path.join(_PACKAGE_ROOT, "cache")

        self.memory_cache = dict()
        self._actions_cache = dict()
        self.cache_directory = os.path.abspath(cache_directory)
        self.cache_expiry_days = cache_expiry_days

        os.makedirs(self.cache_directory, exist_ok = True)

    # ── cache addressing ──────────────────────────────────────────────

    @staticmethod
    def _cache_key(ticker):
        """Normalise a ticker into a stable, case-insensitive cache key."""
        if ticker is None:
            raise ValueError("Ticker must not be None.")

        key = str(ticker).strip().upper()
        if not key:
            raise ValueError("Ticker must not be empty.")

        return key

    def _safe_name(self, key):
        safe = _SAFE_TICKER.sub("_", key)

        # Keep ordinary tickers readable; disambiguate anything we had to
        # rewrite so '^GSPC' and '_GSPC' cannot collide on one file.
        if safe != key or set(safe) <= {"."}:
            digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:8]
            safe = f"{safe}-{digest}"

        return safe

    def _path_for(self, key, suffix):
        """Filesystem path for a cache entry, guaranteed to stay inside the cache.

        The ticker used to be concatenated straight into the filename, so a
        ticker of '../../x' wrote outside the cache directory entirely. It also
        made the cache case-sensitive, which is why aapl.parquet and
        AAPL.parquet both existed.
        """
        name = f"{self._safe_name(key)}-{suffix}.parquet"
        path = os.path.abspath(os.path.join(self.cache_directory, name))

        if os.path.commonpath([path, self.cache_directory]) != self.cache_directory:
            raise ValueError(f"Refusing to write outside the cache directory for {key!r}.")

        return path

    def _cache_path(self, key):
        # The adjustment basis is part of the identity of the data. Without it
        # in the filename, flipping AUTO_ADJUST would silently reuse prices on
        # the wrong basis.
        return self._path_for(key, "raw" if not self.AUTO_ADJUST else "adj")

    def _actions_path(self, key):
        return self._path_for(key, "actions")

    # ── frame hygiene ─────────────────────────────────────────────────

    @staticmethod
    def _normalize_index(df):
        """Datetime index, tz-naive, so comparisons never raise."""
        df = df.copy()
        df.index = pd.DatetimeIndex(df.index)
        if df.index.tz is not None:
            df.index = df.index.tz_localize(None)
        return df

    @staticmethod
    def _dedupe(df):
        """Drop duplicate *dates*, keeping the most recently fetched row.

        drop_duplicates() compared whole rows, which deleted genuinely distinct
        trading days that happened to share an OHLCV and left the duplicate
        index labels from an overlapping refetch in place -- those then blew up
        the next reindex.
        """
        if df.index.has_duplicates:
            df = df[~df.index.duplicated(keep = "last")]
        return df.sort_index()

    def _merge(self, cached, fresh):
        if cached is None or cached.empty:
            return fresh
        if fresh is None or fresh.empty:
            return cached
        return self._dedupe(pd.concat([cached, fresh]))

    # ── cache i/o ─────────────────────────────────────────────────────

    def _path_is_stale(self, path):
        # An expiry of zero means "never trust the cache". Handled up front
        # because comparing a just-written file's age against zero is decided
        # by filesystem timestamp granularity, which can report the mtime a
        # hair ahead of now() and make the answer nondeterministic.
        if self.cache_expiry_days <= 0:
            return True

        if not os.path.exists(path):
            return True

        age = datetime.now() - datetime.fromtimestamp(os.path.getmtime(path))
        return age >= timedelta(days = self.cache_expiry_days)

    def _is_stale(self, key):
        return self._path_is_stale(self._cache_path(key))

    def _is_actions_stale(self, key):
        return self._path_is_stale(self._actions_path(key))

    def _load(self, key):
        if key in self.memory_cache:
            return self.memory_cache[key]

        path = self._cache_path(key)
        if not os.path.exists(path):
            return None

        try:
            cached = pd.read_parquet(path)
        except Exception as exc:
            print(f"Warning: cache for {key} is unreadable ({exc}). Refetching.")
            return None

        if cached.empty:
            return None

        cached = self._dedupe(self._normalize_index(cached))
        self.memory_cache[key] = cached
        return cached

    def _store(self, key, df):
        """Persist a frame. Empty frames are never written."""
        if df is None or df.empty:
            return df

        df = self._dedupe(self._normalize_index(df))
        self.memory_cache[key] = df
        df.to_parquet(self._cache_path(key))
        return df

    def _download(self, ticker, start_date, end_date):
        # yfinance treats `end` as exclusive, so asking for [start, end] without
        # the extra day silently omits the last bar.
        data = yf.download(
            ticker,
            start = pd.Timestamp(start_date),
            end = pd.Timestamp(end_date) + pd.Timedelta(days = 1),
            auto_adjust = self.AUTO_ADJUST,
            progress = False,
        )

        if data is None or data.empty:
            return pd.DataFrame()

        return self._normalize_index(data)

    # ── public api ────────────────────────────────────────────────────

    def get_historical_prices(self, ticker, start_date, end_date):
        """Closing prices for [start_date, end_date], served from cache where possible.

        Note the price basis: with AUTO_ADJUST the series is back-adjusted for
        dividends and splits, while transactions record the raw price paid. The
        two disagree on trade dates. Fixing that means moving to raw prices and
        crediting dividends to cash, which is a separate change.
        """
        key = self._cache_key(ticker)
        start_date = pd.Timestamp(start_date)
        end_date = pd.Timestamp(end_date)

        cached = self._load(key)

        if cached is None:
            fresh = self._download(ticker, start_date, end_date)
            if fresh.empty:
                return fresh
            return self._store(key, fresh).loc[start_date:end_date]

        # Reach further back if asked for history we do not hold.
        if start_date < cached.index.min():
            fresh = self._download(ticker, start_date, cached.index.min())
            cached = self._store(key, self._merge(cached, fresh))

        # Extend the tail only once the cache has expired. Coverage governs the
        # head, freshness governs the tail -- previously a heuristic skipped any
        # gap of three business days or fewer and returned stale prices as
        # though they were current.
        if end_date > cached.index.max() and self._is_stale(key):
            fresh = self._download(ticker, cached.index.max(), end_date)
            cached = self._store(key, self._merge(cached, fresh))

        return cached.loc[start_date:end_date]

    def fetch_current_price(self, ticker):
        """Most recent close. Raises rather than returning None on failure."""
        today = datetime.now()

        data = self.get_historical_prices(
            ticker = ticker,
            start_date = today - timedelta(days = 7),
            end_date = today,
        )

        if data is None or data.empty:
            raise ValueError(f"No recent price available for {ticker!r}.")

        return data["Close"].squeeze().iloc[-1]

    def fetch_multiple(self, tickers, start_date, end_date):

        data_multiple = dict()

        for ticker in tickers:
            data_price = self.get_historical_prices(ticker=ticker, start_date= start_date, end_date= end_date)
            data_multiple[ticker] = data_price
        return data_multiple

    def _download_actions(self, ticker):
        actions = yf.Ticker(ticker).actions

        if actions is None or actions.empty:
            return pd.DataFrame(columns = ["Dividends", "Stock Splits"])

        return self._normalize_index(actions)

    def get_actions(self, ticker):
        """Dividends per share and split ratios, indexed by ex-date.

        Both come back on the current (split-adjusted) share basis, matching
        the price series. Fetched whole rather than by window -- the history is
        a handful of rows -- so there is nothing to merge.
        """
        key = self._cache_key(ticker)

        if key in self._actions_cache:
            return self._actions_cache[key]

        path = self._actions_path(key)

        if os.path.exists(path) and not self._is_actions_stale(key):
            try:
                actions = self._normalize_index(pd.read_parquet(path))
                self._actions_cache[key] = actions
                return actions
            except Exception as exc:
                print(f"Warning: actions cache for {key} is unreadable ({exc}). Refetching.")

        actions = self._download_actions(ticker)
        self._actions_cache[key] = actions
        actions.to_parquet(path)
        return actions

    def fetch_dividends(self, ticker, start_date, end_date):
        actions = self.get_actions(ticker)

        if actions.empty or "Dividends" not in actions:
            return pd.Series(dtype = float)

        dividends = actions["Dividends"]
        dividends = dividends[dividends > 0]

        return dividends.loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]

    def fetch_splits(self, ticker, start_date = None, end_date = None):
        """Split ratios by ex-date. A 10-for-1 comes back as 10.0."""
        actions = self.get_actions(ticker)

        if actions.empty or "Stock Splits" not in actions:
            return pd.Series(dtype = float)

        splits = actions["Stock Splits"]
        splits = splits[splits > 0]

        if start_date is not None or end_date is not None:
            start = pd.Timestamp(start_date) if start_date is not None else splits.index.min()
            end = pd.Timestamp(end_date) if end_date is not None else splits.index.max()
            splits = splits.loc[start:end]

        return splits
