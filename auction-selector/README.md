# 集合竞价选股系统（数据源无关版）

A 股集合竞价选股信息系统：盘前用日 K 把全市场压到 300 只候选池，
09:15–09:25 自采竞价指示价序列，09:25 用最终快照算因子、硬过滤、
百分位打分，输出主板 Top10 与创业板/科创板 Top5。

本项目由一套依赖付费 API 的同类系统移植重写而来：**策略核只依赖
数据源抽象接口**，数据源可替换；当前实现走腾讯公开接口 + 竞价自采，
不依赖任何付费 key。仅做信息处理，不涉及任何交易功能。

## 架构

```
run.py                        运行入口（refresh / prefilter / morning / selftest）
auction_selector/
  config.py                   全部阈值与权重（与原系统 settings.py 语义一致）
  provider.py                 数据源层：DataProvider 抽象接口 + TencentProvider
  cache.py                    本地缓存：股票池、日K(CSV)、竞价量历史；增量刷新
  prefilter.py                盘前预过滤（本地缓存 → 300 只候选池）
  collector.py                竞价序列自采器（09:15-09:25 每 15s 轮询快照）
  factors.py                  因子计算、硬过滤、百分位打分
  engine.py                   morning 全流程编排（三阶段）
  selftest.py                 离线自检
data/                         运行时缓存（不入仓）
output/                       候选池与推荐结果（不入仓）
```

## 数据源接口（DataProvider）

策略核只消费以下规范化结构，换数据源只需再写一个 Provider：

| 方法 | 返回 | 说明 |
|---|---|---|
| `get_universe()` | `[{tcode, code, name, board, price, total_cap_yuan, float_cap_yuan}]` | 全市场股票池；tcode 为带前缀代码（sh600519） |
| `get_daily_bars(tcode, days)` | `[{date, open, close, high, low, volume(股), amount(元), turnover(%)}]` | 日 K，日期升序 |
| `get_snapshot_batch(tcodes)` | `{tcode: {price, preclose, open, high, low, volume_lots(手), volume_shares(股), amount_yuan(元), turnover(%), bid1_price, bid1_vol_lots(手), ask1_price, ask1_vol_lots(手), pct_chg(%), time}}` | 批量快照，单批 ≤100 只 |
| `get_auction_series(tcode)` | `[(时间, 指示价, 累计量)]` 或 `None` | 可选能力；腾讯无此接口，返回 None，竞价序列由自采器提供 |

抓取通道可配置：`AUCTION_HTTP_MODE=auto|direct|proxy`（环境变量），
auto 为直连优先、失败自动回退家里中转 `http://127.0.0.1:18080`。

## 腾讯字段映射

快照 `qt.gtimg.cn/q=`（GBK 解码，单批 ≤100 只，超量会随机丢码）：

| 规范化字段 | qt 下标 | 备注 |
|---|---|---|
| name / code | [1] / [2] | |
| price 现价 | [3] | 竞价时段即虚拟撮合价 |
| preclose 昨收 | [4] | |
| open 今开 | [5] | 09:25 后即竞价撮合价 |
| volume_lots 累计量(手) | [6] | 竞价时段为累计指示量 |
| bid1_price / bid1_vol_lots | [9] / [10] | 买一价 / 买一量(手) |
| ask1_price / ask1_vol_lots | [19] / [20] | |
| time | [30] | YYYYMMDDHHMMSS |
| pct_chg 涨跌幅% | [32] | |
| high / low | [33] / [34] | |
| amount_yuan 成交额(元) | [37] ×10000 | 接口单位为万元 |
| turnover 换手% | [38] | |
| float_cap_yuan / total_cap_yuan | [44] / [45] ×1e8 | 接口单位为亿元 |

日 K `web.ifzq.gtimg.cn/appstock/app/newfqkline/get?param=<tcode>,day,,,<N>,qfq`：
行格式 `[日期, 开, 收, 高, 低, 量(手), {...}, 换手%, 成交额(万元), ...]`；
无除权时返回键是 `day` 而非 `qfqday`，代码已兼容。前复权口径。

## 两个代理口径（与原付费 API 的差异，务必知悉）

1. **买一量代理未匹配量**：原 API 直接给「买一未匹配量」，本系统用
   09:25 最终快照的**买一量**作代理计算委买封单比
   （买一量(股) / 竞价成交量(股)）。竞价结束后买一未成交量与未匹配量
   高度相关但不完全等同，封单比绝对值仅供横向排序使用。
2. **自采序列代理竞价分时**：原 API 提供 09:15–09:25 竞价分时，
   本系统在竞价时段每 15 秒轮询快照，把（时间、现价、累计量）拼成
   序列。采样粒度 15 秒（原 API 为更细粒度），斜率/撤单率的数值
   精度略低，但公式与原系统完全一致（自检已逐项对照）。

