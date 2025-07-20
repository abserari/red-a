import baostock as bs
import pandas as pd
from datetime import datetime, timedelta
import logging
import threading
import sys

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

# 设置pandas显示选项
pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', 20)
pd.set_option('display.width', None)

# 创建一个全局锁来保护 BaoStock API 调用
baostock_lock = threading.Lock()

# 全局变量，标记是否已登录
_baostock_logged_in = False

def ensure_baostock_login():
    """确保 BaoStock 已登录"""
    global _baostock_logged_in
    if not _baostock_logged_in:
        with baostock_lock:
            if not _baostock_logged_in:  # 双重检查
                result = bs.login()
                logger.info(f'login respond error_code: {result.error_code}')
                logger.info(f'login respond error_msg: {result.error_msg}')
                _baostock_logged_in = True
                return result
    return None

# 如果是直接运行或导入，先登录一次
if __name__ == "__main__" or not hasattr(sys.modules[__name__], '__file__'):
    ensure_baostock_login()
else:
    # 延迟登录，让多进程环境下每个进程自己登录
    import os
    if os.environ.get('BAOSTOCK_AUTO_LOGIN', '1') == '1':
        ensure_baostock_login()

def fetch_dividend_data(code, years):
    """
    获取指定年份的分红数据
    
    Args:
        code (str): 股票代码，格式如 'sh.600519' 或 'sz.000002'
        years (list): 年份列表，如 [2023, 2024] 或 [2024]
    
    Returns:
        DataFrame: 分红数据，如果无数据返回None
        
    调用示例:
        # 获取单年数据
        df = fetch_dividend_data('sh.600519', [2023])
        
        # 获取多年数据
        df = fetch_dividend_data('sz.000002', [2022, 2023, 2024])
        
        # 返回的DataFrame包含以下主要字段:
        # - dividOperateDate: 除权除息日
        # - dividCashPsBeforeTax: 税前每股现金分红
        # - dividRegistDate: 股权登记日
        # - dividPayDate: 派息日
    """
    ensure_baostock_login()  # 确保已登录
    
    all_dividends = []
    fields = None
    
    for year in years:
        try:
            # 尝试查询分红数据，处理可能的 IndexError
            try:
                with baostock_lock:
                    rs_dividend = bs.query_dividend_data(code=code, year=str(year))
            except IndexError as e:
                logger.warning(f"BaoStock IndexError for dividend data {code} in {year}, skipping")
                continue
            
            if rs_dividend.error_code == '0' and rs_dividend.fields:
                # 只在第一次设置fields，或者验证fields一致
                if fields is None:
                    fields = rs_dividend.fields
                
                dividend_list = []
                with baostock_lock:
                    while (rs_dividend.error_code == '0') & rs_dividend.next():
                        row_data = rs_dividend.get_row_data()
                        # 确保行数据长度与字段数匹配
                        if len(row_data) == len(fields):
                            dividend_list.append(row_data)
                
                if dividend_list:
                    all_dividends.extend(dividend_list)
        except Exception as e:
            # 记录错误但继续处理其他年份
            if 'list index' in str(e).lower():
                logger.debug(f"No dividend data for {code} in {year} (list index error)")
            else:
                logger.warning(f"Error fetching dividend data for {code} in {year}: {type(e).__name__}: {e}", exc_info=True)
            continue
    
    if not all_dividends or fields is None:
        return None
    
    try:
        return pd.DataFrame(all_dividends, columns=fields)
    except Exception as e:
        logger.error(f"Error creating DataFrame for {code}: {e}", exc_info=True)
        return None


