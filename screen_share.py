from dividend import calculate_dynamic_dividend_yield, calculate_static_dividend_yield
from share_pool import share_pool
from stock_screener import screen_single_stock, calculate_four_year_dividend_rate
from safe_file_writer import SafeFileWriter
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pymongo import MongoClient
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
import multiprocessing as mp
import time
from tqdm import tqdm
import logging
import baostock as bs
import os
import signal

# 配置日志
logging.basicConfig(
    level=logging.WARNING,  # 只显示警告和错误，减少输出
    format='%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s'
)
logger = logging.getLogger(__name__)

# 设置 dividend 模块的日志级别
logging.getLogger('dividend').setLevel(logging.WARNING)

# MongoDB连接
client = MongoClient("mongodb://localhost:27017/")
db = client["red_a"]

# 多进程相关配置
shutdown_event = mp.Event()

def init_worker():
    """
    Worker进程初始化函数
    每个进程独立登录 BaoStock
    """
    # 忽略中断信号
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    
    # 设置环境变量，禁止dividend模块自动登录
    os.environ['BAOSTOCK_AUTO_LOGIN'] = '0'
    
    # 重置dividend模块的登录状态
    import dividend
    dividend._baostock_logged_in = False
    
    # 每个进程独立登录
    result = bs.login()
    if result.error_code == '0':
        dividend._baostock_logged_in = True
        logger.debug(f"Process {os.getpid()} - BaoStock login success")

def process_single_stock_mp(args):
    """
    处理单只股票（multiprocessing版本）
    参数通过元组传递: (code, name, date)
    """
    code, name, date = args
    result = screen_single_stock(code, date, name)
    return result

def convert_stock_code(code):
    """转换股票代码格式：从 603866.SH 到 sh.603866"""
    parts = code.split('.')
    if len(parts) == 2:
        number, market = parts
        if market == 'SH':
            return f'sh.{number}'
        elif market == 'SZ':
            return f'sz.{number}'
        elif market == 'BJ':
            return f'bj.{number}'
    return code

def process_single_stock(code, date, retry_count=3):
    """处理单只股票，带重试机制"""
    name = share_pool.get(code, '')
    
    for attempt in range(retry_count):
        try:
            # 添加延迟避免API过载，重试时延迟更长
            time.sleep(0.2 * (attempt + 1))
            
            # 使用 stock_screener 模块的函数
            result = screen_single_stock(code, date, name)
            
            if result:
                # 添加兼容性字段
                result['price'] = result.get('stock_price', 0)
                result['price_date'] = date
                result['screen_date'] = result.get('screening_date', date)
                result['four_year_avg'] = result.get('four_year_rate', 0)
                
            return result
            
        except UnicodeDecodeError as e:
            if attempt < retry_count - 1:
                logger.warning(f"Unicode error for {code}, retrying... (attempt {attempt+1}/{retry_count})")
                time.sleep(2)
                continue
            else:
                logger.error(f"Unicode error for {code} after {retry_count} attempts", exc_info=True)
                return None
        except Exception as e:
            if attempt < retry_count - 1:
                if 'list index' not in str(e).lower():
                    logger.warning(f"Error processing {code}, retrying... (attempt {attempt+1}/{retry_count})", exc_info=True)
                time.sleep(1)
                continue
            else:
                if 'list index' not in str(e).lower():
                    logger.error(f"Error processing {code} after {retry_count} attempts", exc_info=True)
                return None

def process_batch(batch_stocks, date, batch_id):
    """处理一批股票"""
    batch_results = []
    for code in batch_stocks:
        try:
            result = process_single_stock(code, date)
            if result:
                batch_results.append(result)
        except Exception as e:
            logger.error(f"批次 {batch_id} 处理股票 {code} 失败", exc_info=True)
            continue
    return batch_results

def screen_stocks_single_thread(date):
    """单线程筛选符合条件的股票（用于调试）"""
    print(f"\n筛选日期: {date}")
    print("=" * 80)
    
    stock_list = list(share_pool.items())
    qualified_stocks = []
    
    # 使用进度条显示处理进度
    with tqdm(total=len(stock_list), desc=f"处理 {date}") as pbar:
        for i, (pool_code, name) in enumerate(stock_list):
            result = process_single_stock(pool_code, date)
            if result:
                result['name'] = name  # 添加股票名称
                qualified_stocks.append(result)
            pbar.update(1)
    
    return qualified_stocks

