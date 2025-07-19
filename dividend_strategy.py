"""
分红策略分析模块

提供股票分红数据获取、价格分析和收益率计算等功能。
"""

from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union

import akshare as ak
import pandas as pd


def get_stock_dividend_info(stock_code: str) -> pd.DataFrame:
    """
    获取单个股票的分红公告信息
    
    Parameters:
    -----------
    stock_code : str
        股票代码，如 '000001' 或 '600000'
    
    Returns:
    --------
    pd.DataFrame
        包含分红公告信息的数据框，包括公告日期、股权登记日、除权除息日、
        派息金额、送股数量、转增数量、股息率等信息
    """
    try:
        # 获取股票分红数据
        dividend_df = ak.stock_dividend_cninfo(symbol=stock_code)
        
        # 筛选有用的列
        if not dividend_df.empty:
            useful_columns = ['公告日期', '股权登记日', '除权除息日', 
                            '派息(税前)(元)', '送股(股)', '转增(股)', '股息率(%)']
            available_columns = [col for col in useful_columns if col in dividend_df.columns]
            dividend_df = dividend_df[available_columns]
            
            # 转换日期格式
            date_columns = ['公告日期', '股权登记日', '除权除息日']
            for col in date_columns:
                if col in dividend_df.columns:
                    dividend_df[col] = pd.to_datetime(dividend_df[col])
            
            # 按除权除息日降序排列
            if '除权除息日' in dividend_df.columns:
                dividend_df = dividend_df.sort_values('除权除息日', ascending=False)
        
        return dividend_df
    
    except Exception as e:
        print(f"获取股票 {stock_code} 分红信息时出错: {e}")
        return pd.DataFrame()


