import pandas as pd 
import numpy as np

class BenchmarkComperator():
    def __init__(self, portfolio_returns: pd.Series, benchmark_returns: pd.Series, risk_free = 0):

        aligned = pd.concat([portfolio_returns, benchmark_returns], axis=1, join='inner').dropna()
        self.port_ret = aligned.iloc[:, 0]
        self.bench_ret = aligned.iloc[:, 1]
        self.rf = risk_free
        self.trading_days = 252
        self.combined = aligned

    
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
    


        