def identify_dividend_fields(dividend_df):
    """
    识别分红数据中的日期字段和现金分红字段
    
    Args:
        dividend_df (DataFrame): 从fetch_dividend_data返回的分红数据
    
    Returns:
        tuple: (date_field, cash_field) 如果找不到返回 (None, None)
        
    调用示例:
        dividend_df = fetch_dividend_data('sh.600519', [2023])
        date_field, cash_field = identify_dividend_fields(dividend_df)
        # 返回: ('dividOperateDate', 'dividCashPsBeforeTax')
        
    说明:
        - 优先使用 dividOperateDate 作为日期字段（除权除息日）
        - 优先使用 dividCashPsBeforeTax 作为现金分红字段（税前每股现金分红）
    """
    date_field = None
    cash_field = None
    
    for field in dividend_df.columns:
        # 寻找日期字段 - 优先使用 dividOperateDate (除权除息日)
        if field == 'dividOperateDate':
            date_field = field
            break
        elif field in ['dividPayDate', 'dividRegistDate']:
            date_field = field
        elif 'date' in field.lower() or '除权' in field or '除息' in field:
            date_field = field
    
    for field in dividend_df.columns:
        # 寻找现金分红字段 - 通常是 dividCashPsBeforeTax (税前每股现金分红)
        if field == 'dividCashPsBeforeTax':
            cash_field = field
            break
        elif 'cash' in field.lower() or '现金' in field:
            cash_field = field
    
    return date_field, cash_field


def filter_12month_dividends(dividend_df, date_field, cash_field, check_date):
    """
    筛选过去12个月的分红数据
    
    Args:
        dividend_df (DataFrame): 分红数据
        date_field (str): 日期字段名，如 'dividOperateDate'
        cash_field (str): 现金分红字段名，如 'dividCashPsBeforeTax'
        check_date (str): 检查日期，格式 'YYYY-MM-DD'
    
    Returns:
        tuple: (filtered_df, total_cash_12m)
            - filtered_df: 筛选后的DataFrame
            - total_cash_12m: 12个月分红总额
            
    调用示例:
        dividend_df = fetch_dividend_data('sh.600519', [2023, 2024])
        date_field, cash_field = identify_dividend_fields(dividend_df)
        df_12m, total = filter_12month_dividends(
            dividend_df, date_field, cash_field, '2024-07-01'
        )
        # 返回: (DataFrame, 25.911)  # 过去12个月分红总额
    """
    check_date_obj = pd.to_datetime(check_date)
    
    # 转换日期和现金分红为数值
    dividend_df[date_field] = pd.to_datetime(dividend_df[date_field], errors='coerce')
    dividend_df[cash_field] = pd.to_numeric(dividend_df[cash_field], errors='coerce')
    
    # 筛选过去12个月的分红
    twelve_months_ago = check_date_obj - timedelta(days=365)
    dividend_df_12m = dividend_df[
        (dividend_df[date_field] > twelve_months_ago) & 
        (dividend_df[date_field] <= check_date_obj)
    ]
    
    total_cash_12m = dividend_df_12m[cash_field].sum()
    
    return dividend_df_12m, total_cash_12m


