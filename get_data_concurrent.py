#!/usr/bin/env python3
"""
高并发获取A股数据（6000并发）
"""

from datetime import datetime, timedelta
from data_acquisition import DataAcquisition
import sys
import time
import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
import os

# 全局锁用于线程安全的计数器更新
counter_lock = Lock()
success_count = 0
fail_count = 0
skip_count = 0

def process_stock(da, code, start_date, end_date, args):
    """处理单个股票的数据获取"""
    global success_count, fail_count, skip_count
    
    try:
        # 如果不是强制更新，检查是否需要更新
        if not args.force:
            # 检查历史数据完整性
            missing_ranges = da.get_missing_date_ranges(code, start_date, end_date)
            if not missing_ranges:
                # 检查分红数据是否需要更新
                dividend_check = da.dividends.find_one({"stock_code": code}, sort=[("update_time", -1)])
                if dividend_check and (datetime.now() - dividend_check.get('update_time', datetime.min)).days < args.dividend_days:
                    with counter_lock:
                        skip_count += 1
                    return (code, 'skip', '数据完整且最新')
        
        # 获取历史数据
        history_msg = ""
        if args.force or missing_ranges:
            history_df = da.get_stock_history_smart(code, start_date, end_date)
            if not history_df.empty:
                history_msg = f"历史数据: {len(history_df)}条"
            else:
                history_msg = "历史数据: 无"
        
        # 获取分红数据
        dividend_msg = ""
        dividend_check = da.dividends.find_one({"stock_code": code}, sort=[("update_time", -1)])
        if args.force or not dividend_check or (datetime.now() - dividend_check.get('update_time', datetime.min)).days >= args.dividend_days:
            dividend_df = da.get_dividend_history(code)
            if not dividend_df.empty:
                dividend_msg = f"分红: {len(dividend_df)}条"
            else:
                dividend_msg = "分红: 无"
        
        with counter_lock:
            success_count += 1
        
        return (code, 'success', f"{history_msg} {dividend_msg}")
        
    except Exception as e:
        with counter_lock:
            fail_count += 1
        return (code, 'fail', str(e)[:50])

def main():
    parser = argparse.ArgumentParser(description='高并发获取A股数据')
    parser.add_argument('--years', type=int, default=8, help='历史数据年数（默认8年）')
    parser.add_argument('--workers', type=int, default=6000, help='并发数（默认6000）')
    parser.add_argument('--test', action='store_true', help='测试模式，只处理前100只股票')
    parser.add_argument('--force', action='store_true', help='强制更新所有数据（忽略缓存）')
    parser.add_argument('--dividend-days', type=int, default=30, help='分红数据更新周期（默认30天）')
    args = parser.parse_args()
    
    # 初始化
    print("=" * 60)
    print("A股数据获取系统（高并发版）")
    print("=" * 60)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"配置：并发数={args.workers}")
    print("-" * 60)
    
    print("\n连接到 MongoDB...")
    da = DataAcquisition()
    
    # 设置时间范围
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=365*args.years)).strftime('%Y%m%d')
    print(f"数据时间范围: {start_date} - {end_date} ({args.years}年)")
    
    # 1. 获取股票列表
    print("\n1. 获取股票列表...")
    stock_list = da.get_all_stock_list()
    all_codes = stock_list['stock_code'].tolist()
    
    # 测试模式
    if args.test:
        all_codes = all_codes[:100]
        print(f"   测试模式：只处理前 {len(all_codes)} 只股票")
    else:
        print(f"   找到 {len(all_codes)} 只股票")
    
    # 2. 并发获取数据
    total = len(all_codes)
    print(f"\n2. 开始并发获取数据（{args.workers} 并发）...")
    print("   注意：高并发可能导致API限流或系统资源耗尽")
    
    start_time = time.time()
    completed = 0
    
    # 使用线程池并发处理
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        # 提交所有任务
        futures = {
            executor.submit(process_stock, da, code, start_date, end_date, args): code 
            for code in all_codes
        }
        
        # 处理完成的任务
        for future in as_completed(futures):
            code = futures[future]
            completed += 1
            
            try:
                code, status, message = future.result(timeout=30)
                
                # 每100个显示一次进度
                if completed % 100 == 0 or completed == total:
                    elapsed = time.time() - start_time
                    rate = completed / elapsed if elapsed > 0 else 0
                    eta = (total - completed) / rate if rate > 0 else 0
                    
                    print(f"\n进度: {completed}/{total} ({completed/total*100:.1f}%)")
                    print(f"成功: {success_count}, 失败: {fail_count}, 跳过: {skip_count}")
                    print(f"速度: {rate:.1f} 股/秒, 预计剩余: {eta:.1f} 秒")
                
                # 失败的显示详情
                if status == 'fail':
                    print(f"✗ {code}: {message}")
                    
            except Exception as e:
                print(f"✗ {code}: 处理异常 - {e}")
    
    # 3. 最终统计
    total_time = time.time() - start_time
    print("\n\n" + "=" * 60)
    print("✅ 数据获取完成！")
    print("=" * 60)
    
    final_stats = da.get_data_statistics()
    print(f"\n最终数据统计：")
    print(f"- 股票总数: {final_stats['stocks_count']}")
    print(f"- 历史价格记录: {final_stats['daily_prices_count']:,}")
    print(f"- 分红记录: {final_stats['dividends_count']:,}")
    print(f"- 有价格数据的股票: {final_stats['stocks_with_prices']}")
    print(f"- 有分红数据的股票: {final_stats['stocks_with_dividends']}")
    
    print(f"\n处理结果：")
    print(f"- 成功: {success_count}")
    print(f"- 失败: {fail_count}")
    print(f"- 跳过: {skip_count}")
    print(f"- 总耗时: {total_time:.1f} 秒 ({total_time/60:.1f} 分钟)")
    print(f"- 平均速度: {total/total_time:.1f} 股/秒")

if __name__ == "__main__":
    # 设置更高的文件描述符限制（Unix系统）
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_NOFILE, (10000, 10000))
    except:
        pass
    
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断，程序已停止")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ 程序错误: {e}")
        sys.exit(1)