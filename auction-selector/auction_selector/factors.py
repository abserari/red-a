"""竞价因子与打分（自有实现，公式语义与原系统一致）。

与原系统的关键差异（详见 EXTRACTION_NOTES.md）：
1. 量比分母由调用方决定：优先「近5日竞价成交量均值」，回退才用
   「5日日均量×5%」，且回退必须带 vol_ratio_fallback=True 标记。
2. 绝不模拟价格序列：无真实竞价序列时，斜率/尾加速度/撤单率记为
   None（缺失），has_auction_data=False。
"""

from typing import Dict, List, Optional, Tuple

from . import config
from .provider import is_gem_or_star

LOCK_SEC = 9 * 3600 + 20 * 60  # 09:20:00 的日内秒数


def _sec(time_str: str) -> int:
    parts = time_str.split(":")
    h, m = int(parts[0]), int(parts[1])
    s = int(parts[2]) if len(parts) > 2 else 0
    return h * 3600 + m * 60 + s


def lin_slope(xs: List[float], ys: List[float]) -> Optional[float]:
    """最小二乘线性回归斜率；点数<2 或时间无跨度时返回 None。"""
    n = len(xs)
    if n < 2:
        return None
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    if sxx <= 0:
        return None
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    return sxy / sxx


def series_factors(series: List[Tuple[str, float, float]]) -> Dict:
    """从真实竞价序列 [(时间, 指示价, 累计量-股)] 提取三因子。

    - 撤单率：09:15-09:20 段最大累计量 vs 09:20 后首个累计量之差占比
    - 抢筹斜率：09:20-09:25 段指示价对时间的回归斜率（元/秒）
    - 尾盘加速度：最后 60 秒内指示价的回归斜率（元/秒）
    数据不足的分量返回 None，绝不编造。
    """
    out = {"has_auction_data": False, "cancel_ratio": None,
           "aggression_slope": None, "tail_acceleration": None}
    if not series or len(series) < 2:
        return out
    pts = []
    for t, p, v in series:
        try:
            pts.append((_sec(t), float(p), float(v)))
        except (ValueError, TypeError):
            continue
    if len(pts) < 2:
        return out
    pts.sort(key=lambda x: x[0])
    out["has_auction_data"] = True

    cancellable = [x for x in pts if x[0] < LOCK_SEC]
    locked = [x for x in pts if x[0] >= LOCK_SEC]

    if cancellable and locked:
        max_vol = max(x[2] for x in cancellable)
        if max_vol > 0:
            out["cancel_ratio"] = max(0.0, (max_vol - locked[0][2]) / max_vol)

    locked_prices = [(x[0], x[1]) for x in locked if x[1] > 0]
    if len(locked_prices) >= 2:
        out["aggression_slope"] = lin_slope(
            [x[0] for x in locked_prices], [x[1] for x in locked_prices])

    tail_from = pts[-1][0] - 60
    tail = [(x[0], x[1]) for x in pts if x[0] >= tail_from and x[1] > 0]
    if len(tail) >= 2:
        out["tail_acceleration"] = lin_slope(
            [x[0] for x in tail], [x[1] for x in tail])
    return out


def volume_ratio(auction_volume_shares: float, denominator: float) -> float:
    """竞价量比 = 竞价成交量 / 分母，上限 50（同原系统）。"""
    if denominator <= 0:
        return 0.0
    return min(auction_volume_shares / denominator, 50.0)


def sector_linkage(code: str, sector_map: Dict[str, str],
                   performance: Dict[str, Dict]) -> float:
    """板块联动度：同板块涨幅>2%占比×10，有涨停先锋 +2，上限 15（同原系统）。"""
    sector = sector_map.get(code, "")
    if not sector:
        return 0.0
    peers = [perf for c, perf in performance.items()
             if sector_map.get(c) == sector]
    if not peers:
        return 0.0
    strong = sum(1 for p in peers if p.get("pct_chg", 0) > 2.0)
    score = strong / len(peers) * 10
    if any(p.get("pct_chg", 0) >= 9.8 for p in peers):
        score += 2.0
    return min(score, 15.0)


