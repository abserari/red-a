# 优化后的数据获取流程

## 核心原则：MongoDB 中已有的数据直接跳过

### 1. 主流程 (get_data_sequential.py)

```
对每只股票:
    1. 调用 get_missing_date_ranges() 检查缺失数据
    2. 如果没有缺失 → 跳过，不调用 API
    3. 如果有缺失 → 调用 get_stock_history_smart() 只获取缺失部分
```

### 2. 智能获取 (get_stock_history_smart)

```
1. 调用 get_missing_date_ranges() 获取缺失数据段
2. 如果没有缺失:
   - 直接从 MongoDB 返回数据
   - 不调用任何 API
3. 如果有缺失:
   - 对每个缺失段调用 get_stock_history()
   - 只获取缺失的日期范围
```

### 3. 缺失检测 (get_missing_date_ranges)

```
1. 查询 MongoDB 中该股票的所有日期
2. 与请求的日期范围对比
3. 返回缺失的日期段列表
   - 空列表 = 数据完整
   - 非空列表 = 需要获取的日期段
```

### 4. 数据插入优化

```
获取到新数据后:
1. 先查询哪些日期的数据已存在
2. 只插入不存在的新数据
3. 使用 insert_many 批量插入（而非逐条 update）
```

## 性能提升

### 场景1：首次运行
- 所有数据都缺失，需要从 API 获取
- 但使用批量插入，性能优于逐条更新

### 场景2：日常更新
- 大部分股票数据已完整，直接跳过
- 只获取真正缺失的数据（如最新几天）
- 速度提升 10-100 倍

### 场景3：恢复中断
- 自动检测已获取的数据
- 只补充缺失部分
- 支持断点续传

## 使用示例

```bash
# 首次运行
uv run get_data_sequential.py

# 日常更新（智能跳过已有数据）
uv run get_data_sequential.py

# 测试优化效果
uv run test_data_optimization.py
```

## 关键优化点

1. **早期检测**：在调用 API 前就检查数据完整性
2. **精确获取**：只请求缺失的日期段，不重复获取
3. **批量操作**：使用 insert_many 代替逐条 update
4. **智能跳过**：完整数据的股票完全跳过，不产生任何 API 调用或数据库写入