def fetch_stock_price(code, check_date):
    """
    获取指定日期附近的股价
    
    Args:
        code (str): 股票代码，格式如 'sh.600519'
        check_date (str): 检查日期，格式 'YYYY-MM-DD'
    
    Returns:
        dict: 包含日期和收盘价的字典，如果无数据返回None
        
    调用示例:
        # 获取2024-07-01附近的股价
        price_data = fetch_stock_price('sh.600519', '2024-07-01')
        # 返回: {
        #     'date': datetime(2024, 7, 1),
        #     'close': 1390.94
        # }
        
        # 如果指定日期非交易日，会返回最近的交易日价格
        price_data = fetch_stock_price('sz.000002', '2024-07-06')  # 周六
        # 返回: {
        #     'date': datetime(2024, 7, 5),  # 周五
        #     'close': 13.85
        # }
    """
    ensure_baostock_login()  # 确保已登录
    
    try:
        start_date = (pd.to_datetime(check_date) - timedelta(days=7)).strftime('%Y-%m-%d')
        end_date = (pd.to_datetime(check_date) + timedelta(days=7)).strftime('%Y-%m-%d')
        
        logger.debug(f"Fetching price for {code} from {start_date} to {end_date}")
        
        # 尝试修复 baostock 的 IndexError 问题
        try:
            with baostock_lock:
                rs_price = bs.query_history_k_data_plus(
                    code, "date,close",
                    start_date=start_date,
                    end_date=end_date,
                    frequency="d", adjustflag="2"
                )
        except IndexError as e:
            logger.warning(f"BaoStock IndexError for {code}, trying without adjustflag")
            # 尝试不使用 adjustflag 参数
            try:
                with baostock_lock:
                    rs_price = bs.query_history_k_data_plus(
                        code, "date,close",
                        start_date=start_date,
                        end_date=end_date,
                        frequency="d"
                    )
            except Exception as e2:
                logger.error(f"Failed to fetch price data for {code} even without adjustflag: {e2}")
                return None
        
        if rs_price.error_code != '0':
            logger.warning(f"Query failed for {code}: error_code={rs_price.error_code}, error_msg={rs_price.error_msg}")
            return None
        
        price_list = []
        row_count = 0
        with baostock_lock:
            while (rs_price.error_code == '0') & rs_price.next():
                try:
                    row_data = rs_price.get_row_data()
                    row_count += 1
                    if row_data and len(row_data) >= 2:
                        price_list.append(row_data)
                    else:
                        logger.warning(f"Invalid row data for {code}: {row_data}")
                except Exception as e:
                    logger.error(f"Error processing row {row_count} for {code}: {e}")
                    logger.error(f"Row data type: {type(row_data) if 'row_data' in locals() else 'undefined'}")
                    if 'row_data' in locals():
                        logger.error(f"Row data content: {row_data}")
                    continue
    except Exception as e:
        logger.error(f"Error in fetch_stock_price for {code} on {check_date}", exc_info=True)
        return None
    
    if not price_list:
        return None
    
    # Debug: Check data structure mismatch
    expected_fields = rs_price.fields if isinstance(rs_price.fields, list) else rs_price.fields.split(',')
    
    if price_list and len(price_list[0]) != len(expected_fields):
        logger.error(f"Column mismatch for {code} on {check_date}:")
        logger.error(f"Expected columns: {expected_fields} (count: {len(expected_fields)})")
        logger.error(f"Actual data columns: {len(price_list[0])} columns")
        logger.error(f"First row data: {price_list[0]}")
        logger.error(f"All row data (first 3 rows):")
        for i, row in enumerate(price_list[:3]):
            logger.error(f"  Row {i}: {row}")
        
        # 打印 rs_price 对象的所有属性
        logger.error(f"rs_price attributes: {dir(rs_price)}")
        if hasattr(rs_price, 'fields'):
            logger.error(f"rs_price.fields type: {type(rs_price.fields)}")
            logger.error(f"rs_price.fields content: {rs_price.fields}")
        
        # Try to use only the expected columns
        price_list = [[row[i] for i in range(len(expected_fields))] for row in price_list]
    
    price_df = pd.DataFrame(price_list, columns=expected_fields)
    price_df['close'] = pd.to_numeric(price_df['close'], errors='coerce')
    
    # 找最接近的交易日
    price_df['date'] = pd.to_datetime(price_df['date'])
    target_date = pd.to_datetime(check_date)
    price_df['date_diff'] = abs(price_df['date'] - target_date)
    closest_price = price_df.loc[price_df['date_diff'].idxmin()]
    
    return {
        'date': closest_price['date'],
        'close': closest_price['close']
    }


def find_ex_dividend_dates(dividend_df, date_field, year=None):
    """
    查找除权除息日
    
    Args:
        dividend_df (DataFrame): 分红数据
        date_field (str): 日期字段名，通常为 'dividOperateDate'
        year (int, optional): 指定年份，如果为None则返回所有除权除息日
    
    Returns:
        list: 除权除息日列表（datetime对象）
        
    调用示例:
        dividend_df = fetch_dividend_data('sh.600519', [2022, 2023, 2024])
        date_field, _ = identify_dividend_fields(dividend_df)
        
        # 获取所有除权除息日
        all_dates = find_ex_dividend_dates(dividend_df, date_field)
        # 返回: [datetime(2022, 6, 28), datetime(2023, 6, 30), datetime(2024, 6, 18)]
        
        # 获取2023年的除权除息日
        dates_2023 = find_ex_dividend_dates(dividend_df, date_field, 2023)
        # 返回: [datetime(2023, 6, 30)]
    """
    if dividend_df is None or dividend_df.empty:
        return []
    
    # 确保日期字段是datetime类型
    dividend_df[date_field] = pd.to_datetime(dividend_df[date_field], errors='coerce')
    
    if year is not None:
        # 筛选指定年份的除权除息日
        year_df = dividend_df[dividend_df[date_field].dt.year == year]
        return year_df[date_field].dropna().tolist()
    else:
        return dividend_df[date_field].dropna().tolist()


