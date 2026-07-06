from domain.transaction import Transaction
from domain.position import Position
from domain.portfolio import Portfolio
from data.market_data import MarketDataFetcher
import pandas as pd
import yfinance as yf
from analytics.timeseries import PortfolioTimeSeries

if __name__ == "__main__":

    # 1. Create your transactions
    transaction1 = Transaction('aapl', '2024-01-01','BUY', 5, 150, 1,'USD')
    transaction2 = Transaction('aapl', '2024-01-02','BUY', 5, 150, 1,'USD')


    # 2. Create your portfolio
    port1 = Portfolio("ATK_1", "USD", creation_date = '2024-01-01')

    # 3. Add transactions directly to the portfolio. 
    # Your Portfolio class will automatically group them into an 'aapl' Position!
    port1.add_transaction(transaction1)
    port1.add_transaction(transaction2)
    
    # 4. Run your timeseries
    fetcher = MarketDataFetcher()
    time_s = PortfolioTimeSeries(port1, fetcher=fetcher, start_date="2024-01-01", end_date="2024-02-01")
    
    a = time_s.portfolio_value()
    print(a)
