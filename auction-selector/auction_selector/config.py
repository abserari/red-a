"""集合竞价选股系统配置（阈值/权重与原系统 settings.py 语义一致，集中管理）。"""

# ---------------- 盘前预过滤 ----------------
PREFILTER = {
    "exclude_st": True,            # 排除 ST/*ST
    "exclude_bse": True,           # 排除北交所
    "min_avg_5d_amount_wan": 500,  # 近5日日均成交额下限（万元）
    "min_pre_close": 2.0,          # 昨收（最近完成日收盘）下限（元）
    "min_kline_days": 20,          # 本地K线最少交易日数
    "high_window_days": 30,        # 高点/强度统计窗口
    "max_dist_recent_high": 0.30,  # 距窗口内最高收盘的最大回撤
    "min_avg_5d_turnover": 0.3,    # 5日均换手率下限（%）
    "max_avg_5d_amplitude": 0,     # 5日均振幅上限（%，0=不限制）
    "limit_up_lookback": 0,        # 近N日有涨停则排除（0=不排除）
    "max_pool_size": 300,          # 候选池上限
    "rank_weights": {              # 候选池排序权重
        "amount": 0.4,             # 5日均成交额
        "turnover": 0.3,           # 5日均换手率
        "amplitude": 0.2,          # 5日均振幅
        "strength": 0.1,           # 距窗口高点的强度（1-回撤）
    },
}

# ---------------- 竞价阶段初筛 ----------------
SCREEN = {
    "candidate_count": 30,         # 硬过滤后按量比取前 N 只进入最终打分
    "pre_filter_pct_chg_min": 1.0,  # 初筛最小涨幅（%）
}

# ---------------- 硬过滤 ----------------
FILTER = {
    "exclude_st": True,
    "pct_chg_min": 1.5,            # 最小涨幅 %
    "pct_chg_max": 5.5,            # 最大涨幅 %（避免追高）
    "min_auction_volume_ratio": 3.0,  # 最小竞价量比
    "min_auction_amount_main": 500,   # 主板最低竞价成交额（万元）
    "min_auction_amount_gem": 300,    # 创业板/科创板最低竞价成交额（万元）
    "max_cancel_ratio": 0.6,       # 撤单率上限（且涨幅<3%时剔除）
    "stage2_cancel_drop": 0.7,     # 二阶段：撤单率超过此值直接剔除
}

# ---------------- 打分权重 ----------------
SCORING_WEIGHTS = {
    "vol_ratio": 0.35,
    "auction_amount": 0.30,
    "bid_surplus_ratio": 0.25,
    "pct_chg": 0.10,
}
SECTOR_LINKAGE_BONUS = 0.01        # 板块联动分对总分的加分系数（同原系统）

# ---------------- 输出 ----------------
OUTPUT = {
    "top_n_main": 10,              # 主板推荐数量
    "top_n_gem": 5,                # 创业板/科创板推荐数量
}

# ---------------- 竞价窗口（Asia/Shanghai） ----------------
AUCTION_START = "09:15:00"         # 集合竞价开始（可撤单）
AUCTION_LOCK = "09:20:00"          # 不可撤单阶段开始
AUCTION_END = "09:25:00"           # 竞价结束/定盘
COLLECT_INTERVAL_SEC = 15          # 自采轮询间隔（秒）

# ---------------- 数据源 ----------------
HTTP_MODE = "auto"                 # auto=直连失败自动回退代理 / direct / proxy
PROXY_URL = "http://127.0.0.1:18080"  # 家里中转（tailscale-home-relay）
HTTP_TIMEOUT = 20
