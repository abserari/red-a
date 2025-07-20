#!/usr/bin/env python3
"""
快速获取A股数据的脚本
"""

from datetime import datetime, timedelta
from data_acquisition import DataAcquisition

def main():
    # 初始化
    print("连接到 MongoDB...")
    da = DataAcquisition()
    
    # 设置时间范围（8年历史数据）
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=365*8)).strftime('%Y%m%d')
    
    # 1. 获取股票列表
    print("\n1. 获取股票列表...")
    stock_list = da.get_all_stock_list()
    print(f"   找到 {len(stock_list)} 只股票")
    
    # 2. 先获取一些示例股票的数据
    print("\n2. 获取示例股票数据...")
    sample_stocks = ['000001', '000002', '600000', '600036', '000858']  # 示例股票
    
    # 获取历史价格（使用并发）
    print("   获取历史价格数据（并发）...")
    history_data = da.get_batch_stock_history_concurrent(
        stock_codes=sample_stocks,
        start_date=start_date,
        end_date=end_date,
        max_workers=5  # 示例股票较少，使用较小的并发数
    )
    
    # 获取分红数据（使用并发）
    print("   获取分红数据（并发）...")
    dividend_data = da.get_batch_dividend_history_concurrent(
        stock_codes=sample_stocks,
        max_workers=5  # 示例股票较少，使用较小的并发数
    )
    
    # 3. 查看数据统计
    print("\n3. 数据统计：")
    stats = da.get_data_statistics()
    print(f"   股票总数: {stats['stocks_count']}")
    print(f"   历史价格记录: {stats['daily_prices_count']}")
    print(f"   分红记录: {stats['dividends_count']}")
    print(f"   有价格数据的股票: {stats['stocks_with_prices']}")
    print(f"   有分红数据的股票: {stats['stocks_with_dividends']}")
    
    # 4. 检查数据完整性
    print("\n4. 检查数据完整性...")
    completeness = da.check_data_completeness(sample_stocks, start_date, end_date)
    print(f"   历史数据完整: {completeness['history_complete']}/{len(sample_stocks)}")
    print(f"   分红数据新鲜: {completeness['dividend_fresh']}/{len(sample_stocks)}")
    
    print("\n✅ 数据获取完成！")
    print(f"\n提示：")
    print(f"- MongoDB Web界面: http://localhost:8081")
    print(f"- 要获取所有股票数据，请运行: python get_all_data.py")

if __name__ == "__main__":
    main()