"""
股票筛选模块 - 基于分红率筛选高股息股票
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import logging
from typing import List, Dict, Optional
from tqdm import tqdm

from data_source import BaoStockDataSource
from dividend import calculate_comprehensive_dividend_yield

logger = logging.getLogger(__name__)


class DividendScreener:
    """红利股票筛选器"""
    
    def __init__(self, stock_codes: Optional[List[str]] = None, excel_file: Optional[str] = None):
        """
        初始化筛选器
        
        Args:
            stock_codes: 要筛选的股票代码列表，如果为None则从文件读取
            excel_file: Excel文件路径，如果为None则使用默认文件
        """
        self.excel_file = excel_file or '分红2025.xlsx'
        self.stock_codes = stock_codes or self._load_stock_codes()
        self.data_source = BaoStockDataSource()
        self.results = []
        
    def _load_stock_codes(self) -> List[str]:
        """从Excel文件或share_pool加载股票代码"""
        # 如果指定了use_share_pool，从share_pool.py导入
        if self.excel_file == 'share_pool':
            try:
                from share_pool import share_list
                # 转换代码格式：去掉.SH/.SZ后缀
                codes = [code.split('.')[0] for code in share_list]
                logger.info(f"从share_pool.py加载了 {len(codes)} 个股票代码")
                return codes
            except ImportError:
                logger.warning("无法导入share_pool.py")
                return self._get_default_stock_pool()
        
        try:
            # 尝试从Excel文件读取
            df = pd.read_excel(self.excel_file)
            codes = df.iloc[:, 0].astype(str).tolist()
            logger.info(f"从Excel文件 {self.excel_file} 加载了 {len(codes)} 个股票代码")
            return codes
        except Exception as e:
            logger.warning(f"无法读取Excel文件 {self.excel_file}: {e}")
            # 使用默认股票池
            return self._get_default_stock_pool()
            
    def _get_default_stock_pool(self) -> List[str]:
        """获取默认股票池"""
        # 一些知名的高分红股票代码
        return [
            '600036', '600104', '600900', '601288', '601398',
            '601939', '601988', '000002', '000651', '000858',
            '002142', '002415', '600519', '000568', '600309'
        ]
        
    def screen_stocks(self, years: int = 5, min_yield: float = 6.0,
                     screening_date: Optional[datetime] = None) -> pd.DataFrame:
        """
        筛选高分红股票
        
        Args:
            years: 要检查的年数
            min_yield: 最低分红率要求(%)
            screening_date: 筛选基准日期
            
        Returns:
            筛选结果DataFrame
        """
        if screening_date is None:
            # 使用2024年作为筛选基准日期，确保有历史数据
            screening_date = datetime(2024, 7, 21)
            
        logger.info(f"开始筛选，共 {len(self.stock_codes)} 只股票")
        logger.info(f"筛选条件: 连续{years}年分红率 >= {min_yield}%")
        
        with self.data_source:
            for code in tqdm(self.stock_codes, desc="筛选进度"):
                try:
                    result = self._screen_single_stock(code, years, min_yield, screening_date)
                    if result:
                        self.results.append(result)
                except Exception as e:
                    logger.error(f"筛选股票 {code} 时出错: {e}")
                    continue
                    
        # 转换为DataFrame
        if self.results:
            df = pd.DataFrame(self.results)
            # 按四年平均分红率排序
            df = df.sort_values('four_year_rate', ascending=False)
            logger.info(f"筛选完成，找到 {len(df)} 只符合条件的股票")
            return df
        else:
            logger.info("没有找到符合条件的股票")
            return pd.DataFrame()
            
    def _screen_single_stock(self, code: str, years: int, 
                           min_yield: float, screening_date: datetime) -> Optional[Dict]:
        """筛选单只股票"""
        # 需要计算多年的分红率
        yearly_yields = {}
        current_year = screening_date.year
        
        # 获取过去N年的分红率
        for i in range(years):
            year = current_year - i
            from dividend import calculate_static_dividend_yield
            
            # 转换股票代码格式
            bs_code = self.data_source.convert_stock_code(code)
            year_result = calculate_static_dividend_yield(bs_code, year)
            if 'error' not in year_result and year_result.get('annual_static_yield'):
                yearly_yields[str(year)] = year_result['annual_static_yield']
        
        if not yearly_yields:
            return None
            
        # 检查是否满足连续N年的条件
        valid_years = []
        yields = []
        
        for year_str, year_yield in sorted(yearly_yields.items(), reverse=True):
            if year_yield >= min_yield:
                valid_years.append(year_str)
                yields.append(year_yield)
                
        # 检查是否有足够的年份满足条件
        if len(valid_years) < years:
            return None
            
        # 获取当前的综合分红率数据
        yield_data = calculate_comprehensive_dividend_yield(bs_code, screening_date)
        
        # 计算最近4年的平均分红率
        recent_yields = list(yields)[:4]
        four_year_avg = np.mean(recent_yields) if len(recent_yields) >= 4 else 0
        
        # 计算标准差
        std_dev = np.std(yields) if len(yields) > 1 else 0
        
        # 提取动态和静态收益率
        dynamic_yield = 0
        static_yield = 0
        
        if yield_data:
            if yield_data.get('dynamic_yield') and yield_data['dynamic_yield'].get('yield_percentage'):
                dynamic_yield = yield_data['dynamic_yield']['yield_percentage']
            if yield_data.get('static_yield') and yield_data['static_yield'].get('yield_percentage'):
                static_yield = yield_data['static_yield']['yield_percentage']
        
        return {
            'code': code,
            'screening_date': screening_date.strftime('%Y-%m-%d'),
            'dynamic_yield': dynamic_yield,
            'static_yield': static_yield,
            'qualified_years': len(valid_years),
            'avg_yield': np.mean(yields),
            'min_yield': min(yields),
            'max_yield': max(yields),
            'std_dev': std_dev,
            'four_year_rate': four_year_avg,
            'yield_years': ','.join(valid_years),
            'yield_values': ','.join([f"{y:.2f}" for y in yields])
        }
        
    def save_results(self, df: pd.DataFrame, filename: Optional[str] = None):
        """保存筛选结果"""
        if filename is None:
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"dividend_screening_results_{timestamp}.csv"
            
        df.to_csv(filename, index=False, encoding='utf-8-sig')
        logger.info(f"结果已保存到: {filename}")
        
        # 打印摘要
        print("\n筛选结果摘要:")
        print(f"符合条件的股票数: {len(df)}")
        print(f"平均四年分红率: {df['four_year_rate'].mean():.2f}%")
        print(f"最高四年分红率: {df['four_year_rate'].max():.2f}%")
        print("\nTop 10 股票（按四年平均分红率排序）:")
        print(df.head(10)[['code', 'four_year_rate', 'avg_yield', 'qualified_years']])


def main():
    """主函数"""
    import argparse
    
    parser = argparse.ArgumentParser(description='红利股票筛选工具')
    parser.add_argument('--years', type=int, default=5, help='连续分红年数要求')
    parser.add_argument('--min-yield', type=float, default=6.0, help='最低分红率要求(%)')
    parser.add_argument('--excel', type=str, help='股票代码Excel文件路径')
    parser.add_argument('--output', type=str, help='输出文件名')
    
    args = parser.parse_args()
    
    # 创建筛选器
    screener = DividendScreener()
    
    # 执行筛选
    results = screener.screen_stocks(
        years=args.years,
        min_yield=args.min_yield
    )
    
    # 保存结果
    if not results.empty:
        screener.save_results(results, args.output)


if __name__ == "__main__":
    main()