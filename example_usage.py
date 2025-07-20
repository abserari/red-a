#!/usr/bin/env python3
"""
示例：如何导入和使用 dividend.py 中的函数
"""

# 导入所需的函数
from dividend import (
    calculate_dynamic_dividend_yield,
    calculate_static_dividend_yield,
    calculate_comprehensive_dividend_yield,
    test_dividend_yield_calculation
)

# 使用导入的函数
if __name__ == "__main__":
    # 使用新的动态股息率函数
    print("="*60)
    print("使用 calculate_dynamic_dividend_yield 函数")
    print("="*60)
    
    dynamic_result = calculate_dynamic_dividend_yield("sh.600519", "2024-07-01")
    if 'error' not in dynamic_result:
        print(f"股票代码: sh.600519")
        print(f"动态股息率: {dynamic_result['yield_percentage']:.2f}%")
        print(f"12个月分红总额: {dynamic_result['total_dividend_12m']:.4f}")
        print(f"当前股价: {dynamic_result['stock_price']:.2f}")
        print(f"分红次数: {dynamic_result['dividend_count']}")
        
        if dynamic_result['dividend_details']:
            print("分红明细:")
            for div in dynamic_result['dividend_details']:
                print(f"  - {div['date'].strftime('%Y-%m-%d')}: {div['amount']:.4f}元/股")
    else:
        print(f"错误: {dynamic_result['error']}")
    
    # 测试静态股息率
    print("\n" + "="*60)
    print("使用 calculate_static_dividend_yield 函数")
    print("="*60)
    
    static_result = calculate_static_dividend_yield("sh.600519", 2024)
    if 'error' not in static_result:
        print(f"股票代码: sh.600519")
        print(f"年度静态股息率: {static_result['annual_static_yield']:.2f}%")
        print(f"年度总分红: {static_result['total_dividend']:.4f}")
        print(f"基准股价: {static_result['base_price']:.2f}")
    else:
        print(f"错误: {static_result['error']}")
    
    # 测试综合股息率
    print("\n" + "="*60)
    print("使用 calculate_comprehensive_dividend_yield 函数")
    print("="*60)
    
    comp_result = calculate_comprehensive_dividend_yield("sh.603565", "2024-07-01")
    print(f"股票代码: {comp_result['code']}")
    print(f"检查日期: {comp_result['check_date']}")
    
    if comp_result['dynamic_yield']:
        print(f"\n动态股息率: {comp_result['dynamic_yield']['yield_percentage']:.2f}%")
        print(f"  - 12个月分红: {comp_result['dynamic_yield']['total_dividend_12m']:.4f}")
        print(f"  - 当前股价: {comp_result['dynamic_yield']['stock_price']:.2f}")
    
    if comp_result['static_yield']:
        print(f"\n静态股息率: {comp_result['static_yield']['yield_percentage']:.2f}%")
        print(f"  - 年度分红: {comp_result['static_yield']['total_dividend']:.4f}")
        print(f"  - 基准股价: {comp_result['static_yield']['base_price']:.2f}")