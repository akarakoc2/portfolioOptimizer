from domain.portfolio import Portfolio
from analytics.timeseries import PortfolioTimeSeries
from analytics.performance import PerformanceCalculator
from analytics.mwr import MWRCalculator
from analytics.twr import TWRcalculator
import pandas as pd
from analytics.benchmark import BenchmarkComparator

class PortfolioSummary():
    def __init__(self, portfolio: Portfolio, fetcher, benchmark_ticker = "SPY", risk_free = 0):
        self.portfolio = portfolio
        self.fetcher = fetcher
        self.benchmark_ticker = benchmark_ticker
        self.rf = risk_free
        self.port_inception = self.portfolio.creation_date
        self.ts = PortfolioTimeSeries(portfolio= portfolio, fetcher=fetcher)
        self.portfolio_value = self.ts.portfolio_value()
        self.portfolio_returns = self.ts.portfolio_returns()
        self.perf = PerformanceCalculator(self.portfolio_value, self.portfolio_returns, risk_free=risk_free)
        self.mwr = MWRCalculator(
            self.ts.external_cashflows,
            current_value=self.portfolio_value.iloc[-1],
            inception_date=pd.Timestamp(self.port_inception),
            terminal_date=self.portfolio_value.index[-1],
        )
        self.port_positions = self.portfolio.open_positions()
        self.twr = TWRcalculator(self.portfolio_returns)

        benchmark_data = self.fetcher.get_historical_prices(ticker=self.benchmark_ticker,start_date=self.portfolio_value.index.min(),end_date=self.portfolio_value.index.max())
        self.bnch_return = benchmark_data["Close"].squeeze().pct_change().dropna()

        self.bnch = BenchmarkComparator(portfolio_returns=self.portfolio_returns, benchmark_returns=self.bnch_return, risk_free=self.rf, mf=self.fetcher)

    def get_summary(self):
        return {
            "identity": self._get_identity(),
            "value_summary": self._get_value_summary(),
            "performance_metrics": self._get_performance_metrics(),
            "period_returns": self._get_period_returns(),
            "timeseries": self._get_timeseries(),
            "transactions": self._get_transactions(),
            "positions": self._get_positions(),
            "benchmark": self._get_benchmark()
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

        # Net cash you actually put in, not the book value of what you still
        # hold. The old sum of net_quantity * average_cost_basis ignored fees
        # and silently wrote off every realised gain on a sold position.
        total_invested = -sum(amount for _, amount in self.ts.external_cashflows)

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
        period_returns["Inception"] = self.perf.total_return()
        return period_returns



        

    def _get_timeseries(self, base_value = 100):
        return {
            "portfolio_value": self.portfolio_value,
            "portfolio_returns": self.portfolio_returns,
            "growth_of_1usd": (1 + self.portfolio_returns).cumprod() * base_value
        }


    def _get_transactions(self):
        transactions = []
        
        for position in self.portfolio.all_positions():
            for transaction in position.transactions:
                transactions.append({
                    "date": transaction.transaction_date,
                    "ticker": transaction.ticker,
                    "type": transaction.transaction_type,
                    "quantity": transaction.quantity,
                    "price": transaction.cost_per_unit,
                    "fees": transaction.fees,
                    "total_cost": transaction.total_cost,
                    "currency": transaction.currency
                })
        
        transactions = sorted(transactions, key=lambda x: x["date"])
        return transactions


    def _get_positions(self):
        positions = []

        # Mark against the same valuation the rest of the report uses. Calling
        # fetch_current_price here dated the numerator to today while the
        # denominator was the last close, so weights never summed to 1.
        last_prices = self.ts.build_price_frames().iloc[-1]
        # Split-adjusted, so it shares a basis with the price. pos.net_quantity
        # is the share count as recorded, which is stale after a split.
        last_quantities = self.ts.build_holding_frames().iloc[-1]
        last_fx = self.ts.build_fx_frames().iloc[-1]
        currencies = self.ts.instrument_currencies
        total_value = self.portfolio_value.iloc[-1]

        for pos in self.portfolio.open_positions():
            # Price stays in the currency it is quoted in; everything that gets
            # summed or weighted is converted, so the two are not comparable
            # without the rate. Hence reporting both.
            current_price = last_prices[pos.ticker]
            rate = last_fx[pos.ticker]
            quantity = last_quantities[pos.ticker]
            current_value = current_price * quantity * rate
            # Total outlay is split-invariant; per-share cost is not, so derive
            # it from the adjusted count to stay comparable with current_price.
            cost_basis = pos.average_cost_basis * pos.net_quantity * rate
            unrealized_pnl = current_value - cost_basis

            positions.append({
                "ticker" : pos.ticker,
                "quantity": quantity,
                "currency": currencies[pos.ticker],
                "avg_cost": cost_basis / quantity if quantity else float('nan'),
                "current_price": current_price,
                "current_value": current_value,
                "unrealized_pnl": unrealized_pnl,
                "weight": current_value / total_value if total_value else float('nan'),
                "is_open": pos.is_open,
                "unrealized_pnl_pct": unrealized_pnl / cost_basis if cost_basis else float('nan')
            }
            )

        return positions


    def _get_benchmark(self):
        return {
        "benchmark_ticker": self.benchmark_ticker,
        "benchmark_return": (1 + self.bnch_return).prod() - 1,
        "alpha": self.bnch.calculate_alpha(),
        "beta": self.bnch.calculate_beta(),
        "correlation": self.bnch.calculate_correlation(),
        "tracking_error": self.bnch.calculate_tracking_error().iloc[-1],
        "information_ratio": self.bnch.calculate_overall_ir(),
        "outperformance": self.perf.total_return() - ((1 + self.bnch_return).prod() - 1),
        "benchmark_value_series": self.bnch_return,
        "growth_of_1usd_benchmark": ((self.bnch_return) + 1).cumprod() * 100
    }


        

