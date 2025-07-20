import baostock as bs
import pandas as pd
from datetime import datetime, timedelta

# 设置pandas显示选项
pd.set_option('display.max_columns', None)
pd.set_option('display.max_rows', 20)
pd.set_option('display.width', None)

# 登录系统
result = bs.login()
print('login respond error_code:' + result.error_code)
print('login respond error_msg:' + result.error_msg)

def fetch_dividend_data(code, years):
    """
    获取指定年份的分红数据
    
    Args:
        code: 股票代码
        years: 年份列表
    
    Returns:
        DataFrame: 分红数据，如果无数据返回None
    """
    all_dividends = []
    fields = None
    
    for year in years:
        rs_dividend = bs.query_dividend_data(code=code, year=str(year))
        
        if rs_dividend.error_code == '0':
            fields = rs_dividend.fields
            
        dividend_list = []
        while (rs_dividend.error_code == '0') & rs_dividend.next():
            dividend_list.append(rs_dividend.get_row_data())
        
        if dividend_list:
            all_dividends.extend(dividend_list)
    
    if not all_dividends:
        return None
    
    return pd.DataFrame(all_dividends, columns=fields)


def identify_dividend_fields(dividend_df):
    """
    识别分红数据中的日期字段和现金分红字段
    
    Args:
        dividend_df: 分红数据DataFrame
    
    Returns:
        tuple: (date_field, cash_field) 如果找不到返回 (None, None)
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
        dividend_df: 分红数据DataFrame
        date_field: 日期字段名
        cash_field: 现金分红字段名
        check_date: 检查日期
    
    Returns:
        tuple: (filtered_df, total_cash_12m)
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
        code: 股票代码
        check_date: 检查日期
    
    Returns:
        dict: 包含日期和收盘价的字典，如果无数据返回None
    """
    start_date = (pd.to_datetime(check_date) - timedelta(days=7)).strftime('%Y-%m-%d')
    end_date = (pd.to_datetime(check_date) + timedelta(days=7)).strftime('%Y-%m-%d')
    
    rs_price = bs.query_history_k_data_plus(
        code, "date,close",
        start_date=start_date,
        end_date=end_date,
        frequency="d", adjustflag="2"
    )
    
    price_list = []
    while (rs_price.error_code == '0') & rs_price.next():
        price_list.append(rs_price.get_row_data())
    
    if not price_list:
        return None
    
    price_df = pd.DataFrame(price_list, columns=rs_price.fields)
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


def calculate_dividend_yield(total_cash_12m, stock_price):
    """
    计算股息率
    
    Args:
        total_cash_12m: 过去12个月每股现金分红总额
        stock_price: 股价
    
    Returns:
        float: 股息率（百分比），如果无法计算返回None
    """
    if stock_price > 0 and total_cash_12m > 0:
        return (total_cash_12m / stock_price) * 100
    return None


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

# 测试几个案例
test_cases = [
    ("sh.603866", "2024-07-01"),  
    ("sh.603565", "2024-07-01"), 
]

for code, date in test_cases:
    test_dividend_yield_calculation(code, date)