import os
import yfinance as yf
import pandas as pd 

class MarketDataFetcher():
    def __init__(self, cache_directory = os.path.join("cache"), cache_expiry_days = 1):
        self.memory_cache = dict()
        self.cache_directory = cache_directory
        self.cache_expiry_days = cache_expiry_days

        #directly checking if the cache exist if not the directory will be created automatically. 
        os.makedirs(self.cache_directory, exist_ok = True)

    def get_historical_prices(self, ticker, start_date, end_date):
        if ticker in self.memory_cache:
            return pd.DataFrame(self)