def calculate_static_dividend_yield(code, year, use_previous_day=True):
    """
    计算静态股息率 - 使用指定年份的除权除息日前一天的股价
    
    Args:
        code (str): 股票代码，格式如 'sh.600519'
        year (int): 年份，如 2023
        use_previous_day (bool): 是否使用除权除息日前一天的股价，默认True
    
    Returns:
        dict: 包含静态股息率信息的字典
        
    调用示例:
        # 计算2023年静态股息率
        result = calculate_static_dividend_yield('sh.600519', 2023)
        # 返回: {
        #     'year': 2023,
        #     'dividends': [{
        #         'ex_dividend_date': datetime(2023, 6, 30),
        #         'dividend_amount': 25.911,
        #         'price_date': datetime(2023, 6, 29),
        #         'stock_price': 1578.57,
        #         'static_yield': 1.64
        #     }],
        #     'total_dividend': 25.911,
        #     'annual_static_yield': 1.64,
        #     'base_price': 1578.57
        # }
        
        # 使用除权除息日当天价格
        result = calculate_static_dividend_yield('sh.603565', 2024, use_previous_day=False)
    """
    try:
        # 获取该年度的分红数据
        dividend_df = fetch_dividend_data(code, [year])
        if dividend_df is None:
            return {'error': '无分红数据'}
        
        # 识别字段
        date_field, cash_field = identify_dividend_fields(dividend_df)
        if not date_field or not cash_field:
            return {'error': '无法识别必要字段'}
        
        # 转换数据类型
        dividend_df[date_field] = pd.to_datetime(dividend_df[date_field], errors='coerce')
        dividend_df[cash_field] = pd.to_numeric(dividend_df[cash_field], errors='coerce')
        
        # 查找该年的除权除息日
        ex_dividend_dates = find_ex_dividend_dates(dividend_df, date_field, year)
        if not ex_dividend_dates:
            return {'error': f'{year}年无除权除息记录'}
    except Exception as e:
        logger.error(f"Error processing dividend data for {code} in {year}", exc_info=True)
        return {'error': f'处理分红数据时出错: {str(e)}'}
    
    results = []
    
    for ex_date in ex_dividend_dates:
        try:
            # 获取该次分红的金额
            dividend_rows = dividend_df[dividend_df[date_field] == ex_date]
            if dividend_rows.empty:
                continue
            
            # 检查是否为空
            if len(dividend_rows) == 0:
                logger.debug(f"No dividend rows found for {code} on {ex_date}")
                continue
                
            try:
                dividend_amount = dividend_rows[cash_field].iloc[0]
            except IndexError:
                logger.error(f"IndexError accessing dividend amount for {code} on {ex_date}")
                logger.error(f"  - dividend_rows shape: {dividend_rows.shape}")
                logger.error(f"  - cash_field: {cash_field}")
                logger.error(f"  - dividend_rows columns: {dividend_rows.columns.tolist()}")
                logger.error(f"  - dividend_rows content: {dividend_rows.head()}")
                continue
                
            if pd.isna(dividend_amount) or dividend_amount <= 0:
                continue
            
            # 确定价格日期
            price_date = ex_date - timedelta(days=1) if use_previous_day else ex_date
            
            # 获取股价
            price_data = fetch_stock_price(code, price_date.strftime('%Y-%m-%d'))
            
            if price_data and price_data.get('close', 0) > 0:
                # 计算该次分红的股息率
                static_yield = (dividend_amount / price_data['close']) * 100
                
                results.append({
                    'ex_dividend_date': ex_date,
                    'dividend_amount': dividend_amount,
                    'price_date': price_data['date'],
                    'stock_price': price_data['close'],
                    'static_yield': static_yield
                })
        except Exception as e:
            logger.error(f"Error processing dividend for {code} on {ex_date}: {type(e).__name__}: {e}")
            logger.error(f"Details - Code: {code}, Ex-date: {ex_date}, Price date: {price_date.strftime('%Y-%m-%d') if 'price_date' in locals() else 'N/A'}")
            continue
    
    # 计算年度总静态股息率
    if results:
        try:
            total_dividend = sum(r['dividend_amount'] for r in results)
            # 使用第一次除权除息前的股价作为基准
            base_price = results[0]['stock_price']
            annual_static_yield = (total_dividend / base_price) * 100
            
            return {
                'year': year,
                'dividends': results,
                'total_dividend': total_dividend,
                'annual_static_yield': annual_static_yield,
                'base_price': base_price
            }
        except Exception as e:
            logger.error(f"Error calculating annual static yield for {code}", exc_info=True)
            return {'error': f'计算年度静态股息率时出错: {str(e)}'}
    
    return {'error': '无法计算静态股息率'}


