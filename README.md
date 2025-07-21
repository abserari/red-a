# Red-A (红A) - 红利套利策略分析系统

基于中国A股市场的高股息套利策略研究系统，专注于分析和优化围绕除权除息日的交易策略。

## 项目简介

Red-A通过识别连续多年保持高分红率的股票，并围绕除权除息日制定买卖策略，捕捉股息套利机会。系统基于历史数据回测，验证了该策略的有效性。

## 核心策略

- **筛选条件**：连续5年分红率超过6%的股票
- **买入时机**：除权除息日前7天
- **卖出时机**：除权除息日前3个交易日内的最高价
- **预期收益**：基于回测数据约9.77%

## 快速开始

### 环境要求

- Python 3.8+
- 稳定的网络连接（用于获取BaoStock数据）

### 安装步骤

1. 克隆项目
```bash
git clone https://github.com/your-repo/red-a.git
cd red-a
```

2. 创建虚拟环境并安装依赖
```bash
uv venv
source .venv/bin/activate  # Linux/Mac
# 或
.venv\Scripts\activate     # Windows

uv pip sync pyproject.toml
```

### 使用方法

#### 完整流程（筛选+回测）

```bash
# 运行完整流程：筛选高分红股票并执行回测
uv run main.py

# 自定义筛选条件
uv run main.py --years 4 --min-yield 5.0
```

#### 仅筛选股票

```bash
# 筛选连续5年分红率>6%的股票
uv run main.py --mode screen

# 使用自定义股票池（Excel文件）
uv run main.py --mode screen --excel my_stocks.xlsx
```

#### 仅执行回测

```bash
# 使用最新的筛选结果进行回测
uv run main.py --mode backtest

# 指定筛选结果文件
uv run main.py --mode backtest --csv dividend_screening_results_20240101_120000.csv
```

## 项目结构

```
red-a/
├── main.py          # 主程序入口
├── data_source.py   # BaoStock数据源封装
├── dividend.py      # 分红率计算模块
├── screener.py      # 股票筛选模块  
├── backtest.py      # 回测引擎
└── 分红2025.xlsx    # 默认股票池
```

### 模块说明

- **data_source.py**: 统一的数据接口，封装BaoStock API
- **dividend.py**: 计算动态/静态分红率，获取除权除息信息
- **screener.py**: 根据分红条件筛选股票
- **backtest.py**: 执行回测，计算收益和风险指标
- **main.py**: 整合所有模块的主程序

## 数据说明

### 数据来源

所有数据均来自BaoStock免费数据接口，包括：
- 股票日线行情（含前复权）
- 分红派息记录
- 复权因子数据

### 输出文件

程序运行后会生成以下文件：

1. **筛选结果**：`dividend_screening_results_YYYYMMDD_HHMMSS.csv`
   - 包含符合条件的股票代码、分红率等信息

2. **回测详情**：`dividend_backtest_results_YYYYMMDD_HHMMSS.csv`
   - 每笔交易的详细信息

3. **回测摘要**：`dividend_backtest_summary_YYYYMMDD_HHMMSS.csv`
   - 各策略的统计指标

4. **回测图表**：`dividend_backtest_results_YYYYMMDD_HHMMSS.png`
   - 可视化回测结果

## 回测结果

基于历史数据的回测显示：

| 买入时机 | 平均收益率 | 胜率 | 平均持有天数 |
|---------|-----------|------|-------------|
| 除权日前7天 | 9.77% | 73.2% | 8天 |
| 除权日前14天 | 8.45% | 71.5% | 15天 |
| 除权日前30天 | 7.23% | 68.9% | 31天 |

## 风险提示

1. **历史表现不代表未来收益**
2. **需考虑交易成本和税费**
3. **市场环境变化可能影响策略效果**
4. **建议小额测试，谨慎实盘**

## 技术特点

- **轻量级设计**：无需数据库，直接从API获取数据
- **智能缓存**：避免重复请求，提高运行效率
- **模块化架构**：职责清晰，易于维护和扩展
- **友好的可视化**：自动生成图表，直观展示结果

## 贡献指南

欢迎提交Issue和Pull Request。在提交代码前请确保：

1. 代码符合PEP 8规范
2. 添加必要的注释和文档
3. 通过所有测试用例
4. 更新相关文档

## 许可证

MIT License

## 免责声明

本项目仅供学习和研究使用，不构成投资建议。使用者需自行承担投资风险。