def get_stock_price_history(stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    获取股票历史价格数据
    
    Parameters:
    -----------
    stock_code : str
        股票代码，如 '000001' 或 '600000'
    start_date : str
        开始日期，格式 'YYYYMMDD'
    end_date : str
        结束日期，格式 'YYYYMMDD'
    
    Returns:
    --------
    pd.DataFrame
        包含历史价格的数据框，索引为日期，包含开盘价、收盘价、
        最高价、最低价、成交量、成交额、涨跌幅等列
    """
    try:
        # 判断股票市场
        if stock_code.startswith('6'):
            symbol = f"sh{stock_code}"
        elif stock_code.startswith('0') or stock_code.startswith('3'):
            symbol = f"sz{stock_code}"
        else:
            symbol = stock_code
        
        # 获取历史数据
        df = ak.stock_zh_a_hist(symbol=symbol, 
                              period="daily", 
                              start_date=start_date, 
                              end_date=end_date, 
                              adjust="qfq")  # 前复权
        
        if not df.empty:
            # 重命名列以便使用
            df = df.rename(columns={
                '日期': 'date',
                '开盘': 'open',
                '收盘': 'close',
                '最高': 'high',
                '最低': 'low',
                '成交量': 'volume',
                '成交额': 'amount',
                '涨跌幅': 'pct_change'
            })
            
            # 确保日期列是datetime格式
            df['date'] = pd.to_datetime(df['date'])
            df = df.set_index('date')
        
        return df
    
    except Exception as e:
        print(f"获取股票 {stock_code} 价格数据时出错: {e}")
        return pd.DataFrame()


def calculate_dividend_profit_rate(
    stock_code: str, 
    dividend_date: Union[str, datetime], 
    days_before: int = 7, 
    days_after: int = 0
) -> Optional[Dict[str, Union[str, float]]]:
    """
    计算分红理论利润率
    
    Parameters:
    -----------
    stock_code : str
        股票代码
    dividend_date : str or datetime
        除权除息日
    days_before : int, optional
        提前买入天数，默认7天
    days_after : int, optional
        延后卖出天数，默认0天（除权日当天卖出）
    
    Returns:
    --------
    dict or None
        包含买入价、卖出价、理论收益率等信息的字典，如果计算失败则返回None
        
        返回字典包含以下键：
        - stock_code: 股票代码
        - dividend_date: 除权除息日
        - buy_date: 实际买入日期
        - sell_date: 实际卖出日期
        - buy_price: 买入价格
        - sell_price: 卖出价格
        - dividend_per_share: 每股分红金额
        - price_change_rate: 价格变动收益率(%)
        - dividend_yield: 分红收益率(%)
        - total_profit_rate: 总收益率(%)
    """
    try:
        # 确保日期格式正确
        if isinstance(dividend_date, str):
            dividend_date = pd.to_datetime(dividend_date)
        
        # 计算买入和卖出日期
        buy_date = dividend_date - timedelta(days=days_before)
        sell_date = dividend_date + timedelta(days=days_after)
        
        # 获取价格数据（扩大范围以确保获取到交易日数据）
        start_date = (buy_date - timedelta(days=10)).strftime('%Y%m%d')
        end_date = (sell_date + timedelta(days=10)).strftime('%Y%m%d')
        
        price_df = get_stock_price_history(stock_code, start_date, end_date)
        
        if price_df.empty:
            return None
        
        # 找到最接近买入日期的交易日
        buy_prices = price_df[price_df.index <= buy_date].tail(1)
        if buy_prices.empty:
            return None
        buy_price = buy_prices['close'].iloc[0]
        actual_buy_date = buy_prices.index[0]
        
        # 找到最接近卖出日期的交易日
        sell_prices = price_df[price_df.index >= sell_date].head(1)
        if sell_prices.empty:
            # 如果没有找到，使用最后一个交易日
            sell_prices = price_df.tail(1)
        sell_price = sell_prices['close'].iloc[0]
        actual_sell_date = sell_prices.index[0]
        
        # 计算收益率
        profit_rate = (sell_price - buy_price) / buy_price * 100
        
        # 获取分红信息
        dividend_info = get_stock_dividend_info(stock_code)
        dividend_per_share = 0
        if not dividend_info.empty and '派息(税前)(元)' in dividend_info.columns:
            # 找到对应日期的分红
            mask = dividend_info['除权除息日'] == dividend_date
            if mask.any():
                dividend_per_share = dividend_info.loc[mask, '派息(税前)(元)'].iloc[0]
                # 每10股派息转换为每股派息
                dividend_per_share = dividend_per_share / 10 if dividend_per_share else 0
        
        # 计算包含分红的总收益率
        total_profit_rate = profit_rate + (dividend_per_share / buy_price * 100)
        
        return {
            'stock_code': stock_code,
            'dividend_date': dividend_date.strftime('%Y-%m-%d'),
            'buy_date': actual_buy_date.strftime('%Y-%m-%d'),
            'sell_date': actual_sell_date.strftime('%Y-%m-%d'),
            'buy_price': round(buy_price, 2),
            'sell_price': round(sell_price, 2),
            'dividend_per_share': round(dividend_per_share, 4),
            'price_change_rate': round(profit_rate, 2),
            'dividend_yield': round(dividend_per_share / buy_price * 100, 2),
            'total_profit_rate': round(total_profit_rate, 2)
        }
    
    except Exception as e:
        print(f"计算分红理论利润率时出错: {e}")
        return None


def analyze_stock_dividend_strategy(
    stock_code: str, 
    recent_years: int = 3,
    buy_timings: List[int] = None
) -> pd.DataFrame:
    """
    分析股票的历史分红策略表现
    
    Parameters:
    -----------
    stock_code : str
        股票代码
    recent_years : int, optional
        分析最近几年的数据，默认3年
    buy_timings : list of int, optional
        要测试的买入时机列表（提前天数），默认为[7, 14, 30]
    
    Returns:
    --------
    pd.DataFrame
        历次分红的收益分析数据框，包含每次分红在不同买入时机下的收益情况
    """
    if buy_timings is None:
        buy_timings = [7, 14, 30]
    
    try:
        # 获取分红信息
        dividend_info = get_stock_dividend_info(stock_code)
        
        if dividend_info.empty or '除权除息日' not in dividend_info.columns:
            print(f"股票 {stock_code} 没有分红数据")
            return pd.DataFrame()
        
        # 筛选最近几年的分红
        cutoff_date = datetime.now() - timedelta(days=365 * recent_years)
        recent_dividends = dividend_info[
            (dividend_info['除权除息日'] > cutoff_date) & 
            (dividend_info['除权除息日'] < datetime.now())
        ]
        
        results = []
        for _, row in recent_dividends.iterrows():
            dividend_date = row['除权除息日']
            
            # 计算不同买入时机的收益
            for days_before in buy_timings:
                result = calculate_dividend_profit_rate(
                    stock_code, 
                    dividend_date, 
                    days_before=days_before
                )
                
                if result:
                    result['days_before'] = days_before
                    results.append(result)
        
        if results:
            results_df = pd.DataFrame(results)
            return results_df
        else:
            return pd.DataFrame()
    
    except Exception as e:
        print(f"分析股票分红策略时出错: {e}")
        return pd.DataFrame()


def get_dividend_strategy_summary(analysis_results: pd.DataFrame) -> pd.DataFrame:
    """
    汇总分红策略分析结果
    
    Parameters:
    -----------
    analysis_results : pd.DataFrame
        analyze_stock_dividend_strategy 函数返回的分析结果
    
    Returns:
    --------
    pd.DataFrame
        按买入时机分组的汇总统计信息
    """
    if analysis_results.empty:
        return pd.DataFrame()
    
    summary = analysis_results.groupby('days_before').agg({
        'total_profit_rate': ['mean', 'std', 'count', 'min', 'max'],
        'price_change_rate': 'mean',
        'dividend_yield': 'mean'
    }).round(2)
    
    # 计算成功率（正收益的比例）
    success_rates = analysis_results.groupby('days_before')['total_profit_rate'].apply(
        lambda x: (x > 0).sum() / len(x) * 100
    ).round(1)
    
    summary[('total_profit_rate', 'success_rate')] = success_rates
    
    return summary