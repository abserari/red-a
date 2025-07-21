#!/usr/bin/env python3
"""
红利套利策略主程序
完整的筛选和回测流程
"""
import argparse
import logging
from datetime import datetime
import sys

from screener import DividendScreener
from backtest import DividendBacktest

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """主程序入口"""
    parser = argparse.ArgumentParser(description='红利套利策略系统')
    parser.add_argument('--mode', choices=['screen', 'backtest', 'full'], 
                       default='full', help='运行模式')
    parser.add_argument('--years', type=int, default=5, 
                       help='筛选条件：连续分红年数')
    parser.add_argument('--min-yield', type=float, default=6.0, 
                       help='筛选条件：最低分红率(%)')
    parser.add_argument('--csv', type=str, 
                       help='回测模式：使用的筛选结果CSV文件')
    parser.add_argument('--excel', type=str, default='分红2025.xlsx',
                       help='股票代码Excel文件')
    
    args = parser.parse_args()
    
    try:
        if args.mode == 'screen' or args.mode == 'full':
            # 执行筛选
            logger.info("开始执行股票筛选...")
            screener = DividendScreener()
            results = screener.screen_stocks(
                years=args.years,
                min_yield=args.min_yield
            )
            
            if results.empty:
                logger.warning("没有找到符合条件的股票")
                return
                
            # 保存筛选结果
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            screening_file = f"dividend_screening_results_{timestamp}.csv"
            screener.save_results(results, screening_file)
            
            if args.mode == 'screen':
                return
                
            # 继续执行回测
            csv_file = screening_file
        else:
            # 只执行回测
            csv_file = args.csv
            if not csv_file:
                # 查找最新的筛选结果文件
                import glob
                csv_files = glob.glob("dividend_screening_results_*.csv")
                if csv_files:
                    csv_file = max(csv_files)
                else:
                    logger.error("请提供筛选结果CSV文件")
                    return
                    
        # 执行回测
        logger.info(f"开始执行回测，使用文件: {csv_file}")
        with DividendBacktest(csv_file) as backtester:
            results_df = backtester.run_backtest()
            
            if not results_df.empty:
                # 分析结果
                timing_stats = backtester.analyze_results()
                
                # 保存结果
                output_file = csv_file.replace('screening_results', 'backtest_results')
                results_df.to_csv(output_file, index=False, encoding='utf-8-sig')
                logger.info(f"详细回测结果已保存到: {output_file}")
                
                if timing_stats is not None:
                    summary_file = csv_file.replace('screening_results', 'backtest_summary')
                    timing_stats.to_csv(summary_file, encoding='utf-8-sig')
                    logger.info(f"统计摘要已保存到: {summary_file}")
                
                # 绘制图表
                plot_file = output_file.replace('.csv', '.png')
                backtester.plot_results(plot_file)
            else:
                logger.warning("没有生成回测结果")
                
    except Exception as e:
        logger.error(f"程序执行出错: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()