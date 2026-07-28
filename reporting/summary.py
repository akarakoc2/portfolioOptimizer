from domain.portfolio import Portfolio
from analytics.timeseries import PortfolioTimeSeries
from analytics.performance import PerformanceCalculator
import datetime
from analytics.mwr import MWRCalculator
from analytics.twr import TWRcalculator
import pandas as pd

class PortfolioSummary():
    def __init__(self, portfolio: Portfolio, fetcher, benchmark_ticker = "SPY"):
        self.portfolio = portfolio
        self.fetcher = fetcher
        self.benchmark_ticker = benchmark_ticker
        self.port_inception = self.portfolio.creation_date
        self.ts = PortfolioTimeSeries(portfolio= portfolio, fetcher=fetcher)
        self.twr_dates = self.ts.cashflow_dates
        self.portfolio_value = self.ts.portfolio_value()
        self.portfolio_returns = self.ts.portfolio_returns()
        self.perf = PerformanceCalculator(self.portfolio_value, self.portfolio_returns)
        self.mwr = MWRCalculator(self.ts.mwr_cashflows, current_value=self.portfolio_value.iloc[-1], inception_date= pd.Timestamp(self.port_inception ))
        self.twr = TWRcalculator(self.portfolio_value, self.twr_dates)

    def get_summary(self):
        return {
            "identity": self._get_identity(),
            "value_summary": self._get_value_summary(),
            "performance_metrics": self._get_performance_metrics(),
        }


    def _get_identity(self):

        identity_dict = {"Portfolio Name": self.portfolio.portfolio_name,
                         "Base Currency" : self.portfolio.portfolio_currency,
                         "Inception Date": self.portfolio.creation_date,
                         "Open Positions": len(self.portfolio.open_positions()),
                         "Total Positions": len(self.portfolio.all_positions())
                         }
        return identity_dict


    def _get_value_summary(self):

        # calculate total invested
        total_invested = 0
        for position in self.portfolio.all_positions():
            position_cost = position.net_quantity * position.average_cost_basis
            total_invested += position_cost

        current_value = self.portfolio_value.iloc[-1]
        total_profit = current_value - total_invested
        
        value_dict = { "Current Value": current_value,
                       "Total Invested":total_invested,
                       "Total Profit":total_profit,
                       "Total Return Percentage": self.perf.total_return()
        }

        return value_dict


    def _get_performance_metrics(self):


        performance_metrics = {"Annualized Return": self.perf.annualized_return(),
                               "Volatility": self.perf.volatility(),
                               "Sharpe Ratio": self.perf.sharpe_ratio(),
                               "Max Drawdown": self.perf.max_drawdown(),
                               "Money Weighted return":self.mwr.calculate_mwr(),
                               "Time Weighted Return": self.twr.calculate_twr(),

        }
        return performance_metrics


    def _get_period_returns(self):
        period_returns = self.perf.get_tearsheet_returns()

        

        

        