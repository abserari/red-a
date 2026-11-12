"""盘前本地预过滤：只用本地缓存把全市场压缩到 300 只候选池（零行情接口）。

语义与原系统 core/prefilter.py 一致：基础过滤（ST/北交所/5日均额/低价）
→ K线指标过滤（天数/距高回撤/换手）→ 百分位加权排序取前 N。
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional

from . import config
from .provider import board_of

BJ = timezone(timedelta(hours=8))


def pool_trade_date(now: datetime = None) -> str:
    """候选池服务的竞价交易日：工作日取当天，周末取下个工作日。"""
    day = (now or datetime.now(BJ)).date()
    while day.weekday() >= 5:
        day += timedelta(days=1)
    return day.strftime("%Y-%m-%d")


def pool_path(output_dir: Path, date: str = None) -> Path:
    date = date or pool_trade_date()
    return Path(output_dir) / f"prefilter_{date.replace('-', '')}.json"


def load_pool(output_dir: Path, date: str = None) -> Optional[Dict]:
    path = pool_path(output_dir, date)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return None


def _pct_rank_avg(values: List[float]) -> List[float]:
    """百分位排名（并列取平均秩），等价于 pandas rank(pct=True)。"""
    n = len(values)
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2 + 1  # 1-based 平均秩
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank / n
        i = j + 1
    return ranks


def stock_metrics(bars: List[Dict], today: str) -> Optional[Dict]:
    """单只指标：剔除当日未完成K线后，用最近窗口计算。"""
    done = [b for b in bars if b["date"] != today]
    if len(done) < 5:
        return None
    window = done[-max(int(config.PREFILTER["high_window_days"]), 5):]
    closes = [b["close"] for b in window]
    last_close = closes[-1]
    if last_close <= 0:
        return None
    last5 = done[-5:]

    def mean(key, rows):
        vals = [r[key] for r in rows]
        return sum(vals) / len(vals) if vals else 0.0

    avg_5d_amount = mean("amount", last5)          # 元
    avg_5d_turnover = mean("turnover", last5)      # %
    avg_5d_vol = mean("volume", last5)             # 股

    # 5日均振幅（%）：(高-低)/前收，取最近5个有前收的交易日
    amps = []
    idx = {b["date"]: i for i, b in enumerate(done)}
    for b in last5:
        i = idx[b["date"]]
        if i > 0 and done[i - 1]["close"] > 0:
            amps.append((b["high"] - b["low"]) / done[i - 1]["close"] * 100)
    avg_5d_amplitude = sum(amps) / len(amps) if amps else 0.0

    high_recent = max(closes)
    dist_recent_high = ((high_recent - last_close) / high_recent
                        if high_recent > 0 else 1.0)
    return {
        "close": last_close,
        "kline_days": len(done),
        "avg_5d_amount": avg_5d_amount,
        "avg_5d_amount_wan": avg_5d_amount / 10000.0,
        "avg_5d_turnover": avg_5d_turnover,
        "avg_5d_amplitude": avg_5d_amplitude,
        "avg_5d_vol": avg_5d_vol,
        "dist_recent_high": dist_recent_high,
    }


def build_pool(universe: List[Dict], bars_map: Dict[str, List[Dict]],
               today: str = None, save_dir: Path = None) -> Dict:
    cfg = config.PREFILTER
    today = today or datetime.now(BJ).strftime("%Y-%m-%d")
    excluded = {"ST": 0, "北交所": 0, "无K线数据": 0, "成交额不足": 0,
                "低价股": 0, "K线不足": 0, "距近期高点过远": 0, "换手率过低": 0}
    metrics_list = []

    for stock in universe:
        tcode, code, name = stock["tcode"], stock["code"], stock.get("name", "")
        if cfg["exclude_st"] and "ST" in name:
            excluded["ST"] += 1
            continue
        if cfg["exclude_bse"] and board_of(code) == "北交所":
            excluded["北交所"] += 1
            continue
        bars = bars_map.get(tcode)
        if not bars:
            excluded["无K线数据"] += 1
            continue
        m = stock_metrics(bars, today)
        if m is None:
            excluded["无K线数据"] += 1
            continue
        if m["avg_5d_amount_wan"] < cfg["min_avg_5d_amount_wan"]:
            excluded["成交额不足"] += 1
            continue
        if 0 < m["close"] < cfg["min_pre_close"]:
            excluded["低价股"] += 1
            continue
        if m["kline_days"] < cfg["min_kline_days"]:
            excluded["K线不足"] += 1
            continue
        if m["dist_recent_high"] > cfg["max_dist_recent_high"]:
            excluded["距近期高点过远"] += 1
            continue
        if m["avg_5d_turnover"] < cfg["min_avg_5d_turnover"]:
            excluded["换手率过低"] += 1
            continue
        metrics_list.append({
            "tcode": tcode, "code": code, "name": name,
            "board": board_of(code), **m,
        })

    # 百分位加权排序
    weights = cfg["rank_weights"]
    if metrics_list:
        fields = {
            "amount": [m["avg_5d_amount"] for m in metrics_list],
            "turnover": [m["avg_5d_turnover"] for m in metrics_list],
            "amplitude": [m["avg_5d_amplitude"] for m in metrics_list],
            "strength": [1.0 - m["dist_recent_high"] for m in metrics_list],
        }
        pct = {k: _pct_rank_avg(v) for k, v in fields.items()}
        for i, m in enumerate(metrics_list):
            m["pool_score"] = round(
                sum(pct[k][i] * weights.get(k, 0) for k in fields), 4)
        metrics_list.sort(key=lambda m: m["pool_score"], reverse=True)
        metrics_list = metrics_list[:cfg["max_pool_size"]]

    result = {
        "date": pool_trade_date(),
        "generated_at": datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S"),
        "total_stocks": len(universe),
        "pool_size": len(metrics_list),
        "excluded": {k: v for k, v in excluded.items() if v > 0},
        "pool": metrics_list,
    }
    if save_dir is not None:
        path = pool_path(save_dir, result["date"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        result["_path"] = str(path)
    return result
