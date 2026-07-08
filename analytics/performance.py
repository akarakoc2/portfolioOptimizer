import pandas as pd

class PerformanceCalculator():
    def __init__(self, portfolio_value, portfolio_returns, risk_free = 0):
        
        self.portfolio_value = portfolio_value
        self.portfolio_returns = portfolio_returns
        
        self.trading_days = 252

    def total_return(self):
        
        growth_factors = self.portfolio_returns + 1
        total_return = growth_factors.prod() - 1 

        return total_return

    





