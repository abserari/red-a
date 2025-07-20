from dividend import *
from share_pool import *
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pymongo import MongoClient

# MongoDB连接
client = MongoClient("mongodb://localhost:27017/")
db = client["red_a"]

def calculate_four_year_dividend_rate(code, check_date):
    """计算四年平均分红率"""
    check_dt = datetime.strptime(check_date, "%Y-%m-%d")
    current_year = check_dt.year
    
    # 计算过去4年的分红率
    yearly_yields = []
    
    for year in range(current_year - 4, current_year):
        try:
            result = calculate_static_dividend_yield(code, year)
            if result and 'annual_static_yield' in result and result['annual_static_yield'] is not None:
                yearly_yields.append(result['annual_static_yield'])
        except Exception as e:
            print(f"Error calculating yield for {code} in {year}: {e}")
            continue
    
    if len(yearly_yields) >= 3:  # 至少需要3年的数据
        return np.mean(yearly_yields)
    else:
        return None

def calculate_dividend_std(code, check_date, years=4):
    """计算分红标准差"""
    check_dt = datetime.strptime(check_date, "%Y-%m-%d")
    current_year = check_dt.year
    
    # 获取过去几年的分红数据
    yearly_dividends = []
    
    for year in range(current_year - years, current_year):
        try:
            result = calculate_static_dividend_yield(code, year)
            if result and 'total_dividend' in result and result['total_dividend'] is not None:
                yearly_dividends.append(result['total_dividend'])
        except Exception as e:
            print(f"Error getting dividend for {code} in {year}: {e}")
            continue
    
    if len(yearly_dividends) >= 3:  # 至少需要3年的数据
        return np.std(yearly_dividends) * 100  # 转换为百分比形式
    else:
        return None

def convert_stock_code(code):
    """转换股票代码格式：从 603866.SH 到 sh.603866"""
    parts = code.split('.')
    if len(parts) == 2:
        number, market = parts
        if market == 'SH':
            return f'sh.{number}'
        elif market == 'SZ':
            return f'sz.{number}'
        elif market == 'BJ':
            return f'bj.{number}'
    return code

def screen_stocks(date):
    """筛选符合条件的股票"""
    print(f"\n筛选日期: {date}")
    print("=" * 80)
    
    qualified_stocks = []
    
    for i, (code, info) in enumerate(share_pool.items()):
        # 转换股票代码格式
        converted_code = convert_stock_code(code)
        
        print(f"\n处理第 {i+1}/{len(share_pool)} 只股票: {code}")
        
        try:
            # 1. 计算动态股息率
            dynamic_result = calculate_dynamic_dividend_yield(converted_code, date)
            if not dynamic_result or 'yield_percentage' not in dynamic_result:
                print(f"  - 无法获取动态股息率")
                continue
            
            dynamic_yield = dynamic_result['yield_percentage']
            print(f"  - 动态股息率: {dynamic_yield:.2f}%")
            
            # 检查是否大于6%
            if dynamic_yield <= 6:
                print(f"  - 不符合条件: 动态股息率 {dynamic_yield:.2f}% <= 6%")
                continue
            
            # 2. 计算四年平均分红率
            four_year_rate = calculate_four_year_dividend_rate(converted_code, date)
            if four_year_rate is None:
                print(f"  - 无法计算四年平均分红率")
                continue
            
            print(f"  - 四年平均分红率: {four_year_rate:.2f}%")
            
            # 检查是否大于6%
            if four_year_rate <= 6:
                print(f"  - 不符合条件: 四年平均分红率 {four_year_rate:.2f}% <= 6%")
                continue
            
            # 3. 计算分红标准差
            dividend_std = calculate_dividend_std(converted_code, date)
            if dividend_std is None:
                print(f"  - 无法计算分红标准差")
                continue
            
            print(f"  - 分红标准差: {dividend_std:.2f}")
            
            # 检查是否小于30
            if dividend_std >= 30:
                print(f"  - 不符合条件: 分红标准差 {dividend_std:.2f} >= 30")
                continue
            
            # 符合所有条件
            print(f"  ✓ 符合所有条件!")
            qualified_stocks.append({
                'code': code,
                'converted_code': converted_code,
                'dynamic_yield': dynamic_yield,
                'four_year_rate': four_year_rate,
                'dividend_std': dividend_std,
                'stock_price': dynamic_result.get('stock_price', 0),
                'total_dividend_12m': dynamic_result.get('total_dividend_12m', 0)
            })
            
        except Exception as e:
            print(f"  - 处理错误: {e}")
            continue
    
    return qualified_stocks

def screen_multiple_dates(year):
    """在指定年份的多个日期进行筛选"""
    # 筛选日期列表
    screen_dates = [
        f"{year}-01-01",
        f"{year}-04-01",
        f"{year}-05-01",
        f"{year}-07-01",
        f"{year}-10-01"
    ]
    
    all_results = {}
    
    for date in screen_dates:
        results = screen_stocks(date)
        all_results[date] = results
        
        # 显示结果汇总
        print(f"\n{date} 筛选结果汇总:")
        print(f"符合条件的股票数量: {len(results)}")
        
        if results:
            print("\n符合条件的股票列表:")
            print("-" * 100)
            print(f"{'股票代码':<12} {'动态股息率':<12} {'四年平均分红率':<15} {'分红标准差':<12} {'股价':<10} {'12个月分红':<12}")
            print("-" * 100)
            
            for stock in sorted(results, key=lambda x: x['dynamic_yield'], reverse=True):
                print(f"{stock['code']:<12} "
                      f"{stock['dynamic_yield']:>10.2f}% "
                      f"{stock['four_year_rate']:>13.2f}% "
                      f"{stock['dividend_std']:>10.2f} "
                      f"{stock['stock_price']:>10.2f} "
                      f"{stock['total_dividend_12m']:>10.2f}")
    
    return all_results

# 主程序
if __name__ == "__main__":
    # 可以修改年份进行不同年份的筛选
    year = 2024
    
    print(f"开始筛选 {year} 年的高股息股票")
    print(f"筛选条件:")
    print(f"1. 动态股息率 > 6%")
    print(f"2. 四年平均分红率 > 6%")
    print(f"3. 分红标准差 < 30")
    print(f"筛选日期: 1月1日, 4月1日, 5月1日, 7月1日, 10月1日")
    
    results = screen_multiple_dates(year)
    
    # 统计所有日期都符合条件的股票
    all_dates_stocks = None
    for date, stocks in results.items():
        stock_codes = {s['code'] for s in stocks}
        if all_dates_stocks is None:
            all_dates_stocks = stock_codes
        else:
            all_dates_stocks = all_dates_stocks.intersection(stock_codes)
    
    if all_dates_stocks:
        print(f"\n在所有筛选日期都符合条件的股票 ({len(all_dates_stocks)} 只):")
        for code in sorted(all_dates_stocks):
            print(f"  - {code}")