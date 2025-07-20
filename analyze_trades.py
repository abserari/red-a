"""
分析红利套利的实际交易统计
"""
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from pymongo import MongoClient
import matplotlib.pyplot as plt
from collections import defaultdict

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['Microsoft YaHei', 'SimHei', 'DejaVu Sans']
plt.rcParams['axes.unicode_minus'] = False


def analyze_dividend_trades(csv_file):
    """分析每笔交易的详细统计"""
    # 连接数据库
    client = MongoClient("mongodb://admin:red-a-2025@localhost:27017/")
    db = client["stock_data"]
    
    # 加载筛选结果
    screening_results = pd.read_csv(csv_file)
    print(f"分析 {len(screening_results)} 条交易记录")
    
    # 收集所有交易的统计信息
    trades = []
    
    for idx, row in screening_results.iterrows():
        code = row['code']
        stock_code = code.split('.')[0]
        screening_date = pd.to_datetime(row['screening_date'])
        
        # 查找除权日
        dividend = db.dividends.find_one({
            'stock_code': stock_code,
            'ex_date': {'$gt': screening_date}
        }, sort=[('ex_date', 1)])
        
        if not dividend:
            continue
            
        ex_date = pd.to_datetime(dividend['ex_date'])
        
        # 获取价格数据
        prices = list(db.daily_prices.find({
            'stock_code': stock_code,
            'date': {
                '$gte': screening_date - timedelta(days=60),
                '$lte': ex_date + timedelta(days=10)
            }
        }).sort('date', 1))
        
        if not prices:
            continue
            
        price_df = pd.DataFrame(prices)
        price_df['date'] = pd.to_datetime(price_df['date'])
        price_df.set_index('date', inplace=True)
        
        # 分析不同买入时机
        timings = [
            ('筛选日', 0),
            ('除权前7天', 7),
            ('除权前14天', 14),
            ('除权前30天', 30)
        ]
        
        for timing_name, days_before in timings:
            if days_before == 0:
                buy_date = screening_date
            else:
                buy_date = ex_date - timedelta(days=days_before)
                if buy_date < screening_date:
                    continue
            
            # 查找买入价格
            buy_price = None
            for i in range(5):  # 允许最多5天的容错
                try_date = buy_date + timedelta(days=i)
                if try_date in price_df.index:
                    buy_price = float(price_df.loc[try_date, 'close'])
                    actual_buy_date = try_date
                    break
            
            if buy_price is None:
                continue
            
            # 查找卖出价格（除权日前3天内的最高价）
            sell_end = ex_date - timedelta(days=1)
            sell_start = ex_date - timedelta(days=3)
            sell_window = price_df[(price_df.index >= sell_start) & (price_df.index <= sell_end)]
            
            if sell_window.empty:
                continue
            
            sell_price = float(sell_window['high'].max())
            sell_date = sell_window['high'].idxmax()
            
            # 计算收益
            return_pct = (sell_price - buy_price) / buy_price * 100
            holding_days = (sell_date - actual_buy_date).days
            
            trades.append({
                'code': code,
                'timing': timing_name,
                'buy_date': actual_buy_date,
                'sell_date': sell_date,
                'buy_price': buy_price,
                'sell_price': sell_price,
                'return_pct': return_pct,
                'holding_days': holding_days,
                'ex_date': ex_date,
                'dividend_yield': row['dynamic_yield']
            })
    
    # 转换为DataFrame
    trades_df = pd.DataFrame(trades)
    
    # 按买入时机分组统计
    print("\n" + "="*80)
    print("红利套利交易统计分析")
    print("="*80)
    
    for timing in ['筛选日', '除权前7天', '除权前14天', '除权前30天']:
        timing_trades = trades_df[trades_df['timing'] == timing]
        
        if len(timing_trades) == 0:
            continue
            
        print(f"\n【{timing}买入】")
        print(f"交易次数: {len(timing_trades)}")
        print(f"平均收益率: {timing_trades['return_pct'].mean():.2f}%")
        print(f"中位数收益率: {timing_trades['return_pct'].median():.2f}%")
        print(f"胜率: {(timing_trades['return_pct'] > 0).sum() / len(timing_trades) * 100:.1f}%")
        print(f"最大收益: {timing_trades['return_pct'].max():.2f}%")
        print(f"最大亏损: {timing_trades['return_pct'].min():.2f}%")
        print(f"平均持有天数: {timing_trades['holding_days'].mean():.1f}天")
        
        # 收益分布
        print("\n收益分布:")
        bins = [-np.inf, -10, -5, 0, 5, 10, 15, 20, np.inf]
        labels = ['<-10%', '-10~-5%', '-5~0%', '0~5%', '5~10%', '10~15%', '15~20%', '>20%']
        timing_trades['return_bin'] = pd.cut(timing_trades['return_pct'], bins=bins, labels=labels)
        distribution = timing_trades['return_bin'].value_counts().sort_index()
        
        for bin_label, count in distribution.items():
            pct = count / len(timing_trades) * 100
            print(f"  {bin_label}: {count}笔 ({pct:.1f}%)")
    
    # 绘制对比图表
    fig, axes = plt.subplots(2, 2, figsize=(15, 10))
    
    # 1. 收益率分布对比
    ax1 = axes[0, 0]
    for timing in ['筛选日', '除权前7天', '除权前14天', '除权前30天']:
        timing_trades = trades_df[trades_df['timing'] == timing]
        if len(timing_trades) > 0:
            ax1.hist(timing_trades['return_pct'], alpha=0.5, label=timing, bins=30)
    ax1.set_xlabel('收益率(%)')
    ax1.set_ylabel('交易次数')
    ax1.set_title('不同买入时机的收益率分布')
    ax1.legend()
    ax1.grid(True, alpha=0.3)
    
    # 2. 平均收益率对比
    ax2 = axes[0, 1]
    timing_stats = trades_df.groupby('timing')['return_pct'].agg(['mean', 'std', 'count'])
    timing_stats['mean'].plot(kind='bar', ax=ax2, yerr=timing_stats['std']/np.sqrt(timing_stats['count']))
    ax2.set_title('不同买入时机的平均收益率')
    ax2.set_ylabel('平均收益率(%)')
    ax2.set_xticklabels(ax2.get_xticklabels(), rotation=45)
    ax2.grid(True, alpha=0.3)
    
    # 3. 胜率对比
    ax3 = axes[1, 0]
    win_rates = trades_df.groupby('timing').apply(lambda x: (x['return_pct'] > 0).sum() / len(x) * 100)
    win_rates.plot(kind='bar', ax=ax3)
    ax3.set_title('不同买入时机的胜率')
    ax3.set_ylabel('胜率(%)')
    ax3.set_xticklabels(ax3.get_xticklabels(), rotation=45)
    ax3.grid(True, alpha=0.3)
    
    # 4. 持有天数对比
    ax4 = axes[1, 1]
    trades_df.boxplot(column='holding_days', by='timing', ax=ax4)
    ax4.set_title('不同买入时机的持有天数分布')
    ax4.set_ylabel('持有天数')
    ax4.set_xlabel('买入时机')
    
    plt.tight_layout()
    plt.savefig('dividend_trade_analysis.png', dpi=300, bbox_inches='tight')
    plt.show()
    
    # 保存详细交易记录
    trades_df.to_csv('dividend_trade_details.csv', index=False, encoding='utf-8-sig')
    print(f"\n详细交易记录已保存到: dividend_trade_details.csv")
    
    return trades_df


if __name__ == "__main__":
    import sys
    import glob
    
    # 获取CSV文件
    if len(sys.argv) > 1:
        csv_file = sys.argv[1]
    else:
        csv_files = glob.glob("dividend_screening_results_*.csv")
        if csv_files:
            csv_file = max(csv_files)
        else:
            print("请提供筛选结果CSV文件路径")
            sys.exit(1)
            
    print(f"使用筛选结果文件: {csv_file}")
    
    # 运行分析
    trades_df = analyze_dividend_trades(csv_file)