def screen_stocks_parallel(date, batch_size=5, max_workers=3):
    """并行筛选符合条件的股票"""
    print(f"\n筛选日期: {date}")
    print("=" * 80)
    
    # 将股票列表分批
    stock_list = list(share_pool.keys())
    batches = [stock_list[i:i + batch_size] for i in range(0, len(stock_list), batch_size)]
    
    qualified_stocks = []
    
    # 使用线程池处理批次
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        # 提交所有批次任务
        future_to_batch = {executor.submit(process_batch, batch, date, i): i 
                          for i, batch in enumerate(batches)}
        
        # 使用进度条显示处理进度
        with tqdm(total=len(batches), desc=f"处理 {date}") as pbar:
            for future in as_completed(future_to_batch):
                batch_id = future_to_batch[future]
                try:
                    batch_results = future.result()
                    qualified_stocks.extend(batch_results)
                except Exception as e:
                    logger.error(f"批次 {batch_id} 处理失败", exc_info=True)
                pbar.update(1)
    
    return qualified_stocks

def screen_multiple_dates_single_thread(year):
    """在指定年份的多个日期进行单线程筛选"""
    # 筛选日期列表
    screen_dates = [
        f"{year}-01-01",
        f"{year}-04-01",
        f"{year}-05-01",
        f"{year}-07-01",
        f"{year}-10-01"
    ]
    
    all_results = []
    
    for date in screen_dates:
        print(f"\n开始处理日期: {date}")
        date_results = screen_stocks_single_thread(date)
        
        # 将日期添加到每个结果中
        for result in date_results:
            result['screening_date'] = date
            all_results.append(result)
    
    return all_results

def screen_stocks_multiprocess(date, num_processes=None, file_writer=None):
    """
    使用多进程筛选符合条件的股票
    
    Args:
        date: 筛选日期
        num_processes: 进程数，默认为CPU核心数-1
        file_writer: 文件写入器实例（可选）
    """
    print(f"\n筛选日期: {date}")
    print("=" * 80)
    
    if num_processes is None:
        num_processes = max(4, mp.cpu_count() - 1)
    
    print(f"使用 {num_processes} 个进程处理...")
    
    # 准备任务列表
    tasks = [(code, name, date) for code, name in share_pool.items()]
    
    qualified_stocks = []
    
    # 创建进程池
    with mp.Pool(processes=num_processes, initializer=init_worker) as pool:
        # 使用 imap_unordered 提高性能
        with tqdm(total=len(tasks), desc=f"处理 {date}") as pbar:
            for result in pool.imap_unordered(process_single_stock_mp, tasks, chunksize=2):
                if result:
                    qualified_stocks.append(result)
                    # 如果有文件写入器，实时写入
                    if file_writer:
                        file_writer.put(result)
                pbar.update(1)
                
                # 不在这里检查shutdown_event，让进程自然完成
    
    return qualified_stocks

def screen_multiple_dates_parallel(year, batch_size=50, max_workers=10):
    """在指定年份的多个日期进行并行筛选"""
    # 筛选日期列表
    screen_dates = [
        f"{year}-01-01",
        f"{year}-04-01",
        f"{year}-05-01",
        f"{year}-07-01",
        f"{year}-10-01"
    ]
    
    all_results = []
    
    for date in screen_dates:
        print(f"\n开始处理日期: {date}")
        start_time = time.time()
        
        results = screen_stocks_parallel(date, batch_size, max_workers)
        all_results.extend(results)
        
        elapsed_time = time.time() - start_time
        print(f"{date} 处理完成，耗时: {elapsed_time:.2f}秒")
        print(f"符合条件的股票数量: {len(results)}")
    
    return all_results

def save_results_to_csv(results, filename):
    """将结果保存到CSV文件"""
    if not results:
        print("没有符合条件的股票，不生成CSV文件")
        return
    
    # 转换为DataFrame
    df = pd.DataFrame(results)
    
    # 重新排列列的顺序
    columns_order = ['screen_date', 'code', 'dynamic_yield', 'four_year_rate', 
                    'dividend_std', 'stock_price', 'total_dividend_12m']
    df = df[columns_order]
    
    # 按日期和动态股息率排序
    df = df.sort_values(['screen_date', 'dynamic_yield'], ascending=[True, False])
    
    # 保存到CSV
    df.to_csv(filename, index=False, encoding='utf-8-sig')
    print(f"\n结果已保存到: {filename}")
    
    # 显示统计信息
    print("\n筛选结果统计:")
    print("-" * 50)
    date_stats = df.groupby('screen_date').size()
    for date, count in date_stats.items():
        print(f"{date}: {count} 只股票")
    print(f"总计: {len(df)} 条记录")
    
    # 找出在所有日期都符合条件的股票
    stock_counts = df.groupby('code').size()
    all_dates_stocks = stock_counts[stock_counts == len(screen_dates)]
    if not all_dates_stocks.empty:
        print(f"\n在所有 {len(screen_dates)} 个日期都符合条件的股票 ({len(all_dates_stocks)} 只):")
        for code in sorted(all_dates_stocks.index):
            avg_yield = df[df['code'] == code]['dynamic_yield'].mean()
            print(f"  - {code} (平均动态股息率: {avg_yield:.2f}%)")