def calculate_dividend_yield(total_cash_12m, stock_price):
    """
    计算股息率
    
    Args:
        total_cash_12m (float): 过去12个月每股现金分红总额
        stock_price (float): 股价
    
    Returns:
        float: 股息率（百分比），如果无法计算返回None
        
    调用示例:
        # 计算股息率
        yield_rate = calculate_dividend_yield(0.72, 8.26)
        # 返回: 8.71  # 表示8.71%
        
        # 茅台示例
        yield_rate = calculate_dividend_yield(25.911, 1581.57)
        # 返回: 1.64  # 表示1.64%
        
        # 无分红情况
        yield_rate = calculate_dividend_yield(0, 100)
        # 返回: None
    """
    if stock_price > 0 and total_cash_12m > 0:
        return (total_cash_12m / stock_price) * 100
    return None


def calculate_dynamic_dividend_yield(code, check_date):
    """
    计算动态股息率 - 使用过去12个月的分红数据和当前股价
    
    Args:
        code (str): 股票代码，格式如 'sh.600519'
        check_date (str): 检查日期，格式 'YYYY-MM-DD'
    
    Returns:
        dict: 包含动态股息率信息的字典
        
    调用示例:
        result = calculate_dynamic_dividend_yield('sh.603565', '2024-07-01')
        # 返回: {
        #     'yield_percentage': 8.71,
        #     'total_dividend_12m': 0.72,
        #     'stock_price': 8.26,
        #     'price_date': datetime(2024, 7, 1),
        #     'dividend_count': 1,
        #     'dividend_details': [{
        #         'date': datetime(2024, 4, 30),
        #         'amount': 0.72
        #     }]
        # }
        
        # 无分红情况
        result = calculate_dynamic_dividend_yield('sh.000001', '2024-07-01')
        # 返回: {'error': '过去12个月无分红'}
    """
    check_date_obj = pd.to_datetime(check_date)
    
    # 获取过去两年的分红数据以确保覆盖12个月
    year1 = check_date_obj.year
    year2 = check_date_obj.year - 1
    
    dividend_df = fetch_dividend_data(code, [year1, year2])
    if dividend_df is None:
        return {'error': '无分红数据'}
    
    # 识别字段
    date_field, cash_field = identify_dividend_fields(dividend_df)
    if not date_field or not cash_field:
        return {'error': '无法识别必要字段'}
    
    # 筛选过去12个月的分红
    dividend_df_12m, total_cash_12m = filter_12month_dividends(
        dividend_df, date_field, cash_field, check_date
    )
    
    # 获取当前股价
    price_data = fetch_stock_price(code, check_date)
    if price_data is None:
        return {'error': '无价格数据'}
    
    # 如果过去12个月无分红
    if total_cash_12m == 0:
        return {
            'yield_percentage': 0,
            'total_dividend_12m': 0,
            'stock_price': price_data['close'],
            'price_date': price_data['date'],
            'dividend_count': 0,
            'dividend_details': []
        }
    
    # 计算股息率
    yield_percentage = calculate_dividend_yield(total_cash_12m, price_data['close'])
    
    # 获取分红明细
    dividend_details = []
    for _, row in dividend_df_12m.iterrows():
        dividend_details.append({
            'date': row[date_field],
            'amount': row[cash_field]
        })
    
    return {
        'yield_percentage': yield_percentage,
        'total_dividend_12m': total_cash_12m,
        'stock_price': price_data['close'],
        'price_date': price_data['date'],
        'dividend_count': len(dividend_df_12m),
        'dividend_details': dividend_details
    }


