from domain.portfolio import Portfolio
from domain.position import Position
from domain.transaction import Transaction
from datetime import datetime
import pandas as pd

class PortfolioTimeSeries():
    def __init__(self, portfolio, fetcher, start_date = None, end_date = None):
        self.portfolio = portfolio
        if start_date is None:
            self.start_date = self.portfolio.creation_date
        else:
            self.start_date = start_date
        if end_date is None:
            self.end_date = datetime.now()
        else:
            self.end_date = end_date

        self.fetcher = fetcher
        self.tickers = self.portfolio.positions.keys()
        self.trading_days = pd.bdate_range(self.start_date, self.end_date)

    def build_holding_frames(self):
        all_transactions=[]

        for position in self.portfolio.positions.values():
            for transaction in position.transactions:
                all_transactions.append(transaction)
        all_transactions = sorted(all_transactions, key = lambda t: t.transaction_date)

        list_dicts = []
       
        for transaction in all_transactions:
            date = pd.Timestamp(transaction.transaction_date)
            ticker = transaction.ticker
            

            if transaction.transaction_type == 'BUY':
                quantity_norm = transaction.quantity
                transaction_dict = {"date":date, "ticker":ticker, "quantity": quantity_norm}
                list_dicts.append(transaction_dict)
            else:
                quantity_norm = - transaction.quantity
                transaction_dict = {"date":date, "ticker":ticker, "quantity": quantity_norm}
                list_dicts.append(transaction_dict)

        df = pd.DataFrame(list_dicts)
        df = df.pivot_table(index="date", columns="ticker", values="quantity", aggfunc="sum")      
        df = df.cumsum()
        df = df.reindex(self.trading_days)
        df = df.ffill()
        df= df.fillna(0)
        return df
    

    def build_price_frames(self):
        prices = dict()
        
        # Fetch the data
        df = self.fetcher.fetch_multiple(self.tickers, self.start_date, self.end_date)

        for ticker in df.keys():
            # Defensive checks from our previous fix
            if df[ticker] is None or df[ticker].empty:
                print(f"WARNING: Data for {ticker} is missing or empty. Skipping...")
                continue 
            
            if "Close" not in df[ticker]:
                print(f"WARNING: 'Close' column missing for {ticker}. Skipping...")
                continue

            # Extract the Close column data
            close_column = df[ticker]["Close"]
            
            
            if isinstance(close_column, pd.DataFrame):
                close_column = close_column.squeeze()

            prices[ticker] = close_column

        prices_df = pd.DataFrame(prices)
        
        if prices_df.empty:
            raise ValueError("No valid price data was returned for any tickers in the portfolio.")

        prices_df.index = prices_df.index.tz_localize(None)
        prices_df = prices_df.reindex(self.trading_days)
        
        if prices_df.empty:
            raise ValueError("Data reindexing problem has occurred please check the reindexing")
            
        prices_df = prices_df.ffill()
        prices_df = prices_df.fillna(0)

        return prices_df


    def build_value_frame(self):
        holding_frames = self.build_holding_frames()
        build_prices = self.build_price_frames()
        daily_values = holding_frames * build_prices   
        return daily_values
    
        
    def portfolio_value(self):

        portfolio_val = self.build_value_frame().sum(axis=1)

        return portfolio_val
    
    def portfolio_returns(self):
        port_val = self.portfolio_value()
        percentage_chg = port_val.pct_change()
        percentage_chg = percentage_chg.dropna()
        percentage_chg = percentage_chg.replace([float('inf'), float('-inf')], float('nan'))
        return percentage_chg