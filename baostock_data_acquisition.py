"""
BaoStock 数据获取模块 - A股股票行情和分红数据
使用 BaoStock 免费数据源，无需 token，直接获取数据
"""

import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Union, Tuple
import pandas as pd
import baostock as bs
from pymongo import MongoClient, ASCENDING, DESCENDING
from pymongo.errors import DuplicateKeyError
import threading


class BaoStockDataAcquisition:
    """使用 BaoStock 获取A股数据"""
    
    def __init__(self, mongo_uri: str = "mongodb://admin:red-a-2025@localhost:27017/", 
                 db_name: str = "stock_data"):
        """
        初始化 BaoStock 数据获取类
        
        Parameters:
        -----------
        mongo_uri : str
            MongoDB连接URI
        db_name : str
            数据库名称
        """
        # 登录 BaoStock
        self.login_result = bs.login()
        if self.login_result.error_code != '0':
            raise ConnectionError(f"BaoStock 登录失败: {self.login_result.error_msg}")
        print("BaoStock 登录成功")
        
        # MongoDB 连接
        self.client = MongoClient(mongo_uri)
        self.db = self.client[db_name]
        
        # 创建集合
        self.stocks = self.db.stocks
        self.daily_prices = self.db.daily_prices
        self.dividends = self.db.dividends
        
        # 创建索引
        self._create_indexes()
        
        # 线程锁，用于并发控制
        self.lock = threading.Lock()
        
    def __del__(self):
        """析构函数，登出 BaoStock"""
        try:
            bs.logout()
        except:
            pass
    
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
    
    def get_stock_list(self) -> pd.DataFrame:
        """
        获取股票列表
        
        Returns:
        --------
        pd.DataFrame: 股票列表
        """
        try:
            # 获取证券基本资料
            rs = bs.query_stock_basic()
            
            data_list = []
            while (rs.error_code == '0') & rs.next():
                # 获取一条记录，将记录合并在一起
                row_data = rs.get_row_data()
                data_list.append(row_data)
            
            if not data_list:
                print("BaoStock 未返回股票列表数据")
                return pd.DataFrame()
            
            df = pd.DataFrame(data_list, columns=rs.fields)
            
            # 只保留上市状态为1的股票（正常上市）
            df = df[df['status'] == '1']
            
            # 只保留股票类型为1的（股票）
            df = df[df['type'] == '1']
            
            # 转换数据格式
            df['stock_code'] = df['code'].str.replace('.', '').str.replace('sh', '').str.replace('sz', '')
            df['stock_name'] = df['code_name']
            df['update_time'] = datetime.now()
            
            # 保存到数据库
            self.stocks.delete_many({})
            records = df[['stock_code', 'stock_name', 'code', 'ipoDate', 'outDate', 'type', 'status', 'update_time']].to_dict('records')
            self.stocks.insert_many(records)
            
            print(f"BaoStock 获取到 {len(df)} 只股票")
            return df
            
        except Exception as e:
            print(f"BaoStock 获取股票列表失败: {e}")
            return pd.DataFrame()
    
    def get_daily_data(self, stock_code: str, start_date: str, end_date: str, 
                       frequency: str = "d", adjustflag: str = "2") -> pd.DataFrame:
        """
        获取股票日线数据
        
        Parameters:
        -----------
        stock_code : str
            股票代码（如 '000001'）
        start_date : str
            开始日期 'YYYY-MM-DD'
        end_date : str
            结束日期 'YYYY-MM-DD'
        frequency : str
            数据频率，d=日k线、w=周、m=月、5=5分钟、15=15分钟、30=30分钟、60=60分钟k线数据
        adjustflag : str
            复权类型，1：后复权；2：前复权；3：不复权；默认为2
        
        Returns:
        --------
        pd.DataFrame: 日线数据
        """
        # 转换股票代码格式
        bs_code = self._convert_stock_code(stock_code)
        if not bs_code:
            print(f"无法转换股票代码: {stock_code}")
            return pd.DataFrame()
        
        # 转换日期格式
        start_date_bs = datetime.strptime(start_date, '%Y%m%d').strftime('%Y-%m-%d')
        end_date_bs = datetime.strptime(end_date, '%Y%m%d').strftime('%Y-%m-%d')
        
        try:
            # 获取日线数据
            rs = bs.query_history_k_data_plus(
                bs_code,
                "date,code,open,high,low,close,preclose,volume,amount,adjustflag,turn,tradestatus,pctChg,isST",
                start_date=start_date_bs,
                end_date=end_date_bs,
                frequency=frequency,
                adjustflag=adjustflag
            )
            
            data_list = []
            while (rs.error_code == '0') & rs.next():
                data_list.append(rs.get_row_data())
            
            if not data_list:
                return pd.DataFrame()
            
            df = pd.DataFrame(data_list, columns=rs.fields)
            
            # 过滤停牌数据（tradestatus=0为停牌）
            df = df[df['tradestatus'] == '1']
            
            if df.empty:
                return pd.DataFrame()
            
            # 转换数据类型
            numeric_columns = ['open', 'high', 'low', 'close', 'preclose', 'volume', 'amount', 'turn', 'pctChg']
            for col in numeric_columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            
            # 转换日期
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
                    "pct_change": float(row['pctChg']),
                    "adjust": "qfq" if adjustflag == "2" else ("hfq" if adjustflag == "1" else "no"),
                    "update_time": datetime.now()
                }
                records.append(record)
            
            # 批量更新或插入
            if records:
                with self.lock:
                    for record in records:
                        self.daily_prices.update_one(
                            {
                                "stock_code": record["stock_code"],
                                "date": record["date"]
                            },
                            {"$set": record},
                            upsert=True
                        )
            
            print(f"BaoStock 获取 {stock_code} 的 {len(df)} 条日线数据")
            
            # 确保返回的 DataFrame 包含必要的列
            result_df = pd.DataFrame()
            result_df['date'] = df['date']
            result_df['open'] = df['open']
            result_df['close'] = df['close']
            result_df['high'] = df['high']
            result_df['low'] = df['low']
            result_df['volume'] = df['volume']
            result_df['amount'] = df['amount']
            result_df['pct_change'] = df['pctChg']
            
            return result_df
            
        except Exception as e:
            print(f"BaoStock 获取 {stock_code} 日线数据失败: {e}")
            return pd.DataFrame()
    
    def get_dividend_data(self, stock_code: str, year: Optional[str] = None, 
                         yearType: Optional[str] = None) -> pd.DataFrame:
        """
        获取股票分红数据
        
        Parameters:
        -----------
        stock_code : str
            股票代码
        year : str, optional
            年份，如 "2023"
        yearType : str, optional
            年份类别，预案公告日、股权登记日、除权除息日、派息日
        
        Returns:
        --------
        pd.DataFrame: 分红数据
        """
        # 转换股票代码格式
        bs_code = self._convert_stock_code(stock_code)
        if not bs_code:
            return pd.DataFrame()
        
        try:
            # 查询分红数据
            dividend_list = []
            
            # 如果没有指定年份，获取近10年的数据
            if year is None:
                years = [str(y) for y in range(datetime.now().year - 10, datetime.now().year + 1)]
            else:
                years = [year]
            
            for y in years:
                for yt in ["预案公告日", "股权登记日", "除权除息日", "派息日"]:
                    rs = bs.query_dividend_data(code=bs_code, year=y, yearType=yt)
                    
                    while (rs.error_code == '0') & rs.next():
                        row_data = rs.get_row_data()
                        dividend_list.append(row_data)
            
            if not dividend_list:
                return pd.DataFrame()
            
            # 创建 DataFrame
            fields = ['code', 'dividPreNoticeDate', 'dividAgmPumDate', 'dividPlanAnnounceDate',
                     'dividPlanDate', 'dividRegistDate', 'dividOperateDate', 'dividPayDate',
                     'dividStockMarketDate', 'dividCashPsBeforeTax', 'dividCashPsAfterTax',
                     'dividStocksPs', 'dividCashStock', 'dividReserveToStockPs']
            
            df = pd.DataFrame(dividend_list, columns=fields)
            
            # 去重
            df = df.drop_duplicates()
            
            # 过滤有现金分红的记录
            df['dividCashPsBeforeTax'] = pd.to_numeric(df['dividCashPsBeforeTax'], errors='coerce')
            df = df[df['dividCashPsBeforeTax'] > 0]
            
            if df.empty:
                return pd.DataFrame()
            
            # 转换数据
            records = []
            for _, row in df.iterrows():
                # 除权除息日
                ex_date = pd.to_datetime(row['dividOperateDate'], errors='coerce') if row['dividOperateDate'] else None
                
                if pd.notna(ex_date):
                    record = {
                        "stock_code": stock_code,
                        "announce_date": pd.to_datetime(row['dividPreNoticeDate'], errors='coerce') if row['dividPreNoticeDate'] else None,
                        "record_date": pd.to_datetime(row['dividRegistDate'], errors='coerce') if row['dividRegistDate'] else None,
                        "ex_date": ex_date,
                        "dividend_per_share": float(row['dividCashPsBeforeTax']),
                        "dividend_per_10_shares": float(row['dividCashPsBeforeTax']) * 10,
                        "bonus_shares": float(row['dividStocksPs']) if pd.notna(row['dividStocksPs']) else 0,
                        "capitalized_shares": float(row['dividReserveToStockPs']) if pd.notna(row['dividReserveToStockPs']) else 0,
                        "update_time": datetime.now()
                    }
                    records.append(record)
            
            # 保存到数据库
            if records:
                with self.lock:
                    self.dividends.delete_many({"stock_code": stock_code})
                    self.dividends.insert_many(records)
                
                print(f"BaoStock 获取 {stock_code} 的 {len(records)} 条分红记录")
                return pd.DataFrame(records)
            
            return pd.DataFrame()
            
        except Exception as e:
            print(f"BaoStock 获取 {stock_code} 分红数据失败: {e}")
            return pd.DataFrame()
    
    def _convert_stock_code(self, stock_code: str) -> str:
        """
        转换股票代码为 BaoStock 格式
        
        Parameters:
        -----------
        stock_code : str
            股票代码（如 '000001'）
        
        Returns:
        --------
        str: BaoStock 格式的股票代码（如 'sz.000001'）
        """
        # 根据股票代码判断交易所
        if stock_code.startswith('60') or stock_code.startswith('68'):
            return f"sh.{stock_code}"
        elif stock_code.startswith('00') or stock_code.startswith('30'):
            return f"sz.{stock_code}"
        elif stock_code.startswith('83') or stock_code.startswith('87') or stock_code.startswith('43'):
            return f"bj.{stock_code}"
        else:
            # 尝试从数据库查找
            stock_info = self.stocks.find_one({"stock_code": stock_code})
            if stock_info and 'code' in stock_info:
                return stock_info['code']
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
            print(f"BaoStock 获取进度: {idx}/{total} - {code}")
            
            try:
                df = self.get_daily_data(code, start_date, end_date)
                if not df.empty:
                    results[code] = df
                    
            except Exception as e:
                print(f"获取 {code} 失败: {e}")
            
            # BaoStock 没有明确的速率限制，但建议适当延时
            if idx % 10 == 0:
                time.sleep(0.1)
        
        print(f"BaoStock 批量获取完成: 成功 {len(results)} 只")
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
            print(f"BaoStock 获取分红数据进度: {idx}/{total} - {code}")
            
            try:
                df = self.get_dividend_data(code)
                if not df.empty:
                    results[code] = df
                    
            except Exception as e:
                print(f"获取 {code} 分红数据失败: {e}")
            
            # 适当延时
            if idx % 10 == 0:
                time.sleep(0.1)
        
        print(f"BaoStock 批量获取分红数据完成: 成功 {len(results)} 只")
        return results


# 测试代码
if __name__ == "__main__":
    # 创建 BaoStock 数据获取实例
    baostock_da = BaoStockDataAcquisition()
    
    try:
        # 测试获取股票列表
        print("测试获取股票列表...")
        stock_list = baostock_da.get_stock_list()
        print(f"获取到 {len(stock_list)} 只股票")
        
        # 测试获取单只股票的日线数据
        if not stock_list.empty:
            test_code = "000001"  # 平安银行
            print(f"\n测试获取 {test_code} 的日线数据...")
            daily_df = baostock_da.get_daily_data(test_code, "20240101", "20241231")
            if not daily_df.empty:
                print(f"获取到 {len(daily_df)} 条日线数据")
                print(daily_df.head())
            
            # 测试获取分红数据
            print(f"\n测试获取 {test_code} 的分红数据...")
            div_df = baostock_da.get_dividend_data(test_code)
            if not div_df.empty:
                print(f"获取到 {len(div_df)} 条分红记录")
                print(div_df.head())
    
    finally:
        # 确保登出
        del baostock_da