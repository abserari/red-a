#!/usr/bin/env python3
"""
测试数据获取优化效果
"""

from datetime import datetime, timedelta
from data_acquisition import DataAcquisition
import time

def test_data_optimization():
    print("=== 测试数据获取优化 ===\n")
    
    # 初始化
    da = DataAcquisition()
    
    # 测试股票
    test_stocks = ['000001', '000002', '600000']
    
    # 时间范围
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y%m%d')  # 只测试30天数据
    
    print(f"测试股票: {test_stocks}")
    print(f"时间范围: {start_date} - {end_date}\n")
    
    # 第一次获取（应该从API获取）
    print("=== 第一次获取（预期：从API获取） ===")
    for code in test_stocks:
        print(f"\n处理 {code}:")
        start_time = time.time()
        
        # 检查缺失数据
        missing = da.get_missing_date_ranges(code, start_date, end_date)
        print(f"  缺失数据段: {len(missing)} 段")
        
        # 获取数据
        df = da.get_stock_history_smart(code, start_date, end_date)
        
        elapsed = time.time() - start_time
        print(f"  耗时: {elapsed:.2f} 秒")
        print(f"  返回数据: {len(df)} 条")
    
    # 第二次获取（应该从数据库返回）
    print("\n\n=== 第二次获取（预期：从数据库返回） ===")
    for code in test_stocks:
        print(f"\n处理 {code}:")
        start_time = time.time()
        
        # 检查缺失数据
        missing = da.get_missing_date_ranges(code, start_date, end_date)
        print(f"  缺失数据段: {len(missing)} 段")
        
        # 获取数据
        df = da.get_stock_history_smart(code, start_date, end_date)
        
        elapsed = time.time() - start_time
        print(f"  耗时: {elapsed:.2f} 秒")
        print(f"  返回数据: {len(df)} 条")
    
    # 测试部分缺失（模拟新增几天数据的情况）
    print("\n\n=== 测试部分缺失（扩展日期范围） ===")
    extended_start = (datetime.now() - timedelta(days=40)).strftime('%Y%m%d')
    print(f"新时间范围: {extended_start} - {end_date}\n")
    
    for code in test_stocks[:1]:  # 只测试第一个
        print(f"\n处理 {code}:")
        start_time = time.time()
        
        # 检查缺失数据
        missing = da.get_missing_date_ranges(code, extended_start, end_date)
        print(f"  缺失数据段: {len(missing)} 段")
        if missing:
            for i, (s, e) in enumerate(missing):
                print(f"    段{i+1}: {s} - {e}")
        
        # 获取数据
        df = da.get_stock_history_smart(code, extended_start, end_date)
        
        elapsed = time.time() - start_time
        print(f"  耗时: {elapsed:.2f} 秒")
        print(f"  返回数据: {len(df)} 条")

if __name__ == "__main__":
    test_data_optimization()