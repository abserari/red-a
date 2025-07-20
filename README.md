# Red-A (红A) - A股高股息套利策略分析系统

Red-A 是一个专注于中国A股市场的高股息套利策略分析系统，通过寻找高股息率股票并优化除息日前后的买卖时机来获取超额收益。

## 系统特点

- 🚀 **多数据源架构**：智能切换 BaoStock、akshare、Tushare 三大数据源
- 📊 **智能增量更新**：自动检测并仅获取缺失的数据
- 🔄 **并发数据获取**：支持多线程并发，大幅提升效率
- 💾 **MongoDB 存储**：高效的数据存储和查询
- 📈 **策略回测**：完整的历史回测和收益分析

## 数据源优先级

本项目使用多数据源策略，按以下优先级自动选择：

1. **BaoStock**（优先推荐）
   - ✅ 完全免费，无需 token
   - ✅ 数据稳定可靠
   - ✅ 支持复权数据
   - ✅ 官方维护，更新及时

2. **akshare**（备用）
   - ✅ 免费开源
   - ⚠️ 可能有网络连接问题
   - ✅ 数据源丰富

3. **Tushare**（最后备用）
   - ⚠️ 需要注册获取 token
   - ⚠️ 有调用频率限制
   - ✅ 数据质量高

## 快速开始

### 1. 环境准备

```bash
# 克隆项目
git clone https://github.com/yourusername/red-a.git
cd red-a

# 使用 uv 创建虚拟环境（推荐）
uv venv
source .venv/bin/activate  # Linux/Mac
# 或
.venv\Scripts\activate     # Windows

# 安装依赖
uv pip sync pyproject.toml
```

### 2. 启动 MongoDB

```bash
# 使用 Docker Compose 启动 MongoDB
docker-compose up -d

# 验证 MongoDB 运行状态
docker-compose ps
```

### 3. 配置数据源（可选）

如果要使用 Tushare 作为备用数据源，需要配置 token：

```bash
# 复制配置文件
cp .env.example .env

# 编辑 .env 文件，添加你的 Tushare token
# TUSHARE_TOKEN=your_token_here
```

### 4. 测试数据源

```bash
# 测试数据源连接和优先级
python test_data_sources.py
```

### 5. 获取数据

```bash
# 获取所有A股数据（约5000+股票，8年历史数据）
python get_all_data.py

# 自定义参数
python get_all_data.py --years 5 --batch-size 50 --workers 5

# 快速测试（仅获取几只股票的数据）
python quick_test.py
```

## 使用指南

### 数据获取

```python
from data_acquisition import DataAcquisition

# 初始化
da = DataAcquisition()

# 获取股票列表
stock_list = da.get_all_stock_list()

# 获取单只股票的历史数据
df = da.get_stock_history('000001', '20200101', '20231231')

# 获取分红数据
div_df = da.get_dividend_history('000001')

# 批量获取（支持并发）
da.get_batch_stock_history_concurrent(
    stock_codes=['000001', '000002', '600000'],
    start_date='20200101',
    end_date='20231231',
    max_workers=10
)
```

### 策略分析

```python
# 启动 Jupyter Lab
jupyter lab

# 打开 dividend_strategy_analysis.ipynb 进行分析
```

## 项目结构

```
red-a/
├── data_acquisition.py          # 核心数据获取模块（多数据源管理）
├── baostock_data_acquisition.py # BaoStock 数据源实现
├── tushare_data_acquisition.py  # Tushare 数据源实现
├── dividend_strategy.py         # 股息策略分析函数
├── get_all_data.py             # 批量数据获取脚本
├── test_data_sources.py        # 数据源测试脚本
├── quick_test.py               # 快速测试脚本
├── dividend_strategy_analysis.ipynb  # 策略分析 Notebook
├── docker-compose.yml          # MongoDB 配置
├── pyproject.toml              # 项目依赖配置
└── CLAUDE.md                   # AI 助手指南
```

## 数据库结构

MongoDB 集合：
- `stocks`: 股票基本信息（代码、名称）
- `daily_prices`: 日线行情数据（OHLCV + 复权）
- `dividends`: 分红公告记录
- `tasks`: 数据获取任务跟踪

## 策略说明

核心策略筛选条件：
- 连续 5 年以上股息率 > 6%
- 最佳入场时机：除息日前 7 天
- 退出时机：除息日当天或之前
- 目标收益：基于历史回测约 9.77%

## 常见问题

### Q: 为什么优先使用 BaoStock？
A: BaoStock 完全免费、无需注册、数据稳定，是最适合个人投资者的数据源。

### Q: 数据获取速度慢怎么办？
A: 可以调整并发数 `--workers` 参数，但注意不要设置过高以免被限流。

### Q: 如何更新已有数据？
A: 系统会自动检测缺失的日期范围，只获取需要的数据，直接运行 `get_all_data.py` 即可。

## 贡献指南

欢迎提交 Issue 和 Pull Request！

## 许可证

MIT License

## 免责声明

本项目仅供学习研究使用，不构成投资建议。股市有风险，投资需谨慎。