#!/usr/bin/env python3
"""
使用 BaoStock 并发获取缺失股票的数据
"""
import pandas as pd
import time
from datetime import datetime, timedelta
import pytz
from concurrent.futures import ProcessPoolExecutor, as_completed
import multiprocessing
import argparse
import sys
import os
from typing import List, Tuple, Dict

def init_worker():
    """
    初始化工作进程
    每个进程需要自己的 BaoStock 连接
    """
    import baostock as bs
    global bs_login_result
    bs_login_result = bs.login()
    if bs_login_result.error_code != '0':
        raise ConnectionError(f"BaoStock 登录失败: {bs_login_result.error_msg}")

def cleanup_worker():
    """清理工作进程"""
    import baostock as bs
    bs.logout()

def process_stock_batch(batch_info: Tuple[int, List[str], datetime, datetime, int]) -> Dict:
    """
    处理一批股票
    
    Parameters:
    -----------
    batch_info : tuple
        (batch_id, stock_list, start_date, end_date, worker_id)
    
    Returns:
    --------
    dict: 处理结果
    """
    batch_id, stock_list, start_date, end_date, worker_id = batch_info
    
    # 每个进程创建自己的 BaoStock 实例
    from baostock_data_acquisition import BaoStockDataAcquisition
    
    try:
        bs_da = BaoStockDataAcquisition()
    except Exception as e:
        return {
            'batch_id': batch_id,
            'worker_id': worker_id,
            'success': 0,
            'failed': len(stock_list),
            'errors': [f"初始化失败: {str(e)}"] * len(stock_list)
        }
    
    results = {
        'batch_id': batch_id,
        'worker_id': worker_id,
        'success': 0,
        'failed': 0,
        'errors': []
    }
    
    for stock_code in stock_list:
        try:
            # 移除前缀以适配 BaoStock
            clean_code = stock_code.replace('sh.', '').replace('sz.', '').replace('bj.', '')
            
            # 获取日线数据
            price_data = bs_da.get_daily_data(
                stock_code=clean_code,
                start_date=start_date.strftime('%Y%m%d'),
                end_date=end_date.strftime('%Y%m%d'),
                frequency='d',
                adjustflag='2'  # 后复权
            )
            
            if price_data is not None and not price_data.empty:
                # 数据已经在 get_daily_data 中保存
                results['success'] += 1
            else:
                results['failed'] += 1
                results['errors'].append(f"{stock_code}: 无数据")
                
        except Exception as e:
            results['failed'] += 1
            results['errors'].append(f"{stock_code}: {str(e)}")
    
    return results

