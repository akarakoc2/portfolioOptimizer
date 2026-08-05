import os
import sys

import pandas as pd
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class FakeFetcher:
    """Deterministic price source, so the tests never touch the network.

    Prices are supplied as {ticker: {date: close}} and forward-filled onto the
    requested range, mirroring what MarketDataFetcher hands back.
    """

    def __init__(self, prices, calendar=None):
        self.prices = prices
        self.calendar = calendar or pd.bdate_range("2024-01-01", "2024-03-29")
        self.calls = []

    def get_historical_prices(self, ticker, start_date, end_date):
        self.calls.append(ticker)
        if ticker not in self.prices:
            return pd.DataFrame()

        series = pd.Series(
            {pd.Timestamp(k): v for k, v in self.prices[ticker].items()}
        ).sort_index()
        series = series.reindex(self.calendar).ffill().bfill()
        return pd.DataFrame({"Close": series})

    def fetch_current_price(self, ticker):
        return self.get_historical_prices(ticker, None, None)["Close"].iloc[-1]


@pytest.fixture
def fetcher():
    return FakeFetcher(
        {
            # Flat on purpose: any return these tests report is contamination.
            "AAPL": {"2024-01-01": 100.0},
            "MSFT": {"2024-01-01": 200.0},
        }
    )
