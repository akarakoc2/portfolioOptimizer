from domain.transaction import Transaction
from domain.position import Position
from domain.portfolio import Portfolio
from data.market_data import MarketDataFetcher
from analytics.timeseries import PortfolioTimeSeries
from analytics.performance import PerformanceCalculator
from analytics.twr import TWRcalculator
from analytics.mwr import MWRCalculator
from datetime import datetime
import pandas as pd
from reporting.summary import PortfolioSummary

if __name__ == "__main__":

    # 1. Create your transactions
    transaction1 = Transaction('aapl', '2024-01-02','BUY', 5, 185, 2,'USD')
    transaction2 = Transaction('msft', '2024-03-01','BUY', 3, 415, 2,'USD')
    transaction3 = Transaction('aapl', '2026-06-01','BUY', 1, 195, 2,'USD')
   
    # 2. Create your portfolio
    port1 = Portfolio("ATK_1", "USD", creation_date = '2024-01-01')

    # 3. Add transactions directly to the portfolio. 
    # Your Portfolio class will automatically group them into an 'aapl' Position!
    port1.add_transaction(transaction1)
    port1.add_transaction(transaction2)
    port1.add_transaction(transaction3)
    
    # 4. Run your timeseries
    fetcher = MarketDataFetcher()
    time_s = PortfolioTimeSeries(port1, fetcher=fetcher, start_date="2024-01-01")
    
    portfolio_val = time_s.portfolio_value()
    portfolio_ret = time_s.portfolio_returns()
    c = PerformanceCalculator(portfolio_value = portfolio_val, portfolio_returns = portfolio_ret)
    total_return = c.total_return()
    ann_return = c.annualized_return()
    sharpe_rat = c.sharpe_ratio()
    max_dd= c.max_drawdown()


    print(f"Annualized return of the portfolio holdings: {ann_return:.2%}")
    print(f"Annualized sharpe ratio of the portfolio holdings: {sharpe_rat}")
    print(f"Annualized maximum drawdown of the portfolio holdings: {max_dd}")
    print(100* "=")

    # ── 4. TIME WEIGHTED RETURN ──────────────────────
    cash_flow_dates = time_s.cashflow_dates

   
    print(100* "=")
    twr_calc = TWRcalculator(portfolio_val, cashflow_dates=cash_flow_dates)
    print("Time weighted return: ",twr_calc.calculate_twr())
    print(100* "=")

    cash_flow_mwr = time_s.mwr_cashflows
    today_port_worth = time_s.portfolio_value().iloc[-1]
    inception_date = pd.Timestamp(port1.creation_date)
    # ── 5. MONEY WEIGHTED RETURN ─────────────────────
    print(100* "=")
    mwr_calc = MWRCalculator(cashflows=cash_flow_mwr,current_value=today_port_worth,inception_date=inception_date )
    print("Money weighted return: ", mwr_calc.calculate_mwr())
    print(100* "=")

    print(port1.positions)



    ps = PortfolioSummary(portfolio=port1,fetcher=fetcher, benchmark_ticker="SPY")
    summary = ps.get_summary(),

    print(summary)




        
                
            






