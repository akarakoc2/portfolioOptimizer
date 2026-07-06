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


    #this fetching helper function to enable correct data ask from the yfinance, asking only data we miss
    def _fetch_missing_data(self, ticker, cached_data, start_date, end_date):
            #filepath handling for the L2 cache & also timestamp
            
            file_path = os.path.join(self.cache_directory, ticker + ".parquet")
            start_date = pd.Timestamp(start_date)
            end_date = pd.Timestamp(end_date)

            
            if start_date < cached_data.index.min():
                business_days = pd.bdate_range(start=start_date, end= cached_data.index.min()) #this gives us the business days
                if len(business_days) > 3: #business day check if we have enough to ask from yfinance
                    df_1 = yf.download(ticker, start = start_date, end = cached_data.index.min())
                    cached_data = pd.concat([df_1,cached_data])
                    cached_data =cached_data.sort_index().drop_duplicates()

            if end_date > cached_data.index.max():
                business_days = pd.bdate_range(start=cached_data.index.max(), end= end_date)
                if len(business_days) > 3:
                    df_1 = yf.download(ticker, start = cached_data.index.max(), end = end_date)
                    cached_data = pd.concat([cached_data, df_1])
                    cached_data = cached_data.sort_index().drop_duplicates()
   
            self.memory_cache[ticker] = cached_data
            cached_data.to_parquet(file_path)

            return cached_data[start_date:end_date]

    def get_historical_prices(self, ticker, start_date, end_date):

        #file path and timestamp for the entries here
        file_path = os.path.join(self.cache_directory, ticker + ".parquet")
        start_date = pd.Timestamp(start_date)
        end_date = pd.Timestamp(end_date)

        #helper function for the data handling over cache

        #here the 1st layer of the memory cache
        if ticker in self.memory_cache:
            dat1 = self.memory_cache[ticker]
            if dat1.index.min() <= start_date and dat1.index.max() >= end_date:
                return dat1[start_date:end_date]
            else:
                return self._fetch_missing_data(ticker, dat1, start_date, end_date) 
            
        #L2 layer of the cache 
        elif os.path.exists(file_path):
            #we have to translate the time to normal date because when we read it gives with seconds since 1970
            last_save = os.path.getmtime(file_path)
            last_save = datetime.fromtimestamp(last_save)
            today = datetime.now()
            diff = today - last_save
            
            if diff < timedelta(self.cache_expiry_days):
                cache_data = pd.read_parquet(file_path)
                self.memory_cache[ticker] = cache_data
                if cache_data.index.min() <= start_date and cache_data.index.max() >= end_date:
                    return cache_data[start_date:end_date]
                else:
                    return self._fetch_missing_data(ticker, cache_data, start_date, end_date)
            else:
                print(f"Cache expired for {ticker}. Fetching fresh data...")
                dat = yf.download(ticker, start=start_date, end=end_date)
                self.memory_cache[ticker] = dat
                dat.to_parquet(file_path)
                return dat

        #L3 cache layer here.. 
        else:
            dat = yf.download(ticker, start = start_date, end = end_date)
            self.memory_cache[ticker] = dat
            dat.to_parquet(file_path)
            return dat


    def fetch_current_price(self, ticker):
        today = datetime.now()

        try:
            current_data = self.get_historical_prices(ticker = ticker, start_date = today - timedelta(days=7), end_date = today)
            current_data = current_data["Close"].iloc[-1]
            return current_data
        
        except Exception as e:
            print(f"The price value for today can not be fetched due to {e}")

            
    def fetch_multiple(self, tickers, start_date, end_date):

        data_multiple = dict()

        for ticker in tickers:
            data_price = self.get_historical_prices(ticker=ticker, start_date= start_date, end_date= end_date)
            data_multiple[ticker] = data_price
        return data_multiple


    def fetch_dividends(self, ticker, start_date, end_date):

        dividends= yf.Ticker(ticker).dividends
        filter_div = dividends[start_date:end_date]
        
        return filter_div



                






