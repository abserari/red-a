"""
使用bt框架的简化红利套利回测
"""
import bt
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pymongo import MongoClient
import logging
import matplotlib.pyplot as plt
from tqdm import tqdm

# 设置日志
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


def prepare_data(csv_file):
    """准备回测数据"""
    # 连接数据库
    client = MongoClient("mongodb://admin:red-a-2025@localhost:27017/")
    db = client["stock_data"]
    
    # 加载筛选结果
    screening_results = pd.read_csv(csv_file)
    logger.info(f"加载了 {len(screening_results)} 条筛选结果")
    
    # 获取唯一股票代码
    unique_codes = screening_results['code'].unique()
    
    # 加载价格数据
    logger.info("加载价格数据...")
    price_data = {}
    
    for code in tqdm(unique_codes[:30], desc="加载价格"):  # 限制股票数量以加快速度
        stock_code = code.split('.')[0] if '.' in code else code
        
        prices = list(db.daily_prices.find({
            'stock_code': stock_code,
            'date': {'$gte': datetime(2023, 1, 1), '$lte': datetime(2025, 1, 1)}
        }).sort('date', 1))
        
        if prices:
            df = pd.DataFrame(prices)
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)
            price_data[code] = df['close'].astype(float)
            
    # 合并价格数据
    prices_df = pd.DataFrame(price_data)
    prices_df = prices_df.ffill().dropna()
    
    logger.info(f"价格数据: {prices_df.shape[0]} 天, {prices_df.shape[1]} 只股票")
    
    return prices_df, screening_results, db


def create_target_weights(prices_df, screening_results, db, timing_days=7):
    """创建目标权重时间序列"""
    weights = pd.DataFrame(0.0, index=prices_df.index, columns=prices_df.columns)
    
    # 记录每个日期的活跃股票
    active_stocks = {}
    
    for idx, row in screening_results.iterrows():
        code = row['code']
        if code not in prices_df.columns:
            continue
            
        screening_date = pd.to_datetime(row['screening_date'])
        stock_code = code.split('.')[0]
        
        # 查找除权日
        dividend = db.dividends.find_one({
            'stock_code': stock_code,
            'ex_date': {'$gt': screening_date}
        }, sort=[('ex_date', 1)])
        
        if not dividend:
            continue
            
        ex_date = pd.to_datetime(dividend['ex_date'])
        
        # 计算买入和卖出日期
        if timing_days == 0:  # 筛选日买入
            buy_date = screening_date
        else:
            buy_date = ex_date - timedelta(days=timing_days)
            if buy_date < screening_date:
                continue
                
        sell_date = ex_date - timedelta(days=1)
        
        # 标记持有期间
        mask = (prices_df.index >= buy_date) & (prices_df.index <= sell_date)
        for date in prices_df.index[mask]:
            if date not in active_stocks:
                active_stocks[date] = []
            active_stocks[date].append(code)
            
    # 计算每天的权重
    for date, stocks in active_stocks.items():
        if stocks:
            weight = 1.0 / len(stocks)
            for stock in stocks:
                weights.loc[date, stock] = weight
                
    return weights


def run_bt_backtest(csv_file):
    """运行bt回测"""
    # 准备数据
    prices_df, screening_results, db = prepare_data(csv_file)
    
    # 创建不同买入时机的权重
    timing_configs = [
        ('筛选日当天', 0),
        ('除权日前1周', 7),
        ('除权日前2周', 14),
        ('除权日前1月', 30)
    ]
    
    # 创建所有策略的回测
    backtests = []
    
    for name, days in timing_configs:
        logger.info(f"创建策略: {name}")
        
        # 创建权重
        weights = create_target_weights(prices_df, screening_results, db, days)
        
        # 创建策略
        strategy = bt.Strategy(
            name,
            [bt.algos.WeighTarget(weights),
             bt.algos.Rebalance()]
        )
        
        # 创建回测
        backtest = bt.Backtest(strategy, prices_df)
        backtests.append(backtest)
        
    # 添加基准
    benchmark = bt.Strategy(
        '等权重买入持有',
        [bt.algos.RunOnce(),
         bt.algos.SelectAll(),
         bt.algos.WeighEqually(),
         bt.algos.Rebalance()]
    )
    benchmark_test = bt.Backtest(benchmark, prices_df)
    backtests.append(benchmark_test)
    
    # 一次性运行所有回测
    results = bt.run(*backtests)
    
    return results