def calculate_comprehensive_dividend_yield(code, check_date):
    """
    综合计算股息率 - 同时返回动态和静态股息率
    
    Args:
        code (str): 股票代码，格式如 'sh.600519'
        check_date (str): 检查日期，格式 'YYYY-MM-DD'
    
    Returns:
        dict: 包含动态和静态股息率的综合信息
        
    调用示例:
        result = calculate_comprehensive_dividend_yield('sh.603565', '2024-07-01')
        # 返回: {
        #     'code': 'sh.603565',
        #     'check_date': '2024-07-01',
        #     'dynamic_yield': {
        #         'yield_percentage': 8.71,
        #         'total_dividend_12m': 0.72,
        #         'stock_price': 8.26,
        #         'price_date': datetime(2024, 7, 1),
        #         'dividend_count': 1
        #     },
        #     'static_yield': {
        #         'yield_percentage': 8.75,
        #         'total_dividend': 0.72,
        #         'base_price': 8.23,
        #         'dividend_count': 1
        #     },
        #     'details': {}
        # }
        
    说明:
        - dynamic_yield: 基于过去12个月分红和当前股价计算
        - static_yield: 基于当年分红和除权除息日前股价计算
    """
    check_date_obj = pd.to_datetime(check_date)
    result = {
        'code': code,
        'check_date': check_date,
        'dynamic_yield': None,
        'static_yield': None,
        'details': {}
    }
    
    # 计算动态股息率（过去12个月）
    dynamic_result = calculate_dynamic_dividend_yield(code, check_date)
    
    if 'error' not in dynamic_result and dynamic_result['yield_percentage'] is not None:
        result['dynamic_yield'] = {
            'yield_percentage': dynamic_result['yield_percentage'],
            'total_dividend_12m': dynamic_result['total_dividend_12m'],
            'stock_price': dynamic_result['stock_price'],
            'price_date': dynamic_result['price_date'],
            'dividend_count': dynamic_result['dividend_count']
        }
    
    # 计算静态股息率（当年）
    current_year = check_date_obj.year
    static_result = calculate_static_dividend_yield(code, current_year)
    
    if 'error' not in static_result:
        result['static_yield'] = {
            'yield_percentage': static_result['annual_static_yield'],
            'total_dividend': static_result['total_dividend'],
            'base_price': static_result['base_price'],
            'dividend_count': len(static_result['dividends'])
        }
    
    return result


# 测试计算某只股票在特定日期的股息率
def test_dividend_yield_calculation(code, check_date, dividend_year=None):
    """
    测试股息率计算 - 使用过去12个月的分红数据
    公式：过去12个月每股派息金额 / 股价 × 100%
    """
    check_date_obj = pd.to_datetime(check_date)
    print(f"\n测试 {code} 在 {check_date} 的股息率（过去12个月分红）：")
    
    # 1. 获取过去两年的分红数据以确保覆盖12个月内的所有分红
    year1 = check_date_obj.year
    year2 = check_date_obj.year - 1
    
    dividend_df = fetch_dividend_data(code, [year1, year2])
    if dividend_df is None:
        print("  - 无分红数据")
        return
    
    # 显示字段信息（仅第一次）
    print(f"  - 分红数据字段: {list(dividend_df.columns)}")
    
    # 2. 识别字段
    date_field, cash_field = identify_dividend_fields(dividend_df)
    
    if not date_field:
        print("  - 未找到日期字段")
        return
    
    if not cash_field:
        print("  - 未找到现金分红字段")
        print(f"  - 可用字段: {list(dividend_df.columns)}")
        return
    
    # 3. 筛选过去12个月的分红
    dividend_df_12m, total_cash_12m = filter_12month_dividends(
        dividend_df, date_field, cash_field, check_date
    )
    
    print(f"  - 使用字段 '{cash_field}' 和 '{date_field}'")
    print(f"  - 过去12个月分红记录数: {len(dividend_df_12m)}")
    print(f"  - 过去12个月每股现金分红总额: {total_cash_12m:.4f}")
    
    if len(dividend_df_12m) > 0:
        print("  - 分红明细:")
        for _, row in dividend_df_12m.iterrows():
            print(f"    {row[date_field].strftime('%Y-%m-%d')}: {row[cash_field]:.4f}元/股")
    
    # 4. 获取股价
    price_data = fetch_stock_price(code, check_date)
    if price_data is None:
        print("  - 无价格数据")
        return
    
    print(f"  - 使用 {price_data['date'].strftime('%Y-%m-%d')} 的收盘价: {price_data['close']}")
    
    # 5. 计算股息率
    dividend_yield = calculate_dividend_yield(total_cash_12m, price_data['close'])
    
    if dividend_yield is not None:
        print(f"  - 股息率: {dividend_yield:.2f}%")
    elif price_data['close'] <= 0:
        print("  - 无法计算股息率（股价无效）")
    else:
        print("  - 过去12个月无分红，股息率: 0.00%")

