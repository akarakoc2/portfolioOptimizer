from domain.transaction import Transaction
from domain.position import Position
from domain.portfolio import Portfolio
from data.market_data import MarketDataFetcher
import pandas as pd
import yfinance as yf

if __name__ == "__main__":
    
    # transcation_test = Transaction('AAPL', 20220603,'BUY', 3,5,1,'EUR')
    # transaction2 = Transaction('aapl', 20220603,'BUY', 1,6,4,'EUR')
    # pos1 = Position(transcation_test)
    # pos1.add_transaction(transaction2)
    # port1 = Portfolio("ATK_1", "EUR")
    # port1.add_transaction(transaction=transcation_test)
    
    # print(transaction2)
    # print('\n')
    # print(pos1)
    # fetcher = MarketDataFetcher()
    # last_price = fetcher.fetch_current_price(ticker = "AAPL")
    # print(last_price)

    # tickers = ["aapl","tsla","oust","msft"]
    # data_multiple = fetcher.fetch_multiple(tickers, start_date = "2025-01-01", end_date = "2026-01-01")
    # print(data_multiple)

    ticker = "aapl" 
    div = yf.Ticker(ticker).dividends
    print(div["2025-01-01":"2026-01-01"])