def fetch_missing_stocks_concurrent(csv_file='remaining_missing_stocks.csv', 
                                  workers=10, 
                                  batch_size=50, 
                                  years=8):
    """
    并发获取缺失股票的数据
    
    Parameters:
    -----------
    csv_file : str
        包含缺失股票列表的CSV文件
    workers : int
        并发工作进程数
    batch_size : int
        每批处理的股票数量
    years : int
        获取多少年的历史数据
    """
    # 读取缺失股票列表
    try:
        df = pd.read_csv(csv_file)
        missing_stocks = df['股票代码'].tolist()
        print(f"从 {csv_file} 读取到 {len(missing_stocks)} 只缺失数据的股票")
    except Exception as e:
        print(f"读取CSV文件失败: {e}")
        return
    
    # 设置时间范围
    china_tz = pytz.timezone('Asia/Shanghai')
    end_date = datetime.now(china_tz).replace(tzinfo=None)
    start_date = end_date - timedelta(days=years*365)
    
    print(f"数据获取时间范围: {start_date.strftime('%Y-%m-%d')} 到 {end_date.strftime('%Y-%m-%d')}")
    print(f"使用 {workers} 个工作进程")
    print(f"批次大小: {batch_size}\n")
    
    # 将股票列表分成批次
    batches = []
    for i in range(0, len(missing_stocks), batch_size):
        batch = missing_stocks[i:i+batch_size]
        batch_id = i // batch_size
        # 分配给不同的 worker
        worker_id = batch_id % workers
        batches.append((batch_id, batch, start_date, end_date, worker_id))
    
    print(f"总批次数: {len(batches)}")
    print("开始并发处理...\n")
    
    # 统计
    total_success = 0
    total_failed = 0
    all_errors = []
    start_time = time.time()
    
    # 使用进程池并发处理
    with ProcessPoolExecutor(max_workers=workers, initializer=init_worker) as executor:
        # 提交所有任务
        future_to_batch = {executor.submit(process_stock_batch, batch): batch for batch in batches}
        
        # 处理完成的任务
        completed = 0
        for future in as_completed(future_to_batch):
            batch_info = future_to_batch[future]
            batch_id = batch_info[0]
            
            try:
                result = future.result()
                total_success += result['success']
                total_failed += result['failed']
                all_errors.extend(result['errors'])
                
                completed += 1
                
                # 显示进度
                elapsed = time.time() - start_time
                rate = completed / elapsed if elapsed > 0 else 0
                eta = (len(batches) - completed) / rate if rate > 0 else 0
                
                print(f"\r进度: {completed}/{len(batches)} 批次 "
                      f"({completed/len(batches)*100:.1f}%) | "
                      f"成功: {total_success} | "
                      f"失败: {total_failed} | "
                      f"速度: {rate:.1f} 批次/秒 | "
                      f"预计剩余: {eta/60:.1f} 分钟", end='', flush=True)
                
            except Exception as e:
                print(f"\n批次 {batch_id} 处理异常: {str(e)}")
                total_failed += len(batch_info[1])
    
    # 清理 BaoStock
    cleanup_worker()
    
    # 输出最终统计
    print("\n\n" + "="*80)
    print("处理完成！")
    print(f"总用时: {(time.time() - start_time)/60:.1f} 分钟")
    print(f"成功: {total_success} 只股票")
    print(f"失败: {total_failed} 只股票")
    print(f"平均速度: {len(missing_stocks)/(time.time() - start_time):.1f} 只/秒")
    
    # 保存错误日志
    if all_errors:
        with open('concurrent_errors.log', 'w', encoding='utf-8') as f:
            for error in all_errors[:100]:  # 只保存前100个错误
                f.write(f"{error}\n")
        print(f"\n错误日志已保存到: concurrent_errors.log")
    
    print("\n建议后续操作:")
    print("1. 运行分析脚本查看最新的数据状态: uv run python analyze_data_correct.py")
    print("2. 如果还有失败的股票，可以降低并发数重试")

def main():
    parser = argparse.ArgumentParser(description='使用 BaoStock 并发获取缺失股票的数据')
    parser.add_argument('--csv', default='remaining_missing_stocks.csv', help='缺失股票列表CSV文件')
    parser.add_argument('--workers', type=int, default=10, help='并发工作进程数')
    parser.add_argument('--batch-size', type=int, default=50, help='每批处理的股票数量')
    parser.add_argument('--years', type=int, default=8, help='获取多少年的历史数据')
    parser.add_argument('--test', action='store_true', help='测试模式，只处理前100只股票')
    
    args = parser.parse_args()
    
    # 限制最大并发数
    if args.workers > multiprocessing.cpu_count():
        print(f"警告: 工作进程数 ({args.workers}) 超过 CPU 核心数 ({multiprocessing.cpu_count()})")
        print(f"建议使用不超过 {multiprocessing.cpu_count()} 个工作进程")
    
    # 如果是测试模式，限制处理数量
    if args.test:
        print("测试模式：只处理前100只股票")
        # 读取CSV并限制数量
        df = pd.read_csv(args.csv)
        df_test = df.head(100)
        df_test.to_csv('test_concurrent_stocks.csv', index=False, encoding='utf-8-sig')
        args.csv = 'test_concurrent_stocks.csv'
    
    fetch_missing_stocks_concurrent(
        csv_file=args.csv,
        workers=args.workers,
        batch_size=args.batch_size,
        years=args.years
    )

if __name__ == "__main__":
    # 设置多进程启动方式
    multiprocessing.set_start_method('spawn', force=True)
    main()