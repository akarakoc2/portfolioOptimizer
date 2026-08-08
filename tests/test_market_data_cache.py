"""Cache behaviour of MarketDataFetcher.

These matter most under a UI, where every widget change re-runs the pipeline:
a cache that shrinks, or silently serves stale prices, turns into constant
refetching and numbers that drift between refreshes.

_download is stubbed throughout, so nothing here touches the network.
"""
import os

import pandas as pd
import pytest

from data.market_data import MarketDataFetcher


def frame(start, end, price=100.0):
    days = pd.bdate_range(start, end)
    return pd.DataFrame({"Close": [price] * len(days)}, index=days)


class Recorder(MarketDataFetcher):
    """Serves a fixed history and records what was asked for."""

    history = frame("2024-01-01", "2024-06-28")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.requests = []

    def _download(self, ticker, start_date, end_date):
        self.requests.append((pd.Timestamp(start_date), pd.Timestamp(end_date)))
        window = self.history.loc[pd.Timestamp(start_date):pd.Timestamp(end_date)]
        return window.copy()


@pytest.fixture
def fetcher(tmp_path):
    return Recorder(cache_directory=str(tmp_path))


def test_a_narrow_request_does_not_shrink_the_cache(fetcher):
    """fetch_current_price asks for 7 days and used to overwrite all history."""
    fetcher.get_historical_prices("AAPL", "2024-01-01", "2024-06-28")
    assert len(fetcher.memory_cache["AAPL"]) > 100

    fetcher.cache_expiry_days = 0          # force the stale path
    fetcher.get_historical_prices("AAPL", "2024-06-20", "2024-06-28")

    assert len(fetcher.memory_cache["AAPL"]) > 100, "narrow request truncated the cache"
    on_disk = pd.read_parquet(fetcher._cache_path("AAPL"))
    assert len(on_disk) > 100, "narrow request truncated the parquet"


def test_ticker_case_shares_one_cache_entry(fetcher):
    """aapl.parquet and AAPL.parquet both existed in the real cache directory."""
    fetcher.get_historical_prices("aapl", "2024-01-01", "2024-03-01")
    fetcher.get_historical_prices("AAPL", "2024-01-01", "2024-03-01")

    assert len(fetcher.requests) == 1, "case difference caused a second download"
    assert len(os.listdir(fetcher.cache_directory)) == 1


def test_ticker_cannot_escape_the_cache_directory(fetcher):
    """'../../x' used to resolve outside the cache directory entirely."""
    path = fetcher._cache_path(fetcher._cache_key("../../pwned"))
    assert os.path.dirname(path) == fetcher.cache_directory


def test_awkward_tickers_get_distinct_files(fetcher):
    caret = fetcher._cache_path(fetcher._cache_key("^GSPC"))
    plain = fetcher._cache_path(fetcher._cache_key("_GSPC"))
    assert caret != plain, "sanitised tickers collided on one file"


def test_identical_rows_on_distinct_days_survive(fetcher):
    """drop_duplicates() compared rows, deleting flat days."""
    flat = pd.DataFrame({"Close": [100.0, 100.0, 100.0]},
                        index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04"]))
    assert len(fetcher._dedupe(flat)) == 3


def test_overlapping_fetches_do_not_leave_duplicate_dates(fetcher):
    """Duplicate index labels used to break the next reindex."""
    first = pd.DataFrame({"Close": [100.0, 101.0]},
                         index=pd.to_datetime(["2024-01-02", "2024-01-03"]))
    second = pd.DataFrame({"Close": [101.5, 102.0]},
                          index=pd.to_datetime(["2024-01-03", "2024-01-04"]))

    merged = fetcher._merge(first, second)

    assert not merged.index.has_duplicates
    assert merged.loc[pd.Timestamp("2024-01-03"), "Close"] == 101.5   # newer wins
    merged.reindex(pd.bdate_range("2024-01-02", "2024-01-04"))        # must not raise


def test_short_gaps_are_actually_fetched(fetcher):
    """A gap of <= 3 business days was skipped, serving stale prices as current."""
    fetcher.get_historical_prices("AAPL", "2024-01-01", "2024-06-25")
    fetcher.cache_expiry_days = 0

    result = fetcher.get_historical_prices("AAPL", "2024-01-01", "2024-06-28")

    assert result.index.max() == pd.Timestamp("2024-06-28"), "short tail gap was not filled"


def test_fresh_cache_is_not_refetched(fetcher):
    """Expiry governs the tail; a fresh cache should serve without a download."""
    fetcher.get_historical_prices("AAPL", "2024-01-01", "2024-06-28")
    before = len(fetcher.requests)

    fetcher.memory_cache.clear()                       # force the disk path
    fetcher.get_historical_prices("AAPL", "2024-01-01", "2024-07-31")

    assert len(fetcher.requests) == before, "refetched a cache that is still fresh"


def test_tz_aware_downloads_do_not_break_comparisons(tmp_path):
    """index.min() <= naive Timestamp raised TypeError on tz-aware data."""

    class TzFetcher(Recorder):
        def _download(self, ticker, start_date, end_date):
            data = super()._download(ticker, start_date, end_date)
            data.index = data.index.tz_localize("America/New_York")
            return data

    fetcher = TzFetcher(cache_directory=str(tmp_path))
    fetcher.get_historical_prices("AAPL", "2024-01-01", "2024-03-01")
    result = fetcher.get_historical_prices("AAPL", "2024-02-01", "2024-04-01")

    assert result.index.tz is None
    assert not result.empty


def test_empty_downloads_are_not_cached(fetcher):
    """An empty parquet used to be written, then warned about on every later read."""
    result = fetcher.get_historical_prices("AAPL", "2030-01-01", "2030-02-01")

    assert result.empty
    assert os.listdir(fetcher.cache_directory) == []
