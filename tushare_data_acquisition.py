"""
Tushare 数据获取模块 - A股股票行情和分红数据
使用 Tushare Pro API 获取天级别数据
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union
import pandas as pd
import tushare as ts
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
import threading


class TushareDataAcquisition:
    """使用 Tushare 获取A股数据"""
    
    def __init__(self, token: str, mongo_uri: str = "mongodb://admin:red-a-2025@localhost:27017/", 
                 db_name: str = "stock_data"):
        """
        初始化 Tushare 数据获取类
        
        Parameters:
        -----------
        token : str
            Tushare API token
        mongo_uri : str
            MongoDB连接URI
        db_name : str
            数据库名称
        """
        # 设置 Tushare token
        ts.set_token(token)
        self.pro = ts.pro_api()
        
        # MongoDB 连接
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        
        # 创建集合
        self.stocks = self.db.stocks
        self.daily_prices = self.db.daily_prices
        self.dividends = self.db.dividends
        
        # 创建索引
        self._create_indexes()
        
        # Tushare API 速率限制控制
        self.rate_limiter = threading.Semaphore(200)  # 每分钟200次的限制
        self.last_reset_time = time.time()
        self.request_count = 0
        self.lock = threading.Lock()
        
    def _create_indexes(self):
        """创建数据库索引"""
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
    
    def _rate_limit(self):
        """速率限制控制"""
        with self.lock:
            current_time = time.time()
            # 每分钟重置
            if current_time - self.last_reset_time > 60:
                self.rate_limiter = threading.Semaphore(200)
                self.last_reset_time = current_time
                self.request_count = 0
            
            self.rate_limiter.acquire()
            self.request_count += 1
            
            # 如果接近限制，添加延迟
            if self.request_count >= 180:
                time.sleep(1)
    
    def get_stock_list(self, list_status: str = 'L') -> pd.DataFrame:
        """
        获取股票列表
        
        Parameters:
        -----------
        list_status : str
            上市状态 L-上市 D-退市 P-暂停上市
        
        Returns:
        --------
        pd.DataFrame: 股票列表
        """
        try:
            # 速率限制
            self._rate_limit()
            
            # 从 Tushare 获取股票基本信息
            df = self.pro.stock_basic(exchange='', list_status=list_status, fields='ts_code,symbol,name,area,industry,list_date')
            
            if df is not None and not df.empty:
                # 转换股票代码格式 (去掉 .SH/.SZ 后缀)
                df['stock_code'] = df['symbol']
                df['stock_name'] = df['name']
                df['update_time'] = datetime.now()
                
                # 保存到数据库
                self.stocks.delete_many({})
                records = df[['stock_code', 'stock_name', 'ts_code', 'area', 'industry', 'list_date', 'update_time']].to_dict('records')
                self.stocks.insert_many(records)
                
                print(f"获取到 {len(df)} 只股票")
                return df
                
        except Exception as e:
            print(f"获取股票列表失败: {e}")
            return pd.DataFrame()
    
    def get_daily_data(self, stock_code: str, start_date: str, end_date: str) -> pd.DataFrame:
        """
        获取股票日线数据
        
        Parameters:
        -----------
        stock_code : str
            股票代码（如 '000001'）
        start_date : str
            开始日期 'YYYYMMDD'
        end_date : str
            结束日期 'YYYYMMDD'
        
        Returns:
        --------
        pd.DataFrame: 日线数据
        """
        # 转换股票代码格式
        ts_code = self._convert_stock_code(stock_code)
        if not ts_code:
            print(f"无法转换股票代码: {stock_code}")
            return pd.DataFrame()
        
        try:
            # 速率限制
            self._rate_limit()
            
            # 从 Tushare 获取日线数据
            df = self.pro.daily(ts_code=ts_code, start_date=start_date, end_date=end_date)
            
            if df is not None and not df.empty:
                # 按日期排序
                df = df.sort_values('trade_date')
                
                # 转换列名
                df = df.rename(columns={
                    'trade_date': 'date',
                    'open': 'open',
                    'high': 'high',
                    'low': 'low',
                    'close': 'close',
                    'vol': 'volume',
                    'amount': 'amount',
                    'pct_chg': 'pct_change'
                })
                
                # 转换日期格式
                df['date'] = pd.to_datetime(df['date'])
                
                # 添加股票代码
                df['stock_code'] = stock_code
                
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
                        "volume": float(row['volume']) * 100,  # Tushare 的成交量单位是手，需要转换为股
                        "amount": float(row['amount']) * 1000,  # Tushare 的成交额单位是千元，需要转换为元
                        "pct_change": float(row['pct_change']) if pd.notna(row['pct_change']) else 0,
                        "adjust": "qfq",  # 前复权
                        "update_time": datetime.now()
                    }
                    records.append(record)
                
                # 批量更新或插入
                if records:
                    for record in records:
                        self.daily_prices.update_one(
                            {
                                "stock_code": record["stock_code"],
                                "date": record["date"]
                            },
                            {"$set": record},
                            upsert=True
                        )
                
                print(f"获取 {stock_code} 的 {len(df)} 条日线数据")
                return df
                
        except Exception as e:
            print(f"获取 {stock_code} 日线数据失败: {e}")
            return pd.DataFrame()
    
    def get_dividend_data(self, stock_code: str) -> pd.DataFrame:
        """
        获取股票分红数据
        
        Parameters:
        -----------
        stock_code : str
            股票代码
        
        Returns:
        --------
        pd.DataFrame: 分红数据
        """
        # 转换股票代码格式
        ts_code = self._convert_stock_code(stock_code)
        if not ts_code:
            return pd.DataFrame()
        
        try:
            # 速率限制
            self._rate_limit()
            
            # 从 Tushare 获取分红数据
            df = self.pro.dividend(ts_code=ts_code)
            
            if df is not None and not df.empty:
                # 过滤出有现金分红的记录
                df = df[df['cash_div_tax'] > 0]
                
                if df.empty:
                    return pd.DataFrame()
                
                # 转换数据
                records = []
                for _, row in df.iterrows():
                    record = {
                        "stock_code": stock_code,
                        "announce_date": pd.to_datetime(row['ann_date'], format='%Y%m%d') if pd.notna(row['ann_date']) else None,
                        "record_date": pd.to_datetime(row['record_date'], format='%Y%m%d') if pd.notna(row['record_date']) else None,
                        "ex_date": pd.to_datetime(row['ex_date'], format='%Y%m%d') if pd.notna(row['ex_date']) else None,
                        "dividend_per_10_shares": float(row['cash_div_tax']) * 10,  # Tushare 是每股分红，需要转换为每10股
                        "dividend_per_share": float(row['cash_div_tax']),
                        "bonus_shares": float(row['stk_bo_rate']) if pd.notna(row['stk_bo_rate']) else 0,  # 送股比例
                        "capitalized_shares": float(row['stk_co_rate']) if pd.notna(row['stk_co_rate']) else 0,  # 转增比例
                        "dividend_year": row['end_date'][:4] if pd.notna(row['end_date']) else '',  # 分红年度
                        "update_time": datetime.now()
                    }
                    
                    # 只保存有效的除权日数据
                    if pd.notna(record['ex_date']) and record['dividend_per_10_shares'] > 0:
                        records.append(record)
                
                # 保存到数据库
                if records:
                    self.dividends.delete_many({"stock_code": stock_code})
                    self.dividends.insert_many(records)
                    
                    print(f"获取 {stock_code} 的 {len(records)} 条分红记录")
                    return pd.DataFrame(records)
                    
            return pd.DataFrame()
            
        except Exception as e:
            print(f"获取 {stock_code} 分红数据失败: {e}")
            return pd.DataFrame()
    
    def _convert_stock_code(self, stock_code: str) -> str:
        """
        转换股票代码为 Tushare 格式
        
        Parameters:
        -----------
        stock_code : str
            股票代码（如 '000001'）
        
        Returns:
        --------
        str: Tushare 格式的股票代码（如 '000001.SZ'）
        """
        # 查询股票信息获取 ts_code
        stock_info = self.stocks.find_one({"stock_code": stock_code})
        if stock_info and 'ts_code' in stock_info:
            return stock_info['ts_code']
        
        # 如果数据库中没有，根据规则推断
        if stock_code.startswith('60') or stock_code.startswith('68'):
            return f"{stock_code}.SH"
        elif stock_code.startswith('00') or stock_code.startswith('30'):
            return f"{stock_code}.SZ"
        else:
            return None
    
    def batch_get_daily_data(self, stock_codes: List[str], start_date: str, end_date: str) -> Dict[str, pd.DataFrame]:
        """
        批量获取多只股票的日线数据
        
        Parameters:
        -----------
        stock_codes : List[str]
            股票代码列表
        start_date : str
            开始日期
        end_date : str
            结束日期
        
        Returns:
        --------
        Dict[str, pd.DataFrame]: 股票代码到数据的映射
        """
        results = {}
        total = len(stock_codes)
        
        for idx, code in enumerate(stock_codes, 1):
            print(f"获取进度: {idx}/{total} - {code}")
            
            try:
                df = self.get_daily_data(code, start_date, end_date)
                if not df.empty:
                    results[code] = df
                    
            except Exception as e:
                print(f"获取 {code} 失败: {e}")
            
            # Tushare 有访问频率限制，添加延时
            time.sleep(0.2)  # 每分钟最多300次请求
        
        print(f"批量获取完成: 成功 {len(results)} 只")
        return results
    
    def batch_get_dividend_data(self, stock_codes: List[str]) -> Dict[str, pd.DataFrame]:
        """
        批量获取多只股票的分红数据
        
        Parameters:
        -----------
        stock_codes : List[str]
            股票代码列表
        
        Returns:
        --------
        Dict[str, pd.DataFrame]: 股票代码到分红数据的映射
        """
        results = {}
        total = len(stock_codes)
        
        for idx, code in enumerate(stock_codes, 1):
            print(f"获取分红数据进度: {idx}/{total} - {code}")
            
            try:
                df = self.get_dividend_data(code)
                if not df.empty:
                    results[code] = df
                    
            except Exception as e:
                print(f"获取 {code} 分红数据失败: {e}")
            
            # 添加延时
            time.sleep(0.2)
        
        print(f"批量获取分红数据完成: 成功 {len(results)} 只")
        return results


# 测试代码
if __name__ == "__main__":
    # 使用您提供的 token
    token = "c534aca85b3eecadff354c3e68501a00fc52fa146c50fc7aa77ebb98"
    
    # 创建 Tushare 数据获取实例
    tushare_da = TushareDataAcquisition(token)
    
    # 测试获取股票列表
    print("测试获取股票列表...")
    stock_list = tushare_da.get_stock_list()
    print(f"获取到 {len(stock_list)} 只股票")
    
    # 测试获取单只股票的日线数据
    if not stock_list.empty:
        test_code = "000001"  # 平安银行
        print(f"\n测试获取 {test_code} 的日线数据...")
        daily_df = tushare_da.get_daily_data(test_code, "20240101", "20241231")
        if not daily_df.empty:
            print(f"获取到 {len(daily_df)} 条日线数据")
            print(daily_df.head())
        
        # 测试获取分红数据
        print(f"\n测试获取 {test_code} 的分红数据...")
        div_df = tushare_da.get_dividend_data(test_code)
        if not div_df.empty:
            print(f"获取到 {len(div_df)} 条分红记录")
            print(div_df.head())