#!/usr/bin/env python3
"""
获取所有A股数据（智能增量更新）
"""

from datetime import datetime, timedelta
from data_acquisition import DataAcquisition
import sys

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
    all_codes = stock_list['stock_code'].tolist()
    print(f"   找到 {len(all_codes)} 只股票")
    
    # 2. 检查整体数据完整性
    print("\n2. 检查数据完整性...")
    completeness = da.check_data_completeness(all_codes, start_date, end_date)
    
    print(f"\n数据概况：")
    print(f"- 历史数据完整: {completeness['history_complete']}/{len(all_codes)}")
    print(f"- 分红数据新鲜: {completeness['dividend_fresh']}/{len(all_codes)}")
    print(f"- 需要获取历史数据: {completeness['history_missing'] + completeness['history_partial']}")
    print(f"- 需要更新分红数据: {completeness['dividend_missing'] + completeness['dividend_stale']}")
    
    # 询问是否继续
    if completeness['history_missing'] + completeness['history_partial'] > 0:
        response = input(f"\n需要获取 {completeness['history_missing'] + completeness['history_partial']} 只股票的历史数据，是否继续？(y/n): ")
        if response.lower() != 'y':
            print("已取消")
            return
    
    # 3. 批量获取数据
    batch_size = 50
    total = len(all_codes)
    
    print(f"\n3. 开始获取数据（每批 {batch_size} 只）...")
    
    for i in range(0, total, batch_size):
        batch_codes = all_codes[i:i+batch_size]
        batch_num = i // batch_size + 1
        total_batches = (total + batch_size - 1) // batch_size
        
        print(f"\n=== 处理第 {batch_num}/{total_batches} 批 ===")
        
        # 获取历史数据（自动跳过已有的）
        print("获取历史价格数据...")
        da.get_batch_stock_history(
            stock_codes=batch_codes,
            start_date=start_date,
            end_date=end_date,
            check_existing=True
        )
        
        # 获取分红数据（自动跳过新鲜的）
        print("获取分红数据...")
        da.get_batch_dividend_history(
            stock_codes=batch_codes,
            check_existing=True
        )
        
        # 显示进度
        completed = min(i + batch_size, total)
        print(f"\n总进度: {completed}/{total} ({completed/total*100:.1f}%)")
        
        # 每10批显示一次统计
        if batch_num % 10 == 0:
            stats = da.get_data_statistics()
            print(f"\n当前数据统计：")
            print(f"- 历史价格记录: {stats['daily_prices_count']:,}")
            print(f"- 分红记录: {stats['dividends_count']:,}")
    
    # 4. 最终统计
    print("\n\n✅ 数据获取完成！")
    final_stats = da.get_data_statistics()
    print(f"\n最终数据统计：")
    print(f"- 股票总数: {final_stats['stocks_count']}")
    print(f"- 历史价格记录: {final_stats['daily_prices_count']:,}")
    print(f"- 分红记录: {final_stats['dividends_count']:,}")
    print(f"- 有价格数据的股票: {final_stats['stocks_with_prices']}")
    print(f"- 有分红数据的股票: {final_stats['stocks_with_dividends']}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断，程序已停止")
        print("提示：下次运行会自动从中断的地方继续")
        sys.exit(0)