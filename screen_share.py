from dividend import *
from share_pool import *

date = "2025-05-11"
# 显示前5个
for i, (code, info) in enumerate(share_pool.items()):
    if i < 5:
        print(f"代码: {code}, ")
        
        print(calculate_dynamic_dividend_yield(code, date)['yield_percentage'])

    else:
        break
