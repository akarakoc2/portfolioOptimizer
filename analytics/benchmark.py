import pandas as pd 
import numpy as np
from data.market_data import MarketDataFetcher

class BenchmarkComperator():
    def __init__(self, portfolio_returns: pd.Series, benchmark_returns: pd.Series, risk_free = 0, mf = None):

        aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1, join='inner').dropna()
        self.port_ret = aligned.iloc[:, 0]
        self.bench_ret = aligned.iloc[:, 1]
        self.rf = risk_free
        self.trading_days = 252
        self.combined = aligned
        self.mf = mf if mf is not None else MarketDataFetcher()

    
    def calculate_beta(self):

        # beta_port = cov(port, benchmark) / var(Rb)
        cov_matrix = self.combined.cov()

        # cov_matrix[0, 1] is Covariance, cov_matrix[1, 1] is Benchmark Variance
        return cov_matrix.iloc[0, 1] / cov_matrix.iloc[1, 1]


    def calculate_correlation(self):

        corr_matrix = self.combined.corr()

        return corr_matrix.iloc[0,1]

    
    def calculate_alpha(self):

        y = self.port_ret - self.rf

        x_raw = self.bench_ret - self.rf

        X = np.vstack([x_raw, np.ones(len(x_raw))]).T

        results = np.linalg.lstsq(X, y, rcond=False)

        coefficients = results[0]
        beta = coefficients[0]
        alpha_daily = coefficients[1]
        alpha_annual = alpha_daily * 252

        return alpha_annual


    def calculate_tracking_error(self):

        #tracking error is sdev of active returns.

        active_return = self.port_ret - self.bench_ret # daily active returns here.

        track_error = active_return.rolling(window=252, min_periods= 21).std()

        annualized_te = track_error * np.sqrt(self.trading_days)


        return annualized_te


    def calculate_overall_ir(self):
        # 1. Get the single overall alpha (inception to date)
        alpha_ann = self.calculate_alpha()
        
        # 2. Get the single overall tracking error (inception to date)
        active_return = self.port_ret - self.bench_ret
        te_ann = active_return.std() * np.sqrt(self.trading_days)
        
        # 3. Calculate IR
        return alpha_ann / te_ann
        

    def get_benchmark_returns(self, benchmark_ticker: str):

        start_date = self.port_ret.index.min() 
        end_date = self.port_ret.index.max()

        df_benchmark = self.mf.get_historical_prices(ticker= benchmark_ticker,
                                                 start_date=start_date,
                                                 end_date = end_date
                                                 )
        df_benchmark = df_benchmark["Close"]
        df_benchmark_returns = df_benchmark.pct_change()

        return df_benchmark_returns
        


        

