import pandas as pd

def read_stock_codes_to_dict(file_path='分红2025.xlsx'):
    """
    读取Excel文件中的证券代码列并转换为字典
    
    Args:
        file_path: Excel文件路径，默认为'分红2025.xlsx'
    
    Returns:
        dict: 以证券代码为键的字典，值为索引位置
    """
    try:
        # 读取Excel文件
        df = pd.read_excel(file_path)
        
        # 查找证券代码列（可能的列名）
        code_column = None
        possible_names = ['证券代码', '股票代码', '代码', 'code', 'stock_code']
        
        for col in df.columns:
            if any(name in str(col) for name in possible_names):
                code_column = col
                break
        
        if code_column is None:
            # 如果找不到，尝试第一列
            code_column = df.columns[0]
            print(f"未找到证券代码列，使用第一列: {code_column}")
        
        # 创建字典：证券代码作为键，索引作为值
        stock_codes_dict = {}
        for idx, code in enumerate(df[code_column]):
            if pd.notna(code):  # 跳过空值
                # 确保代码为字符串格式
                code_str = str(code).strip()
                stock_codes_dict[code_str] = {
                    'index': idx,
                    'row_number': idx + 1  # Excel行号从1开始
                }
        
        return stock_codes_dict
        
    except Exception as e:
        print(f"读取Excel文件时出错: {e}")
        return {}

# 使用示例
if __name__ == "__main__":
    stock_dict = read_stock_codes_to_dict()
    print(f"共读取 {len(stock_dict)} 个股票代码")
    # 显示前5个
    for i, (code, info) in enumerate(stock_dict.items()):
        if i < 5:
            print(f"代码: {code}, 索引: {info['index']}, Excel行号: {info['row_number']}")
        else:
            break