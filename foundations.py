import re
import math

returns_stock = [0.02, 0.03, 0.05, 0.07, 0.11, 0.13, 0.17, 0.19, 0.23, 0.29]

geo_return = 1
for i in returns_stock:
    if i > 0:
        geo_return = (1+i) * geo_return

geo_return = math.pow(geo_return, 1/len(returns_stock)) - 1
print(f"Geometric return: {geo_return:.2%}")

        
#1
    
#Calculation of the target semi deviation 
def target_semi_deviation(returns, target_return, ddof=1):
    negative_ret= [r for r in returns if r < target_return]
    if len(negative_ret) == 0:
        raise ValueError('No returns below the target return provided')
    dispersion_target = sum([(r-target_return)**2 for r in negative_ret]) / (len(negative_ret) - ddof)
    return dispersion_target ** 0.5


#2
def mean_return(returns):
    if len(returns) == 0:
        raise ValueError('No returns provided')
    return sum(returns) / len(returns) * 100

#3
def volatility(returns, ddof=1):
    if len(returns) == 0:
        raise ValueError('No returns provided')
    mean = sum(returns) / len(returns)
    variance =sum([(r-mean)**2 for r in returns]) / (len(returns) - ddof)
    return variance ** 0.5 * 100

def sharpe_ratio(returns, risk_free_rate):
    mean = mean_return(returns) / 100
    sdev = volatility(returns) / 100
    if sdev == 0:
        raise ValueError('Standard deviation cannot be zero for Sharpe ratio calculation')
    return (mean - risk_free_rate) / sdev


def rolling_sharpe(returns, window, risk_free_rate):
    # Step 1: Reach to the returns with the window size mentioned

    sr_list=list()
    if window > len(returns):
        raise ValueError('The Window is bigger than the return size')

    
    for i in range(len(returns) - window + 1 ):

        current_list = returns[i:i+window]
        sr_list.append(sharpe_ratio(current_list, risk_free_rate))
        
    return sr_list         
   
sr_rol = rolling_sharpe(returns_stock, 3, 0.05)


