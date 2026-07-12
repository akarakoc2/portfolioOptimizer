from domain.transaction import Transaction
from domain.position import Position
from domain.portfolio import Portfolio
from data.market_data import MarketDataFetcher
from analytics.timeseries import PortfolioTimeSeries
from analytics.performance import PerformanceCalculator
from analytics.twr import TWRcalculator


if __name__ == "__main__":

    # 1. Create your transactions
    transaction1 = Transaction('aapl', '2024-01-01','BUY', 1, 120, 2,'USD')
    transaction2 = Transaction('msft', '2024-06-01','BUY', 1, 120, 2,'USD')

    # 2. Create your portfolio
    port1 = Portfolio("ATK_1", "USD", creation_date = '2024-01-01')

    # 3. Add transactions directly to the portfolio. 
    # Your Portfolio class will automatically group them into an 'aapl' Position!
    port1.add_transaction(transaction1)
    port1.add_transaction(transaction2)
    
    # 4. Run your timeseries
    fetcher = MarketDataFetcher()
    time_s = PortfolioTimeSeries(port1, fetcher=fetcher, start_date="2024-01-01")
    
    a = time_s.portfolio_value()
    b = time_s.portfolio_returns()
    c = PerformanceCalculator(portfolio_value = a, portfolio_returns = b)
    d = c.total_return()
    ann_return = c.annualized_return()
    sharpe_rat = c.sharpe_ratio()

    print(d)

    print(f"Annualized return of the portfolio holdings: {ann_return:.2%}")
    print(f"Annualized sharpe ratio of the portfolio holdings: {sharpe_rat}")


    print(c.max_drawdown())
    
    print(c.get_tearsheet_returns())

    print(100* "=")

    cash_flow_dates = time_s.cashflow_dates
    print(cash_flow_dates)

    twr_calc = TWRcalculator(a,cashflow_dates=cash_flow_dates)
    print(100* "=")
    print(twr_calc._get_subperiod_boundries())





    



        
                
            






