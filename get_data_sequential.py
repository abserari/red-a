#!/usr/bin/env python3
"""
顺序获取A股数据（稳定版本）
"""

from datetime import datetime, timedelta
from data_acquisition import DataAcquisition
import sys
import time
import argparse

def main():
    parser = argparse.ArgumentParser(description='顺序获取A股数据')
    parser.add_argument('--years', type=int, default=8, help='历史数据年数（默认8年，用于筛选连续5年以上高分红股票）')
    parser.add_argument('--batch-size', type=int, default=10, help='进度显示批次大小（默认10）')
    parser.add_argument('--delay', type=float, default=0.5, help='每只股票之间的延迟秒数（默认0.5）')
    parser.add_argument('--test', action='store_true', help='测试模式，只处理前20只股票')
    parser.add_argument('--force', action='store_true', help='强制更新所有数据（忽略缓存）')
    parser.add_argument('--dividend-days', type=int, default=30, help='分红数据更新周期（默认30天）')
    args = parser.parse_args()
    
    # 初始化
    print("=" * 60)
    print("A股数据获取系统（顺序稳定版）")
    print("=" * 60)
    print(f"开始时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"配置：延迟={args.delay}秒/股，进度批次={args.batch_size}")
    print("-" * 60)
    
    print("\n连接到 MongoDB...")
    da = DataAcquisition()
    
    # 设置时间范围
    end_date = datetime.now().strftime('%Y%m%d')
    start_date = (datetime.now() - timedelta(days=365*args.years)).strftime('%Y%m%d')
    print(f"数据时间范围: {start_date} - {end_date} ({args.years}年)")
    
    # 1. 获取股票列表
    print("\n1. 获取股票列表...")
    stock_list = da.get_all_stock_list()
    all_codes = stock_list['stock_code'].tolist()
    
    # 测试模式只处理前20只
    if args.test:
        all_codes = all_codes[:20]
        print(f"   测试模式：只处理前 {len(all_codes)} 只股票")
    else:
        print(f"   找到 {len(all_codes)} 只股票")
    
    # 2. 顺序获取数据
    total = len(all_codes)
    success_count = 0
    fail_count = 0
    skip_count = 0
    start_time = time.time()
    
    print(f"\n2. 开始顺序获取数据...")
    if args.force:
        print("   强制更新模式：将更新所有数据")
    else:
        print(f"   智能更新模式：跳过完整数据，分红更新周期 {args.dividend_days} 天")
    
    for i, code in enumerate(all_codes):
        try:
            # 进度显示
            if i % args.batch_size == 0 or i == total - 1:
                print(f"\n=== 进度: {i+1}/{total} ({(i+1)/total*100:.1f}%) ===")
            
            # 如果不是强制更新，检查是否需要更新
            need_update = False
            update_reason = ""
            
            if not args.force:
                # 检查历史数据完整性
                missing_ranges = da.get_missing_date_ranges(code, start_date, end_date)
                if missing_ranges:
                    need_update = True
                    update_reason = f"缺失{len(missing_ranges)}段数据"
                else:
                    # 检查分红数据是否需要更新
                    dividend_check = da.dividends.find_one({"stock_code": code}, sort=[("update_time", -1)])
                    if not dividend_check or (datetime.now() - dividend_check.get('update_time', datetime.min)).days >= args.dividend_days:
                        need_update = True
                        update_reason = "分红数据需要更新"
                    else:
                        print(f"  ⏭ {code}: 数据完整且最新，跳过")
                        skip_count += 1
                        continue
            else:
                need_update = True
                update_reason = "强制更新"
            
            # 获取数据
            if need_update:
                print(f"  ⚙ {code}: {update_reason}，开始获取...")
                
                # 获取历史数据
                try:
                    if args.force or missing_ranges:
                        history_df = da.get_stock_history_smart(code, start_date, end_date)
                        if not history_df.empty:
                            print(f"    ✓ 历史数据: 获取 {len(history_df)} 条")
                        else:
                            print(f"    ✗ 历史数据: 无数据")
                except Exception as e:
                    print(f"    ✗ 历史数据错误: {str(e)[:50]}")
                
                # 获取分红数据
                try:
                    dividend_df = da.get_dividend_history(code)
                    if not dividend_df.empty:
                        print(f"    ✓ 分红数据: 获取 {len(dividend_df)} 条")
                    else:
                        print(f"    - 分红数据: 该股票暂无分红")
                except Exception as e:
                    print(f"    ✗ 分红数据错误: {str(e)[:50]}")
                
                success_count += 1
                
                # 延迟以避免请求过快
                time.sleep(args.delay)
                
        except KeyboardInterrupt:
            print("\n\n⚠️  用户中断")
            break
        except Exception as e:
            print(f"  ✗ {code}: 处理失败 - {str(e)[:50]}")
            fail_count += 1
            continue
        
        # 定期显示统计
        if (i + 1) % (args.batch_size * 10) == 0:
            elapsed = time.time() - start_time
            rate = (i + 1) / elapsed
            eta = (total - i - 1) / rate if rate > 0 else 0
            
            print(f"\n--- 统计信息 ---")
            print(f"已处理: {i+1}/{total}")
            print(f"成功: {success_count}, 失败: {fail_count}, 跳过: {skip_count}")
            print(f"速度: {rate:.1f} 股/秒")
            print(f"预计剩余时间: {eta/60:.1f} 分钟")
            
            # 显示数据统计
            stats = da.get_data_statistics()
            print(f"\n数据库统计：")
            print(f"- 历史价格记录: {stats['daily_prices_count']:,}")
            print(f"- 分红记录: {stats['dividends_count']:,}")
            print("-" * 30)
    
    # 3. 最终统计
    total_time = time.time() - start_time
    print("\n\n" + "=" * 60)
    print("✅ 数据获取完成！")
    print("=" * 60)
    
    final_stats = da.get_data_statistics()
    print(f"\n最终数据统计：")
    print(f"- 股票总数: {final_stats['stocks_count']}")
    print(f"- 历史价格记录: {final_stats['daily_prices_count']:,}")
    print(f"- 分红记录: {final_stats['dividends_count']:,}")
    print(f"- 有价格数据的股票: {final_stats['stocks_with_prices']}")
    print(f"- 有分红数据的股票: {final_stats['stocks_with_dividends']}")
    
    print(f"\n处理结果：")
    print(f"- 成功: {success_count}")
    print(f"- 失败: {fail_count}")
    print(f"- 跳过: {skip_count}")
    print(f"- 总耗时: {total_time/60:.1f} 分钟")
    print(f"- 平均速度: {total/total_time:.1f} 股/秒")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️  用户中断，程序已停止")
        sys.exit(0)
    except Exception as e:
        print(f"\n\n❌ 程序错误: {e}")
        sys.exit(1)