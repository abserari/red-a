#!/usr/bin/env python3
"""
分析MongoDB中缺失的股票数据
"""
import pandas as pd
from pymongo import MongoClient
from datetime import datetime, timedelta
from tabulate import tabulate
import pytz

# MongoDB连接
client = MongoClient('mongodb://admin:red-a-2025@localhost:27017/')
db = client.stock_data

# 设置中国时区
china_tz = pytz.timezone('Asia/Shanghai')

def get_all_stocks():
    """获取所有股票列表"""
    return list(db.stocks.find({}, {'_id': 0, 'code': 1, 'name': 1}))

def analyze_stock_data(stock_code, start_date, end_date):
    """分析单个股票的数据完整性"""
    # 获取该股票的所有数据
    data = list(db.daily_prices.find(
        {'code': stock_code, 'date': {'$gte': start_date, '$lte': end_date}},
        {'date': 1}
    ).sort('date', 1))
    
    if not data:
        return {
            'has_data': False,
            'first_date': None,
            'last_date': None,
            'total_days': 0,
            'missing_ranges': [(start_date, end_date)]
        }
    
    dates = [d['date'] for d in data]
    first_date = dates[0]
    last_date = dates[-1]
    
    # 找出缺失的日期范围
    missing_ranges = []
    
    # 检查开始日期前的缺失
    if first_date > start_date:
        missing_ranges.append((start_date, first_date - timedelta(days=1)))
    
    # 检查中间的缺失（超过10天的间隔认为是缺失）
    for i in range(1, len(dates)):
        gap = (dates[i] - dates[i-1]).days
        if gap > 10:  # 考虑节假日，超过10天认为有缺失
            missing_ranges.append((dates[i-1] + timedelta(days=1), dates[i] - timedelta(days=1)))
    
    # 检查结束日期后的缺失
    if last_date < end_date:
        missing_ranges.append((last_date + timedelta(days=1), end_date))
    
    return {
        'has_data': True,
        'first_date': first_date,
        'last_date': last_date,
        'total_days': len(dates),
        'missing_ranges': missing_ranges
    }

def main():
    # 设置分析的时间范围（默认8年）
    end_date = datetime.now(china_tz).replace(tzinfo=None)
    start_date = end_date - timedelta(days=8*365)
    
    print(f"分析时间范围: {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')}")
    print("正在分析数据...")
    
    # 获取所有股票
    all_stocks = get_all_stocks()
    print(f"总股票数: {len(all_stocks)}")
    
    # 分析每个股票
    results = []
    no_data_stocks = []
    incomplete_stocks = []
    
    for i, stock in enumerate(all_stocks):
        if i % 100 == 0:
            print(f"进度: {i}/{len(all_stocks)}")
        
        analysis = analyze_stock_data(stock['code'], start_date, end_date)
        
        if not analysis['has_data']:
            no_data_stocks.append({
                '股票代码': stock['code'],
                '股票名称': stock.get('name', 'N/A'),
                '缺失时段': f"{start_date.strftime('%Y-%m-%d')} ~ {end_date.strftime('%Y-%m-%d')}",
                '状态': '完全无数据'
            })
        elif analysis['missing_ranges']:
            for missing_range in analysis['missing_ranges']:
                incomplete_stocks.append({
                    '股票代码': stock['code'],
                    '股票名称': stock.get('name', 'N/A'),
                    '缺失时段': f"{missing_range[0].strftime('%Y-%m-%d')} ~ {missing_range[1].strftime('%Y-%m-%d')}",
                    '缺失天数': (missing_range[1] - missing_range[0]).days + 1
                })
    
    # 打印结果
    print("\n" + "="*80)
    print("数据分析结果")
    print("="*80)
    
    print(f"\n完全无数据的股票数: {len(no_data_stocks)}")
    if no_data_stocks:
        print("\n完全无数据的股票（前20个）:")
        df_no_data = pd.DataFrame(no_data_stocks[:20])
        print(tabulate(df_no_data, headers='keys', tablefmt='grid', showindex=False))
    
    print(f"\n数据不完整的股票数: {len(set(s['股票代码'] for s in incomplete_stocks))}")
    if incomplete_stocks:
        print("\n数据缺失情况（前30条）:")
        df_incomplete = pd.DataFrame(incomplete_stocks[:30])
        print(tabulate(df_incomplete, headers='keys', tablefmt='grid', showindex=False))
    
    # 统计信息
    print("\n" + "="*80)
    print("统计摘要")
    print("="*80)
    total_stocks = len(all_stocks)
    complete_stocks = total_stocks - len(no_data_stocks) - len(set(s['股票代码'] for s in incomplete_stocks))
    
    print(f"总股票数: {total_stocks}")
    print(f"数据完整的股票数: {complete_stocks} ({complete_stocks/total_stocks*100:.2f}%)")
    print(f"完全无数据的股票数: {len(no_data_stocks)} ({len(no_data_stocks)/total_stocks*100:.2f}%)")
    print(f"数据不完整的股票数: {len(set(s['股票代码'] for s in incomplete_stocks))} ({len(set(s['股票代码'] for s in incomplete_stocks))/total_stocks*100:.2f}%)")
    
    # 保存详细结果到CSV
    if no_data_stocks:
        pd.DataFrame(no_data_stocks).to_csv('missing_stocks_no_data.csv', index=False, encoding='utf-8-sig')
        print("\n完全无数据的股票已保存到: missing_stocks_no_data.csv")
    
    if incomplete_stocks:
        pd.DataFrame(incomplete_stocks).to_csv('missing_stocks_incomplete.csv', index=False, encoding='utf-8-sig')
        print("数据不完整的股票已保存到: missing_stocks_incomplete.csv")

if __name__ == "__main__":
    main()