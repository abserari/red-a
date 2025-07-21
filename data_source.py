"""
数据源管理模块 - 统一管理BaoStock数据接口
"""
import baostock as bs
import pandas as pd
import time
import logging
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, List

logger = logging.getLogger(__name__)


class BaoStockDataSource:
    """BaoStock数据源管理器"""
    
    def __init__(self):
        """初始化数据源"""
        self._logged_in = False
        self._cache: Dict[str, pd.DataFrame] = {}
        
    def __enter__(self):
        """上下文管理器入口"""
        self.login()
        return self
        
    def __exit__(self, exc_type, exc_val, exc_tb):
        """上下文管理器出口"""
        self.logout()
        
    def login(self):
        """登录BaoStock"""
        if not self._logged_in:
            lg = bs.login()
            if lg.error_code != '0':
                raise Exception(f"BaoStock登录失败: {lg.error_msg}")
            self._logged_in = True
            logger.info("成功登录BaoStock")
            
    def logout(self):
        """登出BaoStock"""
        if self._logged_in:
            try:
                bs.logout()
                self._logged_in = False
                logger.info("已登出BaoStock")
            except Exception as e:
                logger.error(f"登出BaoStock失败: {e}")
                
    def convert_stock_code(self, code: str) -> str:
        """转换股票代码格式
        
        Args:
            code: 股票代码 (支持多种格式)
            
        Returns:
            BaoStock格式代码 (如 sh.600036)
        """
        if '.' in code:
            if code.startswith('sh.') or code.startswith('sz.'):
                return code
            # 从 600036.SH 转换为 sh.600036
            stock_code = code.split('.')[0]
            market = code.split('.')[1].lower()
            return f"{market}.{stock_code}"
        else:
            # 根据代码判断市场
            if code.startswith('6'):
                return f"sh.{code}"
            elif code.startswith('0') or code.startswith('3'):
                return f"sz.{code}"
            else:
                return f"sz.{code}"
                
    def get_stock_history(self, code: str, start_date: datetime, 
                         end_date: datetime, frequency: str = "d") -> Optional[pd.DataFrame]:
        """获取股票历史数据（含前复权）
        
        Args:
            code: 股票代码
            start_date: 开始日期
            end_date: 结束日期
            frequency: 数据频率 (d=日线, w=周线, m=月线)
            
        Returns:
            包含前复权价格的DataFrame
        """
        bs_code = self.convert_stock_code(code)
        cache_key = f"{bs_code}_{start_date}_{end_date}_{frequency}"
        
        # 检查缓存
        if cache_key in self._cache:
            return self._cache[cache_key]
            
        # 获取复权因子
        rs_factor = bs.query_adjust_factor(
            code=bs_code,
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d')
        )
        
        factor_df = []
        while (rs_factor.error_code == '0') & rs_factor.next():
            factor_df.append(rs_factor.get_row_data())
            
        if factor_df:
            factor_df = pd.DataFrame(factor_df, columns=rs_factor.fields)
            factor_df['date'] = pd.to_datetime(factor_df['dividOperateDate'])
            factor_df = factor_df.set_index('date')
            factor_df['foreAdjustFactor'] = factor_df['foreAdjustFactor'].astype(float)
        else:
            factor_df = pd.DataFrame()
            
        # 获取日线数据
        rs = bs.query_history_k_data_plus(
            bs_code,
            "date,open,high,low,close,volume,amount,turn,pctChg",
            start_date=start_date.strftime('%Y-%m-%d'),
            end_date=end_date.strftime('%Y-%m-%d'),
            frequency=frequency,
            adjustflag="3"  # 不复权
        )
        
        if rs.error_code != '0':
            logger.warning(f"获取{bs_code}历史数据失败: {rs.error_msg}")
            return None
            
        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())
            
        if not data_list:
            return None
            
        # 创建DataFrame
        df = pd.DataFrame(data_list, columns=rs.fields)
        df['date'] = pd.to_datetime(df['date'])
        df = df.set_index('date')
        
        # 转换为数值类型
        numeric_columns = ['open', 'high', 'low', 'close', 'volume', 'amount', 'turn', 'pctChg']
        for col in numeric_columns:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors='coerce')
                
        # 前复权处理
        if not factor_df.empty:
            df = df.join(factor_df[['foreAdjustFactor']], how='left')
            df['foreAdjustFactor'] = df['foreAdjustFactor'].ffill().fillna(1.0)
            
            # 应用前复权
            price_columns = ['open', 'high', 'low', 'close']
            for col in price_columns:
                df[f'{col}_adj'] = df[col] * df['foreAdjustFactor']
        else:
            # 如果没有复权因子，直接使用原始价格
            for col in ['open', 'high', 'low', 'close']:
                df[f'{col}_adj'] = df[col]
                
        # 缓存数据
        self._cache[cache_key] = df
        
        # 避免请求过快
        time.sleep(0.1)
        
        return df
        
    def get_dividend_data(self, code: str, year: int) -> pd.DataFrame:
        """获取分红数据
        
        Args:
            code: 股票代码
            year: 年份
            
        Returns:
            分红数据DataFrame
        """
        bs_code = self.convert_stock_code(code)
        cache_key = f"div_{bs_code}_{year}"
        
        # 检查缓存
        if cache_key in self._cache:
            return self._cache[cache_key]
            
        rs = bs.query_dividend_data(code=bs_code, year=str(year), yearType="report")
        
        if rs.error_code != '0':
            return pd.DataFrame()
            
        dividend_list = []
        while (rs.error_code == '0') & rs.next():
            dividend_list.append(rs.get_row_data())
            
        if not dividend_list:
            return pd.DataFrame()
            
        # 创建DataFrame
        df = pd.DataFrame(dividend_list, columns=rs.fields)
        
        # 转换日期和数值类型
        date_columns = ['preNoticeDate', 'agmAnnouncementDate', 'planAnnounceDate', 
                       'lastTradeDate', 'dividDate', 'payDate', 'dividRegistDate']
        
        for col in date_columns:
            if col in df.columns:
                df[col] = pd.to_datetime(df[col], errors='coerce')
                
        # 转换分红金额
        if 'cashDiviPerShare' in df.columns:
            df['cashDiviPerShare'] = pd.to_numeric(df['cashDiviPerShare'], errors='coerce')
            
        # 缓存数据
        self._cache[cache_key] = df
        
        # 避免请求过快
        time.sleep(0.1)
        
        return df
        
    def get_stock_list(self, date: Optional[datetime] = None) -> pd.DataFrame:
        """获取股票列表
        
        Args:
            date: 交易日期，默认为今天
            
        Returns:
            股票列表DataFrame
        """
        if date is None:
            date = datetime.now()
            
        rs = bs.query_all_stock(day=date.strftime('%Y-%m-%d'))
        
        if rs.error_code != '0':
            logger.error(f"获取股票列表失败: {rs.error_msg}")
            return pd.DataFrame()
            
        data_list = []
        while (rs.error_code == '0') & rs.next():
            data_list.append(rs.get_row_data())
            
        if not data_list:
            return pd.DataFrame()
            
        df = pd.DataFrame(data_list, columns=rs.fields)
        
        # 只保留A股
        if 'type' in df.columns:
            df = df[df['type'] == '1']  # 1表示股票
            
        return df
        
    def get_trading_day_price(self, code: str, target_date: datetime, 
                             direction: str = 'forward') -> Tuple[Optional[float], Optional[datetime]]:
        """获取最近交易日的价格
        
        Args:
            code: 股票代码
            target_date: 目标日期
            direction: 查找方向 ('forward'=向后, 'backward'=向前)
            
        Returns:
            (价格, 实际交易日期) 元组
        """
        # 扩大查询范围
        if direction == 'forward':
            start_date = target_date
            end_date = target_date + timedelta(days=10)
        else:
            start_date = target_date - timedelta(days=10)
            end_date = target_date
            
        # 获取价格数据
        df = self.get_stock_history(code, start_date, end_date)
        if df is None or df.empty:
            return None, None
            
        # 查找最近的交易日
        if direction == 'forward':
            # 查找target_date当天或之后的第一个交易日
            valid_dates = df.index[df.index >= target_date]
            if len(valid_dates) > 0:
                trade_date = valid_dates[0]
                return float(df.loc[trade_date, 'close_adj']), trade_date
        else:
            # 查找target_date当天或之前的第一个交易日
            valid_dates = df.index[df.index <= target_date]
            if len(valid_dates) > 0:
                trade_date = valid_dates[-1]
                return float(df.loc[trade_date, 'close_adj']), trade_date
                
        return None, None