"""
股票筛选逻辑模块
提供股票筛选的核心功能
"""
import numpy as np
from datetime import datetime
from dividend import calculate_dynamic_dividend_yield, calculate_static_dividend_yield
import logging

logger = logging.getLogger(__name__)

def calculate_four_year_dividend_rate(code, check_date):
    """
    计算四年平均分红率
    
    Args:
        code: 股票代码
        check_date: 检查日期
        
    Returns:
        float: 四年平均分红率，如果数据不足返回None
    """
    check_dt = datetime.strptime(check_date, "%Y-%m-%d")
    current_year = check_dt.year
    
    # 计算过去4年的分红率
    yearly_yields = []
    
    for year in range(current_year - 4, current_year):
        try:
            result = calculate_static_dividend_yield(code, year)
            if result and 'annual_static_yield' in result and result['annual_static_yield'] is not None:
                yearly_yields.append(result['annual_static_yield'])
            elif result and 'error' in result:
                logger.debug(f"Dividend calculation returned error for {code} in {year}: {result['error']}")
        except Exception as e:
            if 'list index' not in str(e).lower():
                logger.warning(f"Error calculating yield for {code} in {year}: {e}")
            continue
    
    if len(yearly_yields) >= 3:  # 至少需要3年的数据
        return np.mean(yearly_yields)
    else:
        return None

def calculate_dividend_std(code, check_date):
    """
    计算分红标准差
    
    Args:
        code: 股票代码
        check_date: 检查日期
        
    Returns:
        float: 分红标准差
    """
    check_dt = datetime.strptime(check_date, "%Y-%m-%d")
    current_year = check_dt.year
    yearly_yields = []
    
    for year in range(current_year - 4, current_year):
        try:
            result = calculate_static_dividend_yield(code, year)
            if result and 'annual_static_yield' in result and result['annual_static_yield'] is not None:
                yearly_yields.append(result['annual_static_yield'])
        except Exception:
            continue
    
    return np.std(yearly_yields) if yearly_yields else 0

def convert_stock_code(code):
    """
    转换股票代码格式
    
    Args:
        code: 原始股票代码（如 600519.SH）
        
    Returns:
        str: 转换后的代码（如 sh.600519）
    """
    if code.endswith('.SH'):
        return 'sh.' + code[:-3]
    elif code.endswith('.SZ'):
        return 'sz.' + code[:-3]
    else:
        return code

def screen_single_stock(code, date, name='', 
                       min_dynamic_yield=6.0, 
                       min_four_year_rate=6.0, 
                       max_dividend_std=30.0):
    """
    筛选单只股票
    
    Args:
        code: 股票代码
        date: 筛选日期
        name: 股票名称
        min_dynamic_yield: 最小动态股息率
        min_four_year_rate: 最小四年平均分红率
        max_dividend_std: 最大分红标准差
        
    Returns:
        dict: 符合条件的股票信息，不符合条件返回None
    """
    try:
        # 转换股票代码格式
        converted_code = convert_stock_code(code)
        
        # 计算动态股息率
        dynamic_result = calculate_dynamic_dividend_yield(converted_code, date)
        
        if not dynamic_result or dynamic_result.get('yield_percentage', 0) <= min_dynamic_yield:
            return None
        
        # 计算四年平均分红率
        four_year_avg = calculate_four_year_dividend_rate(converted_code, date)
        
        if four_year_avg is None or four_year_avg <= min_four_year_rate:
            return None
        
        # 计算分红标准差
        dividend_std = calculate_dividend_std(converted_code, date)
        
        if dividend_std >= max_dividend_std:
            return None
        
        # 返回符合条件的股票信息
        return {
            'code': code,
            'converted_code': converted_code,
            'name': name,
            'dynamic_yield': dynamic_result['yield_percentage'],
            'four_year_rate': four_year_avg,
            'dividend_std': dividend_std,
            'stock_price': dynamic_result.get('stock_price', 0),
            'total_dividend_12m': dynamic_result.get('total_dividend_12m', 0),
            'screening_date': date
        }
        
    except Exception as e:
        if 'list index' not in str(e).lower():
            logger.debug(f"Error screening {code} on {date}: {e}")
        return None