## 策略口径

- **prefilter**：排除 ST、北交所；近 5 日日均成交额 ≥500 万元；
  昨收 ≥2 元；K 线 ≥20 日；距 30 日最高收盘回撤 ≤30%；
  5 日均换手 ≥0.3%；按成交额 0.4 / 换手 0.3 / 振幅 0.2 / 强度 0.1
  百分位加权排序，池上限 300 只。
- **因子**：竞价量比、抢筹斜率（09:20–09:25 指示价回归斜率）、
  尾盘加速度（最后 60 秒斜率）、竞价成交额（万元）、委买封单比、
  撤单率（09:15–09:20 段最大累计量 vs 09:20 时刻累计量）、板块联动。
- **硬过滤**：涨幅 1.5%–5.5%；量比 ≥3；竞价额主板 ≥500 万、
  双创 ≥300 万；撤单率 >0.6 且涨幅 <3% 剔除；
  二阶段撤单率 >0.7 直接剔除。
- **打分**：finalist（硬过滤后按量比取前 30）内百分位加权：
  量比 0.35 / 竞价额 0.30 / 封单比 0.25 / 涨幅 0.10
  （+ 板块联动 ×0.01 加分），分主板 Top10、双创 Top5 输出。

## 两个已修复的原系统毛病

1. **量比分母**：原系统用「5 日日均量 ×5%」拍脑袋近似开盘量。
   本系统优先用自采积累的**近 5 日竞价成交量均值**作分母；
   无历史时才回退原近似，并把结果标记 `vol_ratio_fallback=true`
   （报告中注明「量比为回退口径」）。竞价量历史由每次 morning
   自动写入 `data/auction_vol_history.json`，约一周后回退口径
   基本退出使用。
2. **绝不模拟价格序列**：原系统缺竞价数据时用模拟序列顶替斜率
   因子。本系统无真实序列时斜率/尾加速度/撤单率一律记为缺失
   （`null`，`has_auction_data=false`），报告中显示「-」。

### 缺失因子的处理（设计决定）

打分四因子（量比/竞价额/封单比/涨幅）全部来自 09:25 快照，
不依赖竞价序列；序列因子只参与撤单率一道硬过滤（缺失时该道
过滤不触发剔除）和报告展示。因此**不因序列缺失剔除股票**，
否则自采一旦故障当日即全军覆没，韧性太差；缺失股票在结果中
以 `has_auction_data=false` 明确标记，可人工复核。

## 运行说明

```bash
# 1) 刷新缓存（盘后或盘前均可；增量模式只补最新交易日）
python3 run.py --mode refresh            # 增量
python3 run.py --mode refresh --full     # 全量重拉（首次必跑）

# 2) 生成当日候选池（盘前，如 09:10 前）
python3 run.py --mode prefilter

# 3) 早盘全流程（须在 09:25 前启动，推荐 09:10 前挂起等窗口）
python3 run.py --mode morning

# 离线自检
python3 run.py --mode selftest
```

morning 在非交易时段（周末、09:25:30 之后）运行会**明确报错
退出（exit 2）**，不会用收盘数据假跑。morning 若发现当日候选池
文件缺失，会用本地缓存现生成一份再继续（日志注明）。

输出文件：`output/prefilter_YYYYMMDD.json`、
`output/recommendations_YYYYMMDD.json`、`output/report_YYYYMMDD.txt`、
`data/auction_series_YYYYMMDD.json`。

## 已知限制

- **板块联动恒为 0**：腾讯快照/日 K 不提供行业/概念映射，
  `sector_map` 为空，联动因子与打分加分均为 0。后续若接入行业
  数据源，只需在 engine 里填充 sector_map，因子代码无需改动。
- 候选代码段沿用动量扫描的范围（沪主板/深主板/创业板/科创板），
  不含北交所（策略本身也排除）、不含 302 段少数代码。
- 日 K 为前复权口径；极旧格式若无换手/成交额字段，额以典型价
  (O+H+L+C)/4×量 估算、换手记 0（当前腾讯返回均带这两字段，
  兜底分支基本不会触发）。
- 自采依赖本机在 09:15–09:25 保持运行与网络可用；单轮快照
  拉取失败会记空点，序列点数不足时对应因子按缺失处理。
- 腾讯公开接口无 SLA，盘中可能限流；Transport 已做直连/代理
  双通道与失败批次拆小重试。

## 自检

`run.py --mode selftest` 覆盖：原包快照缓存的 schema 夹具解析、
腾讯 qt 行字段映射、撤单率/抢筹斜率/尾盘加速度与原算法逐项
对照（误差 <1e-6）、本地缓存 prefilter 实跑、自采器假时钟逻辑、
全文件编译检查。
