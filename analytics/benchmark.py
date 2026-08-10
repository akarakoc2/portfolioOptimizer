import pandas as pd 
import numpy as np
from data.market_data import MarketDataFetcher

class BenchmarkComparator():
    """Portfolio measured against a benchmark.

    `risk_free` is an annual rate throughout, matching PerformanceCalculator.
    It is de-annualised where a daily figure is needed -- previously the same
    number was subtracted from annualised returns in one place and from daily
    returns in another, so any non-zero rate produced nonsense.
    """

    def __init__(self, portfolio_returns: pd.Series, benchmark_returns: pd.Series, risk_free = 0, mf = None):

        aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1, join='inner').dropna()
        self.port_ret = aligned.iloc[:, 0]
        self.bench_ret = aligned.iloc[:, 1]
        self.rf = risk_free
        self.trading_days = 252
        self.combined = aligned
        self.mf = mf

    @property
    def daily_rf(self):
        return self.rf / self.trading_days

    
    def calculate_beta(self):

        # beta_port = cov(port, benchmark) / var(Rb)
        cov_matrix = self.combined.cov()

        # cov_matrix[0, 1] is Covariance, cov_matrix[1, 1] is Benchmark Variance
        return cov_matrix.iloc[0, 1] / cov_matrix.iloc[1, 1]


    def calculate_correlation(self):

        corr_matrix = self.combined.corr()

        return corr_matrix.iloc[0,1]

    
    def calculate_alpha(self):

        # Daily excess returns, so the annual rate has to be de-annualised.
        y = self.port_ret - self.daily_rf

        x_raw = self.bench_ret - self.daily_rf

        X = np.vstack([x_raw, np.ones(len(x_raw))]).T

        # rcond=None is the documented "use the machine-precision default";
        # rcond=False coerced to 0.0, which disables the singular-value cutoff.
        results = np.linalg.lstsq(X, y, rcond=None)

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
        


        

