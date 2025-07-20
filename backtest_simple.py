"""
简化版红利套利策略回测
直接计算收益率分布，不依赖bt框架
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pymongo import MongoClient
import logging
import matplotlib.pyplot as plt
import seaborn as sns
from tqdm import tqdm
from collections import defaultdict

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 设置绘图风格
sns.set_style("whitegrid")
plt.rcParams['figure.figsize'] = (12, 8)
plt.rcParams['font.size'] = 10
# 设置中文字体为微软雅黑
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False

class DividendBacktest:
    """红利套利策略回测"""
    
    def __init__(self, csv_file, mongo_uri="mongodb://admin:red-a-2025@localhost:27017/"):
        """初始化"""
        self.csv_file = csv_file
        self.client = MongoClient(mongo_uri)
        self.db = self.client["stock_data"]
        
        # 加载筛选结果
        self.screening_results = pd.read_csv(csv_file)
        logger.info(f"加载了 {len(self.screening_results)} 条筛选结果")
        
        # 存储回测结果
        self.backtest_results = []
        
    def get_trading_day_price(self, code, target_date, direction='forward'):
        """获取最近交易日的价格
        direction: 'forward'向后找, 'backward'向前找
        """
        if isinstance(target_date, str):
            target_date = pd.to_datetime(target_date)
            
        # 转换股票代码格式：从 600036.SH 到 600036
        stock_code = code.split('.')[0] if '.' in code else code
            
        # 查询最近的交易日数据
        if direction == 'forward':
            # 查找target_date当天或之后的第一个交易日
            price_doc = self.db.daily_prices.find_one(
                {'stock_code': stock_code, 'date': {'$gte': target_date}},
                sort=[('date', 1)]
            )
        else:
            # 查找target_date当天或之前的第一个交易日
            price_doc = self.db.daily_prices.find_one(
                {'stock_code': stock_code, 'date': {'$lte': target_date}},
                sort=[('date', -1)]
            )
            
        if price_doc:
            return float(price_doc['close']), pd.to_datetime(price_doc['date'])
        return None, None
        
    def get_max_price_before_exdate(self, code, ex_date, days=3):
        """获取除权日前N个交易日内的最高价"""
        if isinstance(ex_date, str):
            ex_date = pd.to_datetime(ex_date)
            
        # 转换股票代码格式
        stock_code = code.split('.')[0] if '.' in code else code
            
        # 查询除权日前的交易数据
        end_date = ex_date
        start_date = ex_date - timedelta(days=days+5)  # 多查几天确保覆盖N个交易日
        
        prices = list(self.db.daily_prices.find({
            'stock_code': stock_code,
            'date': {'$gte': start_date, '$lt': end_date}
        }).sort('date', -1).limit(days))
        
        if prices:
            # 获取最高价
            max_price = max(float(p['high']) for p in prices)
            # 获取最高价出现的日期
            for p in prices:
                if float(p['high']) == max_price:
                    max_price_date = pd.to_datetime(p['date'])
                    break
            return max_price, max_price_date
        return None, None
        
    def get_next_exdividend_date(self, code, after_date):
        """获取下一个除权除息日"""
        if isinstance(after_date, str):
            after_date = pd.to_datetime(after_date)
            
        # 转换股票代码格式
        stock_code = code.split('.')[0] if '.' in code else code
            
        dividend = self.db.dividends.find_one({
            'stock_code': stock_code,
            'ex_date': {'$gt': after_date}
        }, sort=[('ex_date', 1)])
        
        if dividend and dividend.get('ex_date'):
            return pd.to_datetime(dividend['ex_date'])
        return None
        
    def calculate_single_trade(self, code, screening_date, buy_timing, days_before_ex):
        """计算单次交易的收益"""
        # 获取除权日
        ex_date = self.get_next_exdividend_date(code, screening_date)
        if not ex_date:
            return None
            
        # 计算买入日期
        if buy_timing == '筛选日当天':
            target_buy_date = screening_date
        else:
            target_buy_date = ex_date - timedelta(days=days_before_ex)
            # 确保买入日期不早于筛选日
            if target_buy_date < screening_date:
                return None
                
        # 获取实际买入价格和日期
        buy_price, actual_buy_date = self.get_trading_day_price(code, target_buy_date, 'forward')
        if not buy_price:
            return None
            
        # 获取卖出价格（除权日前3个交易日的最高价）
        sell_price, sell_date = self.get_max_price_before_exdate(code, ex_date, days=3)
        if not sell_price:
            return None
            
        # 确保卖出日期在买入日期之后
        if sell_date <= actual_buy_date:
            return None
            
        # 计算收益
        return_rate = (sell_price - buy_price) / buy_price * 100
        holding_days = (sell_date - actual_buy_date).days
        
        return {
            'code': code,
            'screening_date': screening_date,
            'buy_timing': buy_timing,
            'target_buy_date': target_buy_date,
            'actual_buy_date': actual_buy_date,
            'buy_price': buy_price,
            'ex_date': ex_date,
            'sell_date': sell_date,
            'sell_price': sell_price,
            'return_rate': return_rate,
            'holding_days': holding_days
        }
        
    def run_backtest(self):
        """运行回测"""
        # 定义买入时机
        buy_timings = [
            ('筛选日当天', 0),
            ('除权日前1周', 7),
            ('除权日前2周', 14),
            ('除权日前1月', 30),
            ('除权日前2月', 60)
        ]
        
        logger.info("开始回测...")
        
        # 对每条筛选结果进行回测
        for idx, row in tqdm(self.screening_results.iterrows(), 
                            total=len(self.screening_results),
                            desc="回测进度"):
            code = row['code']
            screening_date = pd.to_datetime(row['screening_date'])
            
            # 测试每种买入时机
            for timing_name, days_before in buy_timings:
                try:
                    result = self.calculate_single_trade(
                        code, screening_date, timing_name, days_before
                    )
                    if result:
                        # 添加额外信息
                        result['dynamic_yield'] = row.get('dynamic_yield', 0)
                        result['four_year_rate'] = row.get('four_year_rate', 0)
                        self.backtest_results.append(result)
                except Exception as e:
                    logger.error(f"回测 {code} {timing_name} 时出错: {e}")
                    continue
                    
        logger.info(f"回测完成，共产生 {len(self.backtest_results)} 条交易记录")
        
        # 转换为DataFrame
        self.results_df = pd.DataFrame(self.backtest_results)
        return self.results_df
        
    def analyze_results(self):
        """分析回测结果"""
        if self.results_df.empty:
            print("没有回测结果")
            return None
            
        print("\n" + "="*80)
        print("红利套利策略回测分析报告")
        print("="*80)
        
        # 基本统计
        print(f"\n基本信息:")
        print(f"- 回测股票数: {self.results_df['code'].nunique()}")
        print(f"- 总交易次数: {len(self.results_df)}")
        print(f"- 平均持有天数: {self.results_df['holding_days'].mean():.1f}")
        
        # 按买入时机分组统计
        timing_stats = self.results_df.groupby('buy_timing').agg({
            'return_rate': ['count', 'mean', 'std', 'min', 'max', lambda x: (x > 0).sum() / len(x) * 100],
            'holding_days': 'mean'
        }).round(2)
        timing_stats.columns = ['交易次数', '平均收益率', '收益标准差', '最小收益率', '最大收益率', '胜率(%)', '平均持有天数']
        
        print("\n各买入时机策略表现:")
        print(timing_stats)
        
        # 收益率分段统计
        print("\n收益率分布统计:")
        for timing in self.results_df['buy_timing'].unique():
            timing_data = self.results_df[self.results_df['buy_timing'] == timing]['return_rate']
            print(f"\n{timing}:")
            print(f"  < -5%: {(timing_data < -5).sum() / len(timing_data) * 100:.1f}%")
            print(f"  -5% ~ 0%: {((timing_data >= -5) & (timing_data < 0)).sum() / len(timing_data) * 100:.1f}%")
            print(f"  0% ~ 5%: {((timing_data >= 0) & (timing_data < 5)).sum() / len(timing_data) * 100:.1f}%")
            print(f"  5% ~ 10%: {((timing_data >= 5) & (timing_data < 10)).sum() / len(timing_data) * 100:.1f}%")
            print(f"  > 10%: {(timing_data >= 10).sum() / len(timing_data) * 100:.1f}%")
            
        # 年度分析
        self.results_df['year'] = self.results_df['screening_date'].dt.year
        yearly_stats = self.results_df.groupby(['year', 'buy_timing'])['return_rate'].agg(['mean', 'count'])
        print("\n年度收益统计:")
        print(yearly_stats)
        
        return timing_stats
        
    def plot_results(self, save_path=None):
        """绘制回测结果"""
        if self.results_df.empty:
            return
            
        # 创建子图
        fig, axes = plt.subplots(2, 3, figsize=(18, 12))
        
        # 1. 各策略收益率箱线图
        ax1 = axes[0, 0]
        self.results_df.boxplot(column='return_rate', by='buy_timing', ax=ax1)
        ax1.set_title('收益率分布 - 箱线图')
        ax1.set_xlabel('买入时机')
        ax1.set_ylabel('收益率 (%)')
        ax1.tick_params(axis='x', rotation=45)
        
        # 2. 收益率分布直方图
        ax2 = axes[0, 1]
        for timing in self.results_df['buy_timing'].unique():
            data = self.results_df[self.results_df['buy_timing'] == timing]['return_rate']
            ax2.hist(data, alpha=0.5, label=timing, bins=30, density=True)
        ax2.set_title('收益率分布 - 直方图')
        ax2.set_xlabel('收益率 (%)')
        ax2.set_ylabel('密度')
        ax2.legend(loc='upper right', fontsize=8)
        ax2.axvline(x=0, color='red', linestyle='--', alpha=0.5)
        
        # 3. 平均收益率对比
        ax3 = axes[0, 2]
        timing_mean = self.results_df.groupby('buy_timing')['return_rate'].mean().sort_values(ascending=False)
        timing_mean.plot(kind='bar', ax=ax3, color='skyblue')
        ax3.set_title('各策略平均收益率')
        ax3.set_xlabel('买入时机')
        ax3.set_ylabel('平均收益率 (%)')
        ax3.tick_params(axis='x', rotation=45)
        ax3.axhline(y=0, color='red', linestyle='--', alpha=0.5)
        
        # 4. 胜率对比
        ax4 = axes[1, 0]
        win_rate = self.results_df.groupby('buy_timing')['return_rate'].apply(lambda x: (x > 0).sum() / len(x) * 100)
        win_rate.sort_values(ascending=False).plot(kind='bar', ax=ax4, color='lightgreen')
        ax4.set_title('各策略胜率')
        ax4.set_xlabel('买入时机')
        ax4.set_ylabel('胜率 (%)')
        ax4.tick_params(axis='x', rotation=45)
        ax4.axhline(y=50, color='red', linestyle='--', alpha=0.5)
        
        # 5. 持有天数与收益率关系
        ax5 = axes[1, 1]
        for timing in self.results_df['buy_timing'].unique():
            data = self.results_df[self.results_df['buy_timing'] == timing]
            ax5.scatter(data['holding_days'], data['return_rate'], alpha=0.5, s=20, label=timing)
        ax5.set_title('持有天数与收益率关系')
        ax5.set_xlabel('持有天数')
        ax5.set_ylabel('收益率 (%)')
        ax5.legend(loc='upper right', fontsize=8)
        ax5.axhline(y=0, color='red', linestyle='--', alpha=0.5)
        
        # 6. 累积收益曲线
        ax6 = axes[1, 2]
        for timing in self.results_df['buy_timing'].unique():
            data = self.results_df[self.results_df['buy_timing'] == timing].copy()
            data = data.sort_values('actual_buy_date')
            data['cum_return'] = (1 + data['return_rate']/100).cumprod()
            ax6.plot(range(len(data)), data['cum_return'], label=timing, linewidth=2)
        ax6.set_title('累积收益曲线')
        ax6.set_xlabel('交易序号')
        ax6.set_ylabel('累积收益')
        ax6.legend(loc='upper left', fontsize=8)
        ax6.axhline(y=1, color='red', linestyle='--', alpha=0.5)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
            print(f"\n图表已保存到: {save_path}")
        else:
            plt.show()
            
        # 额外绘制收益率分布详细图
        self.plot_return_distribution(save_path.replace('.png', '_distribution.png') if save_path else None)
        
    def plot_return_distribution(self, save_path=None):
        """绘制详细的收益率分布图"""
        fig, ax = plt.subplots(1, 1, figsize=(12, 8))
        
        # 为每个策略绘制收益率分布
        timings = self.results_df['buy_timing'].unique()
        colors = plt.cm.Set3(np.linspace(0, 1, len(timings)))
        
        y_offset = 0
        for idx, timing in enumerate(timings):
            data = self.results_df[self.results_df['buy_timing'] == timing]['return_rate'].values
            
            # 计算各区间的比例
            ranges = [(-np.inf, -10), (-10, -5), (-5, 0), (0, 5), (5, 10), (10, 15), (15, np.inf)]
            range_labels = ['< -10%', '-10~-5%', '-5~0%', '0~5%', '5~10%', '10~15%', '> 15%']
            
            percentages = []
            for low, high in ranges:
                pct = ((data > low) & (data <= high)).sum() / len(data) * 100
                percentages.append(pct)
                
            # 绘制水平条形图
            x_pos = 0
            for i, (pct, label) in enumerate(zip(percentages, range_labels)):
                color_intensity = 0.3 + 0.1 * i  # 渐变色
                ax.barh(y_offset, pct, left=x_pos, height=0.8, 
                       color=colors[idx], alpha=color_intensity)
                if pct > 3:  # 只在较大的区间显示百分比
                    ax.text(x_pos + pct/2, y_offset, f'{pct:.1f}%', 
                           ha='center', va='center', fontsize=9)
                x_pos += pct
                
            y_offset += 1
            
        # 设置图表
        ax.set_yticks(range(len(timings)))
        ax.set_yticklabels(timings)
        ax.set_xlabel('收益率分布 (%)')
        ax.set_title('各策略收益率详细分布', fontsize=14)
        ax.set_xlim(0, 100)
        
        # 添加图例
        legend_elements = []
        for i, label in enumerate(range_labels):
            legend_elements.append(plt.Rectangle((0, 0), 1, 1, 
                                               fc='gray', 
                                               alpha=0.3 + 0.1 * i))
        ax.legend(legend_elements, range_labels, loc='upper right', fontsize=9)
        
        plt.tight_layout()
        
        if save_path:
            plt.savefig(save_path, dpi=300, bbox_inches='tight')
        else:
            plt.show()


# 主程序
if __name__ == "__main__":
    import sys
    
    # 检查MongoDB连接
    try:
        client = MongoClient("mongodb://admin:red-a-2025@localhost:27017/", serverSelectionTimeoutMS=5000)
        client.server_info()
    except Exception as e:
        print(f"MongoDB连接失败: {e}")
        print("请先启动MongoDB:")
        print("docker compose up -d")
        sys.exit(1)
    
    # 获取CSV文件
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
    else:
        import glob
        csv_files = glob.glob("dividend_screening_results_*.csv")
        if csv_files:
            csv_file = max(csv_files)
        else:
            print("请提供筛选结果CSV文件路径")
            sys.exit(1)
            
    print(f"使用筛选结果文件: {csv_file}")
    
    # 创建回测器
    backtester = DividendBacktest(csv_file)
    
    # 运行回测
    results_df = backtester.run_backtest()
    
    if not results_df.empty:
        # 分析结果
        timing_stats = backtester.analyze_results()
        
        # 保存详细结果
        output_file = csv_file.replace('screening_results', 'backtest_results')
        results_df.to_csv(output_file, index=False, encoding='utf-8-sig')
        print(f"\n详细回测结果已保存到: {output_file}")
        
        # 保存统计摘要
        if timing_stats is not None:
            summary_file = csv_file.replace('screening_results', 'backtest_summary')
            timing_stats.to_csv(summary_file, encoding='utf-8-sig')
            print(f"统计摘要已保存到: {summary_file}")
        
        # 绘制图表
        plot_file = output_file.replace('.csv', '.png')
        backtester.plot_results(plot_file)
    else:
        print("没有生成回测结果")