"""
数据获取模块 - A股股票行情和分红数据

使用 akshare 获取数据，并通过 MongoDB 进行存储，支持任务断点续传。
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Any, Tuple
from enum import Enum

import akshare as ak
import pandas as pd
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError


class TaskStatus(Enum):
    """任务状态枚举"""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PARTIAL = "partial"  # 部分完成


class DataAcquisition:
    """A股数据获取类，支持MongoDB存储和断点续传"""
    
    def __init__(self, mongo_uri: str = "mongodb://admin:red-a-2025@localhost:27017/", 
                 db_name: str = "stock_data"):
        """
        初始化数据获取类
        
        Parameters:
        -----------
        mongo_uri : str
            MongoDB连接URI
        db_name : str
            数据库名称
        """
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        
        # 创建集合
        self.stocks = self.db.stocks  # 股票列表
        self.daily_prices = self.db.daily_prices  # 日线数据
        self.dividends = self.db.dividends  # 分红数据
        self.tasks = self.db.tasks  # 任务管理
        
        # 创建索引
        self._create_indexes()
        
        # 测试连接
        try:
            self.client.server_info()
            print(f"成功连接到MongoDB: {mongo_uri}")
        except Exception as e:
            print(f"MongoDB连接失败: {e}")
            raise
    
    def _create_indexes(self):
        """创建数据库索引以提高查询性能"""
        # 股票列表索引
        self.stocks.create_index("stock_code", unique=True)
        
        # 日线数据复合索引
        self.daily_prices.create_index([
            ("stock_code", ASCENDING),
            ("date", DESCENDING)
        ], unique=True)
        
        # 分红数据索引
        self.dividends.create_index([
            ("stock_code", ASCENDING),
            ("ex_date", DESCENDING)
        ])
        
        # 任务索引
        self.tasks.create_index("task_id", unique=True)
        self.tasks.create_index("status")
        self.tasks.create_index("create_time")
    
    def create_task(self, task_type: str, params: dict) -> str:
        """
        创建数据获取任务
        
        Parameters:
        -----------
        task_type : str
            任务类型: 'stock_list', 'history', 'dividend', 'batch_history', 'batch_dividend'
        params : dict
            任务参数
        
        Returns:
        --------
        str: 任务ID
        """
        task_id = f"{task_type}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{time.time_ns()}"
        
        task_doc = {
            "task_id": task_id,
            "task_type": task_type,
            "params": params,
            "status": TaskStatus.PENDING.value,
            "progress": {
                "total": 0,
                "completed": 0,
                "failed": 0,
                "current": None
            },
            "create_time": datetime.now(),
            "update_time": datetime.now(),
            "error": None
        }
        
        self.tasks.insert_one(task_doc)
        return task_id
    
    def update_task_progress(self, task_id: str, total: int = None, 
                           completed: int = None, failed: int = None, 
                           current: str = None, status: TaskStatus = None,
                           error: str = None):
        """更新任务进度"""
        update_doc = {"$set": {"update_time": datetime.now()}}
        
        if total is not None:
            update_doc["$set"]["progress.total"] = total
        if completed is not None:
            update_doc["$set"]["progress.completed"] = completed
        if failed is not None:
            update_doc["$set"]["progress.failed"] = failed
        if current is not None:
            update_doc["$set"]["progress.current"] = current
        if status is not None:
            update_doc["$set"]["status"] = status.value
        if error is not None:
            update_doc["$set"]["error"] = error
        
        self.tasks.update_one({"task_id": task_id}, update_doc)
    
    def get_task_status(self, task_id: str) -> dict:
        """获取任务状态"""
        return self.tasks.find_one({"task_id": task_id})
    
    def get_all_stock_list(self, task_id: Optional[str] = None, 
                          force_update: bool = False) -> pd.DataFrame:
        """
        获取所有A股股票列表
        
        Parameters:
        -----------
        task_id : str, optional
            任务ID，用于跟踪进度
        force_update : bool
            是否强制更新
        
        Returns:
        --------
        pd.DataFrame
            包含股票代码、名称、上市日期等信息
        """
        # 检查是否需要更新
        if not force_update:
            # 检查最近更新时间
            latest = self.stocks.find_one(sort=[("update_time", DESCENDING)])
            if latest and (datetime.now() - latest['update_time']).days < 1:
                print("使用缓存的股票列表")
                cursor = self.stocks.find()
                return pd.DataFrame(list(cursor))
        
        # 创建任务
        if not task_id:
            task_id = self.create_task("stock_list", {})
        
        self.update_task_progress(task_id, status=TaskStatus.RUNNING)
        
        try:
            print("正在从akshare获取股票列表...")
            stock_info = ak.stock_info_a_code_name()
            
            if stock_info is not None and not stock_info.empty:
                stock_info = stock_info.rename(columns={
                    'code': 'stock_code',
                    'name': 'stock_name'
                })
                
                # 过滤退市股票
                stock_info = stock_info[~stock_info['stock_name'].str.contains('退', na=False)]
                
                # 添加更新时间
                stock_info['update_time'] = datetime.now()
                
                # 清空旧数据并插入新数据
                self.stocks.delete_many({})
                records = stock_info.to_dict('records')
                self.stocks.insert_many(records)
                
                self.update_task_progress(
                    task_id, 
                    total=len(stock_info),
                    completed=len(stock_info),
                    status=TaskStatus.COMPLETED
                )
                
                print(f"获取到 {len(stock_info)} 只股票")
                return stock_info
                
        except Exception as e:
            error_msg = f"获取股票列表失败: {e}"
            print(error_msg)
            self.update_task_progress(task_id, status=TaskStatus.FAILED, error=error_msg)
            return pd.DataFrame()
    
    def get_stock_history(self, stock_code: str, start_date: str, end_date: str, 
                         adjust: str = "qfq", task_id: Optional[str] = None) -> pd.DataFrame:
        """
        获取股票历史行情数据
        
        Parameters:
        -----------
        stock_code : str
            股票代码
        start_date : str
            开始日期 'YYYYMMDD'
        end_date : str
            结束日期 'YYYYMMDD'
        adjust : str
            复权类型
        task_id : str, optional
            任务ID
        
        Returns:
        --------
        pd.DataFrame
            历史行情数据
        """
        # 先检查数据库中是否有足够的数据
        query = {
            "stock_code": stock_code,
            "date": {
                "$gte": datetime.strptime(start_date, '%Y%m%d'),
                "$lte": datetime.strptime(end_date, '%Y%m%d')
            }
        }
        
        # 使用count_documents更高效地检查数据量
        expected_start = datetime.strptime(start_date, '%Y%m%d')
        expected_end = datetime.strptime(end_date, '%Y%m%d')
        expected_days = (expected_end - expected_start).days
        
        # 获取现有数据的日期范围
        pipeline = [
            {"$match": query},
            {"$group": {
                "_id": None,
                "count": {"$sum": 1},
                "min_date": {"$min": "$date"},
                "max_date": {"$max": "$date"}
            }}
        ]
        
        agg_result = list(self.daily_prices.aggregate(pipeline))
        
        if agg_result and agg_result[0]['count'] > 0:
            result = agg_result[0]
            # 如果数据范围完整（考虑非交易日，只要有50%以上的数据就认为完整）
            if (result['min_date'] <= expected_start and 
                result['max_date'] >= expected_end and 
                result['count'] >= expected_days * 0.5):
                
                # 从数据库获取数据
                cursor = self.daily_prices.find(query).sort("date", ASCENDING)
                df = pd.DataFrame(list(cursor))
                df['date'] = pd.to_datetime(df['date'])
                
                print(f"  {stock_code}: 数据已存在（{result['count']}条），从数据库返回")
                return df[['date', 'open', 'close', 'high', 'low', 'volume', 'amount', 'pct_change']]
        
        # 需要从API获取数据
        print(f"正在获取 {stock_code} 历史行情数据...")
        
        if task_id:
            self.update_task_progress(task_id, current=stock_code)
        
        try:
            df = ak.stock_zh_a_hist(
                symbol=stock_code,
                period="daily",
                start_date=start_date,
                end_date=end_date,
                adjust=adjust
            )
            
            if df is not None and not df.empty:
                # 重命名列
                df = df.rename(columns={
                    '日期': 'date',
                    '开盘': 'open',
                    '收盘': 'close',
                    '最高': 'high',
                    '最低': 'low',
                    '成交量': 'volume',
                    '成交额': 'amount',
                    '涨跌幅': 'pct_change'
                })
                
                # 确保日期格式
                df['date'] = pd.to_datetime(df['date'])
                
                # 保存到数据库
                records = []
                for _, row in df.iterrows():
                    record = {
                        "stock_code": stock_code,
                        "date": row['date'],
                        "open": float(row['open']),
                        "close": float(row['close']),
                        "high": float(row['high']),
                        "low": float(row['low']),
                        "volume": float(row['volume']),
                        "amount": float(row['amount']),
                        "pct_change": float(row['pct_change']) if pd.notna(row['pct_change']) else 0,
                        "adjust": adjust,
                        "update_time": datetime.now()
                    }
                    records.append(record)
                
                # 批量插入新数据
                if records:
                    # 先检查哪些数据已经存在
                    dates_to_check = [r['date'] for r in records]
                    existing_cursor = self.daily_prices.find({
                        "stock_code": stock_code,
                        "date": {"$in": dates_to_check}
                    }, {"date": 1})
                    existing_dates = {doc['date'] for doc in existing_cursor}
                    
                    # 只插入不存在的数据
                    new_records = [r for r in records if r['date'] not in existing_dates]
                    
                    if new_records:
                        try:
                            self.daily_prices.insert_many(new_records, ordered=False)
                            print(f"  插入 {len(new_records)} 条新数据（共获取 {len(records)} 条）")
                        except Exception as e:
                            print(f"  批量插入出错: {e}")
                            # 如果批量插入失败，逐条插入
                            for record in new_records:
                                try:
                                    self.daily_prices.insert_one(record)
                                except:
                                    pass
                    else:
                        print(f"  所有 {len(records)} 条数据已存在，跳过插入")
                
                return df
                
        except Exception as e:
            print(f"获取 {stock_code} 历史数据失败: {e}")
            return pd.DataFrame()
    
    def get_dividend_history(self, stock_code: str, task_id: Optional[str] = None) -> pd.DataFrame:
        """
        获取股票历史分红数据
        
        Parameters:
        -----------
        stock_code : str
            股票代码
        task_id : str, optional
            任务ID
        
        Returns:
        --------
        pd.DataFrame
            分红数据
        """
        # 先从数据库查询
        cursor = self.dividends.find({"stock_code": stock_code}).sort("ex_date", DESCENDING)
        existing_data = list(cursor)
        
        # 检查数据是否是最近更新的
        if existing_data:
            latest_update = max(d.get('update_time', datetime.min) for d in existing_data)
            if (datetime.now() - latest_update).days < 7:  # 7天内的数据认为是新的
                print(f"从数据库获取 {stock_code} 分红数据")
                df = pd.DataFrame(existing_data)
                return df
        
        # 从API获取数据
        print(f"正在获取 {stock_code} 分红数据...")
        
        if task_id:
            self.update_task_progress(task_id, current=stock_code)
        
        try:
            df = ak.stock_dividend_cninfo(symbol=stock_code)
            
            if df is not None and not df.empty:
                # 处理数据
                records = []
                for _, row in df.iterrows():
                    record = {
                        "stock_code": stock_code,
                        "announce_date": pd.to_datetime(row.get('公告日期'), errors='coerce'),
                        "record_date": pd.to_datetime(row.get('股权登记日'), errors='coerce'),
                        "ex_date": pd.to_datetime(row.get('除权除息日'), errors='coerce'),
                        "dividend_per_10_shares": float(row.get('派息(税前)(元)', 0) or 0),
                        "dividend_per_share": float(row.get('派息(税前)(元)', 0) or 0) / 10,
                        "bonus_shares": float(row.get('送股(股)', 0) or 0),
                        "capitalized_shares": float(row.get('转增(股)', 0) or 0),
                        "dividend_yield": float(row.get('股息率(%)', 0) or 0),
                        "dividend_year": row.get('分红年度'),
                        "update_time": datetime.now()
                    }
                    
                    # 只保存有效的除权日数据
                    if pd.notna(record['ex_date']) and record['dividend_per_10_shares'] > 0:
                        records.append(record)
                
                # 清除旧数据并插入新数据
                if records:
                    self.dividends.delete_many({"stock_code": stock_code})
                    self.dividends.insert_many(records)
                    
                    # 转换为DataFrame返回
                    df_result = pd.DataFrame(records)
                    return df_result
                    
            return pd.DataFrame()
            
        except Exception as e:
            print(f"获取 {stock_code} 分红数据失败: {e}")
            return pd.DataFrame()
    
    def get_missing_date_ranges(self, stock_code: str, start_date: str, end_date: str) -> List[Tuple[str, str]]:
        """
        获取缺失的日期范围
        
        Parameters:
        -----------
        stock_code : str
            股票代码
        start_date : str
            开始日期 'YYYYMMDD'
        end_date : str
            结束日期 'YYYYMMDD'
        
        Returns:
        --------
        List[Tuple[str, str]]: 缺失的日期范围列表，每个元组包含(开始日期, 结束日期)
        """
        # 查询已有数据的日期
        pipeline = [
            {
                "$match": {
                    "stock_code": stock_code,
                    "date": {
                        "$gte": datetime.strptime(start_date, '%Y%m%d'),
                        "$lte": datetime.strptime(end_date, '%Y%m%d')
                    }
                }
            },
            {
                "$group": {
                    "_id": None,
                    "dates": {"$push": "$date"},
                    "count": {"$sum": 1},
                    "min_date": {"$min": "$date"},
                    "max_date": {"$max": "$date"}
                }
            }
        ]
        
        result = list(self.daily_prices.aggregate(pipeline))
        
        if not result or result[0]['count'] == 0:
            # 完全没有数据，返回整个范围
            return [(start_date, end_date)]
        
        # 获取已有日期并排序
        existing_dates = sorted(result[0]['dates'])
        
        # 转换日期格式
        start_dt = datetime.strptime(start_date, '%Y%m%d')
        end_dt = datetime.strptime(end_date, '%Y%m%d')
        
        # 检查数据完整性（简化版：只检查起止范围）
        min_date = result[0]['min_date']
        max_date = result[0]['max_date']
        
        missing_ranges = []
        
        # 检查开始日期前是否有缺失
        if min_date > start_dt:
            missing_ranges.append((start_date, (min_date - timedelta(days=1)).strftime('%Y%m%d')))
        
        # 检查结束日期后是否有缺失
        if max_date < end_dt:
            missing_ranges.append(((max_date + timedelta(days=1)).strftime('%Y%m%d'), end_date))
        
        # 对于更精确的缺失检测，可以检查中间的断点
        # 但考虑到股市有非交易日，这里简化处理
        
        return missing_ranges
    
    def get_stock_history_smart(self, stock_code: str, start_date: str, end_date: str, 
                               adjust: str = "qfq", task_id: Optional[str] = None) -> pd.DataFrame:
        """
        智能获取股票历史行情数据（只获取缺失的部分）
        
        Parameters:
        -----------
        stock_code : str
            股票代码
        start_date : str
            开始日期 'YYYYMMDD'
        end_date : str
            结束日期 'YYYYMMDD'
        adjust : str
            复权类型
        task_id : str, optional
            任务ID
        
        Returns:
        --------
        pd.DataFrame
            历史行情数据
        """
        # 先检查缺失的日期范围
        missing_ranges = self.get_missing_date_ranges(stock_code, start_date, end_date)
        
        if not missing_ranges:
            # 数据已完整，直接从数据库返回
            print(f"  {stock_code}: 数据已完整，从数据库返回")
            query = {
                "stock_code": stock_code,
                "date": {
                    "$gte": datetime.strptime(start_date, '%Y%m%d'),
                    "$lte": datetime.strptime(end_date, '%Y%m%d')
                }
            }
            cursor = self.daily_prices.find(query).sort("date", ASCENDING)
            df = pd.DataFrame(list(cursor))
            if not df.empty:
                df['date'] = pd.to_datetime(df['date'])
                return df[['date', 'open', 'close', 'high', 'low', 'volume', 'amount', 'pct_change']]
            return pd.DataFrame()
        
        # 获取缺失的数据
        print(f"  {stock_code}: 检测到 {len(missing_ranges)} 段缺失数据")
        for range_start, range_end in missing_ranges:
            print(f"    获取缺失段: {range_start} - {range_end}")
            self.get_stock_history(stock_code, range_start, range_end, adjust, task_id)
        
        # 返回完整数据
        query = {
            "stock_code": stock_code,
            "date": {
                "$gte": datetime.strptime(start_date, '%Y%m%d'),
                "$lte": datetime.strptime(end_date, '%Y%m%d')
            }
        }
        cursor = self.daily_prices.find(query).sort("date", ASCENDING)
        df = pd.DataFrame(list(cursor))
        if not df.empty:
            df['date'] = pd.to_datetime(df['date'])
            return df[['date', 'open', 'close', 'high', 'low', 'volume', 'amount', 'pct_change']]
        return pd.DataFrame()
    
    def scan_missing_history_data(self, stock_codes: List[str], start_date: str, 
                                 end_date: str, min_days: int = 100) -> List[str]:
        """
        扫描缺失的历史数据
        
        Parameters:
        -----------
        stock_codes : List[str]
            要检查的股票代码列表
        start_date : str
            开始日期
        end_date : str
            结束日期
        min_days : int
            最少需要的交易日数据条数
        
        Returns:
        --------
        List[str]: 缺失或数据不完整的股票代码列表
        """
        print(f"扫描 {len(stock_codes)} 只股票的数据完整性...")
        
        # 使用聚合查询批量检查
        pipeline = [
            {
                "$match": {
                    "stock_code": {"$in": stock_codes},
                    "date": {
                        "$gte": datetime.strptime(start_date, '%Y%m%d'),
                        "$lte": datetime.strptime(end_date, '%Y%m%d')
                    }
                }
            },
            {
                "$group": {
                    "_id": "$stock_code",
                    "count": {"$sum": 1},
                    "min_date": {"$min": "$date"},
                    "max_date": {"$max": "$date"}
                }
            }
        ]
        
        result = list(self.daily_prices.aggregate(pipeline))
        
        # 已有完整数据的股票
        complete_stocks = set()
        for item in result:
            if item['count'] >= min_days:
                # 检查日期范围是否完整
                if (item['min_date'] <= datetime.strptime(start_date, '%Y%m%d') and 
                    item['max_date'] >= datetime.strptime(end_date, '%Y%m%d')):
                    complete_stocks.add(item['_id'])
        
        # 找出缺失的股票
        missing_stocks = [code for code in stock_codes if code not in complete_stocks]
        
        print(f"已有完整数据: {len(complete_stocks)} 只")
        print(f"需要获取数据: {len(missing_stocks)} 只")
        
        return missing_stocks
    
    def scan_missing_dividend_data(self, stock_codes: List[str], 
                                  days_threshold: int = 7) -> List[str]:
        """
        扫描缺失的分红数据
        
        Parameters:
        -----------
        stock_codes : List[str]
            要检查的股票代码列表
        days_threshold : int
            数据新鲜度阈值（天）
        
        Returns:
        --------
        List[str]: 缺失或需要更新的股票代码列表
        """
        print(f"扫描 {len(stock_codes)} 只股票的分红数据...")
        
        # 查询每只股票的最新更新时间
        pipeline = [
            {
                "$match": {"stock_code": {"$in": stock_codes}}
            },
            {
                "$group": {
                    "_id": "$stock_code",
                    "latest_update": {"$max": "$update_time"},
                    "count": {"$sum": 1}
                }
            }
        ]
        
        result = list(self.dividends.aggregate(pipeline))
        
        # 找出需要更新的股票
        fresh_stocks = set()
        cutoff_date = datetime.now() - timedelta(days=days_threshold)
        
        for item in result:
            if item['count'] > 0 and item['latest_update'] > cutoff_date:
                fresh_stocks.add(item['_id'])
        
        # 找出缺失的股票
        missing_stocks = [code for code in stock_codes if code not in fresh_stocks]
        
        print(f"数据新鲜: {len(fresh_stocks)} 只")
        print(f"需要更新: {len(missing_stocks)} 只")
        
        return missing_stocks
    
    def get_batch_stock_history(self, stock_codes: List[str], start_date: str, 
                               end_date: str, adjust: str = "qfq", 
                               check_existing: bool = True) -> Dict[str, pd.DataFrame]:
        """
        批量获取多只股票的历史数据（自动跳过已有完整数据的股票）
        
        Parameters:
        -----------
        stock_codes : List[str]
            股票代码列表
        start_date : str
            开始日期
        end_date : str
            结束日期
        adjust : str
            复权类型
        check_existing : bool
            是否检查已有数据（默认True）
        
        Returns:
        --------
        Dict[str, pd.DataFrame]
            股票代码到历史数据的映射
        """
        # 扫描缺失的数据
        if check_existing:
            stocks_to_fetch = self.scan_missing_history_data(stock_codes, start_date, end_date)
        else:
            stocks_to_fetch = stock_codes
        
        if not stocks_to_fetch:
            print("所有股票数据已完整，无需获取")
            # 返回已有数据
            results = {}
            for code in stock_codes:
                df = self.get_stock_history(code, start_date, end_date, adjust)
                if not df.empty:
                    results[code] = df
            return results
        
        # 创建任务记录进度
        task_id = self.create_task("batch_history", {
            "stock_codes": stocks_to_fetch,
            "start_date": start_date,
            "end_date": end_date,
            "adjust": adjust
        })
        
        results = {}
        total = len(stocks_to_fetch)
        completed = 0
        failed = 0
        
        self.update_task_progress(task_id, total=total, status=TaskStatus.RUNNING)
        
        for idx, code in enumerate(stocks_to_fetch, 1):
            print(f"获取进度: {idx}/{total} - {code}")
            
            try:
                df = self.get_stock_history(code, start_date, end_date, adjust, task_id)
                if not df.empty:
                    results[code] = df
                    completed += 1
                else:
                    failed += 1
                    
            except Exception as e:
                print(f"获取 {code} 失败: {e}")
                failed += 1
            
            # 更新进度
            self.update_task_progress(
                task_id,
                completed=completed,
                failed=failed,
                current=code
            )
            
            # 添加延时避免请求过快
            time.sleep(0.1)
        
        # 更新任务状态
        if failed == 0:
            status = TaskStatus.COMPLETED
        elif completed == 0:
            status = TaskStatus.FAILED
        else:
            status = TaskStatus.PARTIAL
        
        self.update_task_progress(task_id, status=status)
        
        print(f"批量获取完成: 成功 {completed} 只，失败 {failed} 只")
        
        # 如果需要，加载所有请求的股票数据（包括之前已有的）
        if check_existing and len(results) < len(stock_codes):
            print("加载完整数据集...")
            for code in stock_codes:
                if code not in results:
                    df = self.get_stock_history(code, start_date, end_date, adjust)
                    if not df.empty:
                        results[code] = df
        
        return results
    
    def get_batch_dividend_history(self, stock_codes: List[str], 
                                  check_existing: bool = True) -> Dict[str, pd.DataFrame]:
        """
        批量获取多只股票的分红数据（自动跳过新鲜数据的股票）
        
        Parameters:
        -----------
        stock_codes : List[str]
            股票代码列表
        check_existing : bool
            是否检查已有数据（默认True）
        
        Returns:
        --------
        Dict[str, pd.DataFrame]
            股票代码到分红数据的映射
        """
        # 扫描需要更新的数据
        if check_existing:
            stocks_to_fetch = self.scan_missing_dividend_data(stock_codes)
        else:
            stocks_to_fetch = stock_codes
        
        if not stocks_to_fetch:
            print("所有股票分红数据已是最新，无需获取")
            # 返回已有数据
            results = {}
            for code in stock_codes:
                df = self.get_dividend_history(code)
                if not df.empty:
                    results[code] = df
            return results
        
        # 创建任务记录进度
        task_id = self.create_task("batch_dividend", {"stock_codes": stocks_to_fetch})
        
        results = {}
        total = len(stocks_to_fetch)
        completed = 0
        failed = 0
        
        self.update_task_progress(task_id, total=total, status=TaskStatus.RUNNING)
        
        for idx, code in enumerate(stocks_to_fetch, 1):
            print(f"获取进度: {idx}/{total} - {code}")
            
            try:
                df = self.get_dividend_history(code, task_id)
                if not df.empty:
                    results[code] = df
                    completed += 1
                else:
                    failed += 1
                    
            except Exception as e:
                print(f"获取 {code} 失败: {e}")
                failed += 1
            
            # 更新进度
            self.update_task_progress(
                task_id,
                completed=completed,
                failed=failed,
                current=code
            )
            
            # 添加延时
            time.sleep(0.1)
        
        # 更新任务状态
        if failed == 0:
            status = TaskStatus.COMPLETED
        elif completed == 0:
            status = TaskStatus.FAILED
        else:
            status = TaskStatus.PARTIAL
        
        self.update_task_progress(task_id, status=status)
        
        print(f"批量获取完成: 成功 {completed} 只，失败 {failed} 只")
        
        # 如果需要，加载所有请求的股票数据（包括之前已有的）
        if check_existing and len(results) < len(stock_codes):
            print("加载完整数据集...")
            for code in stock_codes:
                if code not in results:
                    df = self.get_dividend_history(code)
                    if not df.empty:
                        results[code] = df
        
        return results
    
    def list_tasks(self, status: Optional[TaskStatus] = None, 
                   task_type: Optional[str] = None, 
                   limit: int = 20) -> List[dict]:
        """
        列出任务
        
        Parameters:
        -----------
        status : TaskStatus, optional
            筛选任务状态
        task_type : str, optional
            筛选任务类型
        limit : int
            返回数量限制
        
        Returns:
        --------
        List[dict]: 任务列表
        """
        query = {}
        if status:
            query["status"] = status.value
        if task_type:
            query["task_type"] = task_type
        
        cursor = self.tasks.find(query).sort("create_time", DESCENDING).limit(limit)
        return list(cursor)
    
    def check_data_completeness(self, stock_codes: List[str], start_date: str, 
                               end_date: str) -> dict:
        """
        检查数据完整性
        
        Parameters:
        -----------
        stock_codes : List[str]
            要检查的股票代码列表
        start_date : str
            开始日期
        end_date : str
            结束日期
        
        Returns:
        --------
        dict: 数据完整性报告
        """
        report = {
            "total_stocks": len(stock_codes),
            "history_complete": 0,
            "history_partial": 0,
            "history_missing": 0,
            "dividend_fresh": 0,
            "dividend_stale": 0,
            "dividend_missing": 0,
            "details": {
                "history_missing": [],
                "history_partial": [],
                "dividend_missing": [],
                "dividend_stale": []
            }
        }
        
        # 检查历史数据
        print("检查历史价格数据完整性...")
        missing_history = self.scan_missing_history_data(stock_codes, start_date, end_date)
        
        # 获取部分数据的股票
        pipeline = [
            {
                "$match": {
                    "stock_code": {"$in": stock_codes},
                    "date": {
                        "$gte": datetime.strptime(start_date, '%Y%m%d'),
                        "$lte": datetime.strptime(end_date, '%Y%m%d')
                    }
                }
            },
            {
                "$group": {
                    "_id": "$stock_code",
                    "count": {"$sum": 1}
                }
            }
        ]
        
        partial_data = list(self.daily_prices.aggregate(pipeline))
        partial_stocks = {item['_id']: item['count'] for item in partial_data if item['count'] < 100}
        
        # 分类统计
        for code in stock_codes:
            if code in missing_history:
                if code in partial_stocks:
                    report["history_partial"] += 1
                    report["details"]["history_partial"].append(
                        {"code": code, "days": partial_stocks[code]}
                    )
                else:
                    report["history_missing"] += 1
                    report["details"]["history_missing"].append(code)
            else:
                report["history_complete"] += 1
        
        # 检查分红数据
        print("检查分红数据新鲜度...")
        missing_dividend = self.scan_missing_dividend_data(stock_codes, days_threshold=7)
        stale_dividend = self.scan_missing_dividend_data(stock_codes, days_threshold=30)
        
        # 分类统计
        for code in stock_codes:
            if code in missing_dividend:
                if code in stale_dividend:
                    report["dividend_missing"] += 1
                    report["details"]["dividend_missing"].append(code)
                else:
                    report["dividend_stale"] += 1
                    report["details"]["dividend_stale"].append(code)
            else:
                report["dividend_fresh"] += 1
        
        return report
    
    def get_data_statistics(self) -> dict:
        """获取数据统计信息"""
        stats = {
            "stocks_count": self.stocks.count_documents({}),
            "daily_prices_count": self.daily_prices.count_documents({}),
            "dividends_count": self.dividends.count_documents({}),
            "tasks_count": self.tasks.count_documents({}),
            "tasks_by_status": {}
        }
        
        # 统计各状态任务数
        for status in TaskStatus:
            count = self.tasks.count_documents({"status": status.value})
            if count > 0:
                stats["tasks_by_status"][status.value] = count
        
        # 统计股票覆盖情况
        pipeline = [
            {"$group": {"_id": "$stock_code"}},
            {"$count": "unique_stocks"}
        ]
        
        price_stocks = list(self.daily_prices.aggregate(pipeline))
        stats["stocks_with_prices"] = price_stocks[0]["unique_stocks"] if price_stocks else 0
        
        dividend_stocks = list(self.dividends.aggregate(pipeline))
        stats["stocks_with_dividends"] = dividend_stocks[0]["unique_stocks"] if dividend_stocks else 0
        
        return stats
    
    def clear_data(self, collection_name: Optional[str] = None):
        """
        清除数据
        
        Parameters:
        -----------
        collection_name : str, optional
            要清除的集合名称，不指定则清除所有数据
        """
        if collection_name:
            if hasattr(self, collection_name):
                collection = getattr(self, collection_name)
                count = collection.count_documents({})
                collection.delete_many({})
                print(f"已清除 {collection_name} 中的 {count} 条数据")
            else:
                print(f"集合 {collection_name} 不存在")
        else:
            # 清除所有数据
            for name in ['stocks', 'daily_prices', 'dividends', 'tasks']:
                collection = getattr(self, name)
                count = collection.count_documents({})
                collection.delete_many({})
                print(f"已清除 {name} 中的 {count} 条数据")