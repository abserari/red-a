#!/usr/bin/env python3
"""
正确分析MongoDB中的数据状态（处理股票代码格式差异）
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

def main():
    """主分析函数"""
    # 设置分析的时间范围（默认8年）
    end_date = datetime.now(china_tz).replace(tzinfo=None)
    start_date = end_date - timedelta(days=8*365)
    
    print(f"分析时间范围: {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')}")
    print("="*80)
    
    # 1. 获取数据库基本信息
    print("\n1. 数据库概览:")
    print(f"   stocks集合文档数: {db.stocks.count_documents({})}")
    print(f"   daily_prices集合文档数: {db.daily_prices.count_documents({})}")
    print(f"   dividends集合文档数: {db.dividends.count_documents({})}")
    
    # 2. 获取所有数据中的唯一股票代码（处理格式差异）
    print("\n2. 股票代码统计:")
    
    # stocks集合中的股票代码（带前缀）
    stocks_codes_with_prefix = set()
    stocks_codes_clean = set()
    stock_info_map = {}
    
    for doc in db.stocks.find({}, {'code': 1, 'name': 1}):
        if 'code' in doc:
            code_with_prefix = doc['code']
            clean_code = code_with_prefix.replace('sh.', '').replace('sz.', '')
            stocks_codes_with_prefix.add(code_with_prefix)
            stocks_codes_clean.add(clean_code)
            stock_info_map[clean_code] = {
                'code_with_prefix': code_with_prefix,
                'name': doc.get('name', 'N/A')
            }
    
    # daily_prices中的股票代码（无前缀）
    prices_codes = set(db.daily_prices.distinct('stock_code'))
    
    # dividends中的股票代码（无前缀）
    dividends_codes = set(db.dividends.distinct('stock_code'))
    
    print(f"   stocks集合中的唯一股票代码数: {len(stocks_codes_clean)}")
    print(f"   daily_prices中的唯一股票代码数: {len(prices_codes)}")
    print(f"   dividends中的唯一股票代码数: {len(dividends_codes)}")
    
    # 3. 分析数据覆盖情况（使用清理后的代码比较）
    print("\n3. 数据覆盖分析:")
    
    # 在stocks中但无日线数据的股票
    no_price_stocks = stocks_codes_clean - prices_codes
    print(f"   在stocks中但无日线数据的股票数: {len(no_price_stocks)}")
    
    # 在stocks中但无分红数据的股票
    no_dividend_stocks = stocks_codes_clean - dividends_codes
    print(f"   在stocks中但无分红数据的股票数: {len(no_dividend_stocks)}")
    
    # 既无日线也无分红数据的股票
    no_data_stocks = no_price_stocks & no_dividend_stocks
    print(f"   既无日线也无分红数据的股票数: {len(no_data_stocks)}")
    
    # 有日线但不在stocks中的股票（异常情况）
    orphan_price_stocks = prices_codes - stocks_codes_clean
    print(f"   有日线但不在stocks中的股票数: {len(orphan_price_stocks)}")
    
    # 4. 统计已成功获取数据的股票
    success_stocks = stocks_codes_clean & prices_codes
    print(f"\n4. 数据获取进度:")
    print(f"   已成功获取数据的股票数: {len(success_stocks)} / {len(stocks_codes_clean)} ({len(success_stocks)/len(stocks_codes_clean)*100:.2f}%)")
    
    # 5. 生成缺失数据报表
    if no_data_stocks:
        print("\n5. 缺失数据详情（前50条）:")
        missing_records = []
        
        for clean_code in sorted(list(no_data_stocks)[:50]):
            info = stock_info_map.get(clean_code, {})
            missing_records.append({
                '股票代码': info.get('code_with_prefix', clean_code),
                '股票名称': info.get('name', 'N/A'),
                '缺失类型': '无任何数据',
                '日线数据': '无',
                '分红数据': '无'
            })
        
        df = pd.DataFrame(missing_records)
        print(tabulate(df, headers='keys', tablefmt='grid', showindex=False))
        
        # 保存剩余缺失的股票列表
        all_missing = []
        for clean_code in sorted(no_data_stocks):
            info = stock_info_map.get(clean_code, {})
            all_missing.append({
                '股票代码': info.get('code_with_prefix', clean_code),
                '股票名称': info.get('name', 'N/A'),
                '缺失类型': '无任何数据'
            })
        
        if all_missing:
            pd.DataFrame(all_missing).to_csv('remaining_missing_stocks.csv', index=False, encoding='utf-8-sig')
            print(f"\n剩余缺失数据列表已保存到: remaining_missing_stocks.csv")
    
    # 6. 检查数据质量（抽样分析）
    print("\n6. 最近获取的数据质量检查:")
    # 获取最近更新的股票
    recent_stocks = list(db.daily_prices.aggregate([
        {"$group": {"_id": "$stock_code", "latest_update": {"$max": "$update_time"}}},
        {"$sort": {"latest_update": -1}},
        {"$limit": 5}
    ]))
    
    for stock in recent_stocks:
        code = stock['_id']
        info = stock_info_map.get(code, {})
        
        pipeline = [
            {"$match": {"stock_code": code}},
            {"$group": {
                "_id": None,
                "count": {"$sum": 1},
                "min_date": {"$min": "$date"},
                "max_date": {"$max": "$date"}
            }}
        ]
        result = list(db.daily_prices.aggregate(pipeline))
        
        if result:
            stats = result[0]
            print(f"\n   {info.get('code_with_prefix', code)} ({info.get('name', 'N/A')}):")
            print(f"     数据条数: {stats['count']}")
            print(f"     时间范围: {stats['min_date'].strftime('%Y-%m-%d')} ~ {stats['max_date'].strftime('%Y-%m-%d')}")
            print(f"     最后更新: {stock['latest_update'].strftime('%Y-%m-%d %H:%M:%S')}")
    
    # 7. 建议
    print("\n" + "="*80)
    print("建议操作:")
    
    if len(no_data_stocks) > 0:
        print(f"\n1. 还有 {len(no_data_stocks)} 只股票需要获取数据")
        print("   继续运行: uv run python fetch_missing_stocks.py --csv remaining_missing_stocks.csv")
        print("   或使用更小的批次: uv run python fetch_missing_stocks.py --csv remaining_missing_stocks.csv --batch-size 20")
    
    print(f"\n2. 已成功获取 {len(success_stocks)} 只股票的数据")
    print("   可以开始运行分红策略分析: jupyter lab")

if __name__ == "__main__":
    main()