def test_static_dividend_yield(code, year):
    """
    测试静态股息率计算
    """
    print(f"\n测试 {code} 在 {year}年的静态股息率：")
    result = calculate_static_dividend_yield(code, year)
    
    if 'error' in result:
        print(f"  - 错误: {result['error']}")
    else:
        print(f"  - 年份: {result['year']}")
        print(f"  - 年度总分红: {result['total_dividend']:.4f}元/股")
        print(f"  - 基准股价: {result['base_price']:.2f}")
        print(f"  - 年度静态股息率: {result['annual_static_yield']:.2f}%")
        print(f"  - 分红明细:")
        
        for div in result['dividends']:
            print(f"    除权除息日: {div['ex_dividend_date'].strftime('%Y-%m-%d')}")
            print(f"      - 每股分红: {div['dividend_amount']:.4f}元")
            print(f"      - 使用股价日期: {div['price_date'].strftime('%Y-%m-%d')}")
            print(f"      - 股价: {div['stock_price']:.2f}")
            print(f"      - 单次股息率: {div['static_yield']:.2f}%")



# 使用示例
if __name__ == "__main__":
    # 测试动态股息率（过去12个月）
    print("="*60)
    print("动态股息率测试（过去12个月）")
    print("="*60)

    test_cases = [
        ("sh.603866", "2024-07-01"),  
        # ("sh.603565", "2024-07-01"), 
    ]

    for code, date in test_cases:
        test_dividend_yield_calculation(code, date)

    # 测试静态股息率（指定年份）
    # print("\n" + "="*60)
    # print("静态股息率测试（指定年份）")
    # print("="*60)

    # static_test_cases = [
    #     ("sh.603866", 2024),
    #     ("sh.603565", 2024),
    # ]

    # for code, year in static_test_cases:
    #     test_static_dividend_yield(code, year)

    # # 测试综合股息率计算
    # print("\n" + "="*60)
    # print("综合股息率测试（动态+静态）")
    # print("="*60)

    # comprehensive_test_cases = [
    #     ("sh.603565", "2024-07-01"),
    #     ("sh.600519", "2023-07-01"),
    # ]

    # for code, date in comprehensive_test_cases:
    #     print(f"\n{code} 在 {date} 的综合股息率分析：")
    #     result = calculate_comprehensive_dividend_yield(code, date)
        
    #     print(f"  动态股息率（过去12个月）:")
    #     if result['dynamic_yield']:
    #         print(f"    - 股息率: {result['dynamic_yield']['yield_percentage']:.2f}%")
    #         print(f"    - 12个月分红总额: {result['dynamic_yield']['total_dividend_12m']:.4f}")
    #         print(f"    - 当前股价: {result['dynamic_yield']['stock_price']:.2f}")
    #     else:
    #         print("    - 无数据")
        
    #     print(f"  静态股息率（{pd.to_datetime(date).year}年）:")
    #     if result['static_yield']:
    #         print(f"    - 股息率: {result['static_yield']['yield_percentage']:.2f}%")
    #         print(f"    - 年度分红总额: {result['static_yield']['total_dividend']:.4f}")
    #         print(f"    - 基准股价: {result['static_yield']['base_price']:.2f}")