def analyze_results(results):
    """分析回测结果"""
    print("\n" + "="*80)
    print("红利套利策略回测结果（bt框架）")
    print("="*80)
    
    # 创建结果表格
    summary_data = []
    
    for name in results.keys():
        stats = results[name].stats
        # 打印第一个策略的所有统计信息以了解结构
        if len(summary_data) == 0:
            print(f"\n可用的统计指标: {list(stats.index)}")
        
        # 计算实际交易时长
        start_date = stats.loc['start']
        end_date = stats.loc['end']
        days = (end_date - start_date).days
        years = days / 365.25
        
        summary_data.append({
            '策略': name,
            '总收益率(%)': f"{stats.loc['total_return'] * 100:.2f}",
            '年化收益率(%)': f"{stats.loc['cagr'] * 100:.2f}",
            '实际时长(天)': f"{days}",
            '夏普比率': f"{stats.loc['daily_sharpe']:.2f}" if 'daily_sharpe' in stats else 'N/A',
            '最大回撤(%)': f"{stats.loc['max_drawdown'] * 100:.2f}",
            '月度夏普': f"{stats.loc['monthly_sharpe']:.2f}" if 'monthly_sharpe' in stats else 'N/A'
        })
        
    summary_df = pd.DataFrame(summary_data)
    print("\n策略对比:")
    print(summary_df.to_string(index=False))
    
    # 绘制图表
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    
    # 1. 累计收益曲线
    ax1 = axes[0, 0]
    results.plot(ax=ax1, title='策略累计收益对比')
    ax1.set_ylabel('累计收益')
    ax1.legend(loc='upper left')
    ax1.grid(True, alpha=0.3)
    
    # 2. 提取并绘制回撤
    ax2 = axes[0, 1]
    for name in results.keys():
        drawdown = results[name].drawdown
        drawdown.plot(ax=ax2, label=name)
    ax2.set_title('策略回撤曲线')
    ax2.set_ylabel('回撤(%)')
    ax2.legend()
    ax2.grid(True, alpha=0.3)
    
    # 3. 年化收益对比
    ax3 = axes[1, 0]
    returns_data = []
    for name in results.keys():
        cagr = results[name].stats.loc['cagr'] * 100
        returns_data.append((name, cagr))
    returns_df = pd.DataFrame(returns_data, columns=['策略', '年化收益率'])
    returns_df.plot(x='策略', y='年化收益率', kind='bar', ax=ax3, legend=False)
    ax3.set_title('年化收益率对比')
    ax3.set_ylabel('年化收益率(%)')
    ax3.tick_params(axis='x', rotation=45)
    ax3.grid(True, alpha=0.3)
    
    # 4. 夏普比率对比
    ax4 = axes[1, 1]
    sharpe_data = []
    for name in results.keys():
        sharpe = results[name].stats.loc['daily_sharpe']
        sharpe_data.append((name, sharpe))
    sharpe_df = pd.DataFrame(sharpe_data, columns=['策略', '夏普比率'])
    sharpe_df.plot(x='策略', y='夏普比率', kind='bar', ax=ax4, legend=False)
    ax4.set_title('夏普比率对比')
    ax4.set_ylabel('夏普比率')
    ax4.tick_params(axis='x', rotation=45)
    ax4.grid(True, alpha=0.3)
    
    plt.tight_layout()
    plt.savefig('dividend_bt_backtest_results.png', dpi=300, bbox_inches='tight')
    plt.show()
    
    # 显示详细统计
    print("\n详细统计:")
    results.display()
    
    return summary_df


if __name__ == "__main__":
    import sys
    
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
    
    try:
        # 运行回测
        results = run_bt_backtest(csv_file)
        
        # 分析结果
        summary = analyze_results(results)
        
        # 保存结果
        summary.to_csv('dividend_bt_backtest_summary.csv', index=False, encoding='utf-8-sig')
        print(f"\n结果已保存到: dividend_bt_backtest_summary.csv")
        
    except Exception as e:
        logger.error(f"回测失败: {e}", exc_info=True)