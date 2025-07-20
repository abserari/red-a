"""
进程安全的文件写入器
提供多进程环境下的安全文件写入功能
"""
import pandas as pd
import multiprocessing as mp
import logging
import time
import os
import queue
import signal

logger = logging.getLogger(__name__)

class SafeFileWriter:
    """进程安全的CSV文件写入器"""
    
    def __init__(self, filename, save_interval=30, batch_size=10):
        """
        初始化文件写入器
        
        Args:
            filename: 输出文件名
            save_interval: 自动保存间隔（秒）
            batch_size: 批量保存的记录数
        """
        self.filename = filename
        self.save_interval = save_interval
        self.batch_size = batch_size
        self.temp_filename = f"{filename}.tmp"
        
        # 创建进程间通信队列
        self.manager = mp.Manager()
        self.result_queue = self.manager.Queue()
        self.writer_process = None
        
        # 关闭事件
        self.shutdown_event = mp.Event()
        
    def start(self):
        """启动写入进程"""
        self.writer_process = mp.Process(
            target=self._writer_worker,
            args=(self.result_queue, self.filename, self.temp_filename, 
                  self.save_interval, self.batch_size, self.shutdown_event)
        )
        self.writer_process.start()
        logger.info(f"文件写入进程已启动，PID: {self.writer_process.pid}")
        
    def stop(self):
        """停止写入进程"""
        if self.writer_process and self.writer_process.is_alive():
            # 发送结束信号
            self.result_queue.put("DONE")
            
            # 等待进程结束
            self.writer_process.join(timeout=30)
            
            if self.writer_process.is_alive():
                logger.warning("写入进程未正常结束，强制终止")
                self.writer_process.terminate()
                self.writer_process.join()
                
    def put(self, result):
        """添加结果到队列"""
        if result is not None:
            self.result_queue.put(result)
            
    def shutdown(self):
        """设置关闭标志"""
        self.shutdown_event.set()
        
    @staticmethod
    def _writer_worker(result_queue, filename, temp_filename, save_interval, batch_size, shutdown_event):
        """
        写入进程的工作函数
        """
        # 忽略中断信号，让主进程处理
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        
        results = []
        processed_count = 0
        last_save_time = time.time()
        
        logger.info(f"文件写入进程启动，输出文件: {filename}")
        
        try:
            while True:
                try:
                    # 使用超时避免永久阻塞
                    result = result_queue.get(timeout=1)
                    
                    if result == "DONE":
                        logger.info("收到结束信号，保存最终结果...")
                        break
                    
                    if result is not None:
                        results.append(result)
                        processed_count += 1
                    
                    # 定期保存或达到批量大小时保存
                    current_time = time.time()
                    should_save = (
                        len(results) >= batch_size or 
                        (current_time - last_save_time > save_interval and results)
                    )
                    
                    if should_save:
                        # 保存到临时文件
                        df = pd.DataFrame(results)
                        df.to_csv(temp_filename, index=False, encoding='utf-8-sig')
                        logger.debug(f"已保存 {len(results)} 条结果到临时文件")
                        last_save_time = current_time
                        
                except queue.Empty:
                    # 检查是否应该关闭
                    if shutdown_event.is_set():
                        logger.info("检测到关闭信号，保存当前结果...")
                        break
                    continue
                except Exception as e:
                    logger.error(f"处理结果时出错: {e}")
                    continue
        
        finally:
            # 保存最终结果
            if results:
                df = pd.DataFrame(results)
                df.to_csv(filename, index=False, encoding='utf-8-sig')
                logger.info(f"最终结果已保存到: {filename}，共 {len(results)} 条记录")
                
                # 删除临时文件
                if os.path.exists(temp_filename):
                    os.remove(temp_filename)
                    
                # 返回统计信息
                SafeFileWriter._print_statistics(df)
            else:
                logger.warning("没有数据需要保存")
                
    @staticmethod
    def _print_statistics(df):
        """打印统计信息"""
        print(f"\n总共找到 {len(df)} 只符合条件的股票")
        
        # 按日期分组统计
        if 'screening_date' in df.columns:
            date_groups = df.groupby('screening_date').size()
            print("\n各日期筛选结果:")
            for date, count in date_groups.items():
                print(f"  {date}: {count} 只")
        
        # 显示平均动态股息率最高的10只股票
        if 'dynamic_yield' in df.columns and 'code' in df.columns:
            print("\n平均动态股息率最高的10只股票:")
            top_stocks = df.groupby('code')['dynamic_yield'].mean().sort_values(ascending=False).head(10)
            for code, avg_yield in top_stocks.items():
                stock_name = df[df['code'] == code]['name'].iloc[0] if 'name' in df.columns else ''
                print(f"  {code} {stock_name}: {avg_yield:.2f}%")