def build_factors(snapshot: Dict, benchmark: Dict,
                  series: Optional[List[Tuple[str, float, float]]],
                  vol_denominator: float, vol_ratio_fallback: bool,
                  sector_map: Dict[str, str],
                  performance: Dict[str, Dict]) -> Dict:
    """组装单只股票的全部因子。

    snapshot: Provider 规范化快照（09:25 最终快照）
    benchmark: 候选池记录 {avg_5d_vol, avg_5d_amount, close(昨收), name}
    vol_denominator: 量比分母（股），由 engine 决定口径
    """
    auction_vol = float(snapshot.get("volume_shares", 0) or 0)
    open_px = float(snapshot.get("open", 0) or 0)
    price = float(snapshot.get("price", 0) or 0)
    # 撮合价：09:25 后 open 即竞价撮合价；open 无效时回退现价（同原系统归一化）
    match_price = open_px if open_px > 0 else price
    pre_close = float(snapshot.get("preclose", 0) or 0) \
        or float(benchmark.get("close", 0) or 0)
    pct_chg = ((match_price - pre_close) / pre_close * 100
               if pre_close > 0 and match_price > 0 else 0.0)

    amount_yuan = float(snapshot.get("amount_yuan", 0) or 0)
    amount_wan = amount_yuan / 10000 if amount_yuan > 0 else \
        auction_vol * match_price / 10000

    bid1_vol_shares = float(snapshot.get("bid1_vol_lots", 0) or 0) * 100

    sf = series_factors(series) if series else {
        "has_auction_data": False, "cancel_ratio": None,
        "aggression_slope": None, "tail_acceleration": None}

    return {
        "tcode": snapshot["tcode"],
        "code": snapshot["code"],
        "name": snapshot.get("name", "") or benchmark.get("name", ""),
        "board": benchmark.get("board", ""),
        "match_price": match_price,
        "pct_chg": pct_chg,
        "auction_volume": auction_vol,
        "auction_volume_ratio": volume_ratio(auction_vol, vol_denominator),
        "vol_ratio_fallback": vol_ratio_fallback,
        "auction_amount": amount_wan,  # 万元
        "bid_surplus_ratio": (bid1_vol_shares / auction_vol
                              if auction_vol > 0 else 0.0),
        "cancel_ratio": sf["cancel_ratio"],
        "aggression_slope": sf["aggression_slope"],
        "tail_acceleration": sf["tail_acceleration"],
        "has_auction_data": sf["has_auction_data"],
        "sector_linkage": sector_linkage(
            snapshot["tcode"], sector_map, performance),
    }


def hard_filter(f: Dict) -> Tuple[bool, str]:
    """硬过滤（同原系统 Scorer.apply_hard_filters 语义）。

    例外：撤单率缺失（无竞价序列）时不因撤单率剔除——该股已用
    has_auction_data=False 标记，见 README 的缺失处理说明。
    """
    cfg = config.FILTER
    if cfg["exclude_st"] and "ST" in (f.get("name") or ""):
        return False, "ST股票"
    pct = f.get("pct_chg", 0)
    if pct < cfg["pct_chg_min"] or pct > cfg["pct_chg_max"]:
        return False, f"涨幅不符合 {pct:.2f}%"
    if f.get("auction_volume_ratio", 0) < cfg["min_auction_volume_ratio"]:
        return False, f"量比不足 {f.get('auction_volume_ratio', 0):.1f}"
    floor = cfg["min_auction_amount_gem"] if is_gem_or_star(f["code"]) \
        else cfg["min_auction_amount_main"]
    if f.get("auction_amount", 0) < floor:
        return False, f"成交额不足 {f.get('auction_amount', 0):.0f}万 < {floor}万"
    cancel = f.get("cancel_ratio")
    if cancel is not None and cancel > cfg["max_cancel_ratio"] and pct < 3.0:
        return False, f"撤单率过高 {cancel:.1%}"
    return True, "通过"


def score_all(finalists: List[Dict]) -> List[Dict]:
    """在 finalist 集合内做百分位加权打分（同原系统：严格小于占比）。

    注：打分四因子（量比/竞价额/封单比/涨幅）全部来自 09:25 快照，
    不依赖竞价序列，因此序列缺失不影响参评资格（见 README）。
    """
    w = config.SCORING_WEIGHTS
    n = len(finalists)
    if n == 0:
        return finalists
    keys = [("auction_volume_ratio", w["vol_ratio"]),
            ("auction_amount", w["auction_amount"]),
            ("bid_surplus_ratio", w["bid_surplus_ratio"]),
            ("pct_chg", w["pct_chg"])]
    columns = {k: [f[k] for f in finalists] for k, _ in keys}
    for f in finalists:
        score = 0.0
        for k, weight in keys:
            rank = sum(1 for v in columns[k] if v < f[k]) / n
            score += weight * rank
        score += f.get("sector_linkage", 0) * config.SECTOR_LINKAGE_BONUS
        f["score"] = round(score * 100, 4)
    finalists.sort(key=lambda f: f["score"], reverse=True)
    return finalists
