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
        ticker_starts = self.ticker_start_dates

        for ticker in self.tickers:
            ticker_start = ticker_starts[ticker]
            data = self.fetcher.get_historical_prices(
                ticker=ticker,
                start_date=ticker_start,
                end_date=self.end_date
            )
            if data is None or data.empty:
                print(f"Warning: No data for {ticker}")
                continue
            prices[ticker] = data["Close"].squeeze()
                                                  
        prices_df = pd.DataFrame(prices)            
        prices_df.index = prices_df.index.tz_localize(None)
        prices_df = prices_df.reindex(self.trading_days)
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
        portfolio_val = portfolio_val.dropna()

        return portfolio_val
    
    def portfolio_returns(self):
        port_val = self.portfolio_value()
        percentage_chg = port_val.pct_change()
        
        percentage_chg = percentage_chg.replace([float('inf'), float('-inf')], float('nan'))
        percentage_chg = percentage_chg.dropna()
        return percentage_chg
    

    @property
    def cashflow_dates(self):
        dates = []
        for position in self.portfolio.positions.values():
            for transaction in position.transactions:
                date = transaction.transaction_date
                dates.append(pd.Timestamp(date))


        return sorted(list(set(dates)))

    @property
    def mwr_cashflows(self):
        cashflows = list()

        for position in self.portfolio.positions.values():
            for transaction in position.transactions:
                date =  pd.Timestamp(transaction.transaction_date)

                if transaction.transaction_type == "BUY":
                    amount = - transaction.total_cost
 
                elif transaction.transaction_type == "SELL":
                    amount = + transaction.total_cost
                else:
                    raise NameError("Please indicate a correct transaction type such ass BUY, SELL")

                cashflows.append((date, amount))
                

        cashflows = sorted(cashflows, key=lambda x: x[0])
        return cashflows
    
    @property
    def ticker_start_dates(self):
        start_dates = {}
        
        for ticker, position in self.portfolio.positions.items():
            first_transaction = position.transactions[0]
            start_dates[ticker] = pd.Timestamp(first_transaction.transaction_date)
        
        return start_dates