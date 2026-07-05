from domain.transaction import Transaction
from domain.position import Position
from domain.portfolio import Portfolio
from data.market_data import MarketDataFetcher
import pandas as pd


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
    # appl_data = fetcher.get_historical_prices(ticker = "OUST", start_date = '2024-01-01', end_date = "2025-01-01")
    