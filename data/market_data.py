import os
import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta

class MarketDataFetcher():
    def __init__(self, cache_directory = os.path.join("cache"), cache_expiry_days = 1):
        self.memory_cache = dict()
        self.cache_directory = cache_directory
        self.cache_expiry_days = cache_expiry_days

        #directly checking if the cache exist if not the directory will be created automatically. 
        os.makedirs(self.cache_directory, exist_ok = True)

    def get_historical_prices(self, ticker, start_date, end_date):

        file_path = os.path.join(self.cache_directory + ticker + ".parquet")
        if ticker in self.memory_cache:
            return self.memory_cache[ticker]
        
        elif os.path.exists(file_path):
            #we have to translate the time to normal date because when we read it gives with seconds since 1970
            last_save = os.path.getmtime(file_path)
            last_save = datetime.fromtimestamp(last_save)
            today = datetime.now()
            diff = today - last_save
            
            if diff < timedelta(self.cache_expiry_days):
                cache_data = pd.read_parquet(file_path)
                self.memory_cache[ticker] = cache_data
                return cache_data
        else:
            dat = yf.download(ticker, start = start_date, end = end_date)
            self.memory_cache[ticker] = dat
            dat.to_parquet(file_path)
            return dat