# 主程序
if __name__ == "__main__":
    # 设置信号处理器（只在主程序中）
    def signal_handler(signum, frame):
        """处理中断信号"""
        print("\n收到中断信号，正在优雅关闭...")
        shutdown_event.set()
        import sys
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    # 配置参数
    year = 2024
    batch_size = 5  # 减小批次大小避免API过载
    max_workers = 3  # 减少并发线程数
    use_single_thread = False  # 是否使用单线程模式
    use_multiprocess = True  # 是否使用多进程（推荐）
    use_safe_writer = True  # 是否使用进程安全的文件写入
    
    print(f"开始筛选 {year} 年的高股息股票")
    print(f"筛选条件:")
    print(f"1. 动态股息率 > 6%")
    print(f"2. 四年平均分红率 > 6%")
    print(f"3. 分红标准差 < 30")
    print(f"筛选日期: 1月1日, 4月1日, 5月1日, 7月1日, 10月1日")
    print(f"\n处理参数:")
    print(f"- 批次大小: {batch_size} 只股票/批")
    print(f"- 最大线程数: {max_workers}")
    print(f"- 股票池总数: {len(share_pool)} 只")
    
    # 筛选日期列表
    screen_dates = [
        f"{year}-01-01",
        f"{year}-04-01",
        f"{year}-05-01",
        f"{year}-07-01",
        f"{year}-10-01"
    ]
    
    # 开始处理
    total_start_time = time.time()
    
    try:
        if use_multiprocess and use_safe_writer:
            # 使用多进程 + 进程安全文件写入
            print(f"\n使用多进程模式 + 进程安全文件写入...")
            
            # 生成输出文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            csv_filename = f"dividend_screening_results_{year}_{timestamp}.csv"
            
            # 创建文件写入器
            file_writer = SafeFileWriter(csv_filename)
            file_writer.start()
            
            try:
                all_results = []
                for i, date in enumerate(screen_dates):
                    try:
                        print(f"\n处理第 {i+1}/{len(screen_dates)} 个日期: {date}")
                        date_results = screen_stocks_multiprocess(date, file_writer=file_writer)
                        all_results.extend(date_results)
                        print(f"日期 {date} 找到 {len(date_results)} 只符合条件的股票")
                        print(f"累计找到 {len(all_results)} 只股票")
                    except KeyboardInterrupt:
                        print(f"\n用户中断，停止处理剩余日期")
                        break
                    except Exception as e:
                        print(f"\n处理日期 {date} 时出错: {type(e).__name__}: {e}")
                        logger.error(f"处理日期 {date} 时出错", exc_info=True)
                        # 继续处理下一个日期，而不是break
                        continue
                
                print(f"\n完成所有 {len(screen_dates)} 个日期的处理")
            finally:
                print("\n停止文件写入器...")
                file_writer.stop()
                
            results = all_results
            
        elif use_multiprocess:
            # 使用多进程，但不使用进程安全文件写入
            print(f"\n使用多进程模式...")
            results = []
            for date in screen_dates:
                date_results = screen_stocks_multiprocess(date)
                results.extend(date_results)
                
        elif use_single_thread:
            print(f"\n使用单线程模式...")
            results = screen_multiple_dates_single_thread(year)
        else:
            print(f"\n使用线程池并行模式...")
            results = screen_multiple_dates_parallel(year, batch_size, max_workers)
            
    except KeyboardInterrupt:
        print("\n\n程序被用户中断")
        results = []
    except Exception as e:
        logger.error(f"程序错误: {e}", exc_info=True)
        results = []
        
    total_elapsed_time = time.time() - total_start_time
    
    print(f"\n总处理时间: {total_elapsed_time:.2f}秒")
    
    # 如果没有使用进程安全文件写入器，则手动保存结果
    if not (use_multiprocess and use_safe_writer) and results:
        # 生成输出文件名（包含时间戳）
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_filename = f"dividend_screening_results_{year}_{timestamp}.csv"
        
        # 保存结果到CSV
        save_results_to_csv(results, csv_filename)