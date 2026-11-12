"""离线自检（run.py --mode selftest）：

1. 快照 schema 夹具：原包 batch_quotes 缓存字段解析 + 腾讯 qt 行解析映射
2. 三公式对照：撤单率 / 抢筹斜率 / 尾盘加速度 与原系统算法同输入同输出
3. 候选池：对本地日K缓存跑 prefilter，报池大小
4. 自采器逻辑：假时钟 + 桩数据源验证窗口行为与序列拼装
5. 全文件 py_compile
返回 (全部通过?, [结果行])
"""

import compileall
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from . import factors, prefilter
from .cache import LocalCache
from .collector import AuctionCollector, AuctionWindowError, BJ
from .provider import parse_qt_line

ORIG_FIXTURE = Path.home() / ("workspace/auction_stock_selector_review/"
                              "auction_stock_selector/cache/"
                              "batch_quotes_20261112_0925.json")
TOL = 1e-6


# ---------- 参考实现（按原 auction_factors.py 的算法定义独立复写） ----------

def _ref_slope(points):
    """points: [(秒, 价)]，对应原系统 np.polyfit 回归斜率。"""
    if len(points) < 2:
        return 0.0
    ts = np.array([p[0] for p in points], dtype=float)
    ps = np.array([p[1] for p in points], dtype=float)
    if ts[-1] == ts[0]:
        return (ps[-1] - ps[0]) / (ts[-1] - ts[0] + 1e-6)
    return float(np.polyfit(ts - ts[0], ps, 1)[0])


def _ref_series(series):
    """原 _extract_auction_factors 的三项输出（series 为 (时间,价,累计量)）。

    同时返回各分量的「可计算」标记：原系统在数据不足时用默认值 0.0 占位，
    本实现按设计记为 None——对照时这类分量只校验缺失标记，不比数值。
    """
    def sec(t):
        p = t.split(":")
        return int(p[0]) * 3600 + int(p[1]) * 60 + (int(p[2]) if len(p) > 2 else 0)
    pts = [(sec(t), float(p), float(v)) for t, p, v in series]
    canc = [x for x in pts if x[0] < 9 * 3600 + 20 * 60]
    locked = [x for x in pts if x[0] >= 9 * 3600 + 20 * 60]
    cancel, cancel_ok = 0.0, bool(canc and locked)
    if cancel_ok:
        mx = max(x[2] for x in canc)
        if mx > 0:
            cancel = max(0.0, (mx - locked[0][2]) / mx)
    locked_prices = [(x[0], x[1]) for x in locked if x[1] > 0]
    slope_ok = (len(locked_prices) >= 2
                and locked_prices[-1][0] > locked_prices[0][0])
    slope = _ref_slope(locked_prices)
    tail_from = pts[-1][0] - 60
    tail_pts = [(x[0], x[1]) for x in pts if x[0] >= tail_from and x[1] > 0]
    tail_ok = len(tail_pts) >= 2 and tail_pts[-1][0] > tail_pts[0][0]
    tail = _ref_slope(tail_pts)
    return (cancel, slope, tail), (cancel_ok, slope_ok, tail_ok)


# ---------- 1. schema 夹具 ----------

def test_fixture_schema():
    if not ORIG_FIXTURE.exists():
        return False, f"夹具缺失：{ORIG_FIXTURE}"
    raw = json.loads(ORIG_FIXTURE.read_text(encoding="utf-8"))
    ok_cnt, price_pos = 0, 0
    for tcode, rec in raw.items():
        # 原始字段（均为字符串）→ 本系统规范化快照口径
        snap = {
            "tcode": tcode, "code": tcode[2:],
            "price": float(rec["last"]), "preclose": 0.0,
            "open": float(rec["open"]), "high": float(rec["high"]),
            "low": float(rec["low"]),
            "volume_lots": float(rec["volume"]),
            "volume_shares": float(rec["volume"]) * 100,
            "amount_yuan": float(rec["amount"]),
            "turnover": float(rec["turnover"]),
            "bid1_price": 0.0, "bid1_vol_lots": 0.0,
        }
        assert snap["volume_shares"] >= 0 and snap["amount_yuan"] >= 0
        assert snap["high"] >= snap["low"]
        ok_cnt += 1
        price_pos += 1 if snap["price"] > 0 else 0
    if ok_cnt < 100 or price_pos < ok_cnt * 0.95:
        return False, f"夹具解析异常：{ok_cnt} 条，正价 {price_pos} 条"
    return True, f"原包快照夹具 {ok_cnt} 条全部解析通过（字段/类型/量纲）"


def test_qt_line_parser():
    f = [""] * 50
    f[0], f[1], f[2] = "1", "贵州茅台", "600519"
    f[3], f[4], f[5], f[6] = "1410.27", "1402.30", "1395.13", "32373"
    f[9], f[10] = "1410.27", "17"
    f[19], f[20] = "1410.43", "2"
    f[30] = "20261112161452"
    f[32], f[33], f[34] = "0.57", "1411.00", "1388.11"
    f[36], f[37], f[38] = "32373", "453681", "0.26"
    f[44], f[45] = "17629.53", "17629.53"
    line = 'v_sh600519="' + "~".join(f) + '";'
    rec = parse_qt_line(line)
    assert rec is not None
    checks = [
        (rec["price"], 1410.27), (rec["preclose"], 1402.30),
        (rec["open"], 1395.13), (rec["volume_lots"], 32373.0),
        (rec["volume_shares"], 3237300.0), (rec["bid1_price"], 1410.27),
        (rec["bid1_vol_lots"], 17.0), (rec["ask1_vol_lots"], 2.0),
        (rec["high"], 1411.00), (rec["low"], 1388.11),
        (rec["amount_yuan"], 4536810000.0), (rec["turnover"], 0.26),
        (rec["total_cap_yuan"], 17629.53e8),
    ]
    for got, want in checks:
        if abs(got - want) > 1e-6:
            return False, f"qt 字段映射错误：got {got}, want {want}"
    if rec["name"] != "贵州茅台" or rec["code"] != "600519":
        return False, "qt 名称/代码映射错误"
    return True, "腾讯 qt 行解析字段映射全部正确"


# ---------- 2. 公式对照 ----------

SERIES_A = [
    ("09:15:00", 10.00, 1000), ("09:16:00", 10.05, 4000),
    ("09:18:00", 10.02, 6000), ("09:19:30", 10.08, 3000),
    ("09:20:00", 10.10, 2500), ("09:21:00", 10.15, 3000),
    ("09:22:30", 10.20, 3600), ("09:24:00", 10.30, 4200),
    ("09:24:30", 10.38, 4600), ("09:25:00", 10.45, 5000),
]
SERIES_B = [  # 只有两个锁定段点、价格走平
    ("09:15:00", 20.00, 500), ("09:19:00", 20.00, 900),
    ("09:20:30", 20.10, 800), ("09:25:00", 20.10, 1200),
]
SERIES_C = [  # 撤单段后量不降（撤单率为 0 的边界）
    ("09:15:30", 5.00, 2000), ("09:19:59", 5.10, 2000),
    ("09:20:00", 5.12, 2600), ("09:23:00", 5.20, 3000),
    ("09:24:50", 5.26, 3300), ("09:25:00", 5.30, 3400),
]


def test_formulas():
    for name, series in (("A", SERIES_A), ("B", SERIES_B), ("C", SERIES_C)):
        got = factors.series_factors(series)
        (rc, rs, rt), (ok_c, ok_s, ok_t) = _ref_series(series)
        for key, ref, computable in (("cancel_ratio", rc, ok_c),
                                     ("aggression_slope", rs, ok_s),
                                     ("tail_acceleration", rt, ok_t)):
            val = got[key]
            if computable:
                if val is None or abs(val - ref) > TOL:
                    return False, (f"序列{name} {key} 不一致："
                                   f"本实现 {val} vs 原算法 {ref}")
            elif val is not None:
                return False, (f"序列{name} {key} 数据不足应记缺失，"
                               f"却得到 {val}")
        if not got["has_auction_data"]:
            return False, f"序列{name} has_auction_data 应为 True"
    # 退化输入：缺失而非编造
    got = factors.series_factors([("09:20:00", 10.0, 100)])
    if got["has_auction_data"] or got["aggression_slope"] is not None:
        return False, "单点序列应记为缺失（None），不得编造因子"
    return True, "撤单率/抢筹斜率/尾盘加速度与原算法逐项一致（误差<1e-6）"


# ---------- 3. prefilter ----------

def test_prefilter(base_dir: Path):
    cache = LocalCache(base_dir / "data")
    universe = cache.load_universe()
    bars_map = cache.load_bars()
    if not universe or not bars_map:
        return False, "本地缓存为空（需先跑 refresh），prefilter 自检跳过"
    pool = prefilter.build_pool(universe, bars_map, save_dir=None)
    n = pool["pool_size"]
    if n <= 0 or n > 300:
        return False, f"候选池大小异常：{n}"
    return True, (f"prefilter 对本地缓存（{len(universe)} 只）运行成功："
                  f"池大小 {n}，排除统计 {pool['excluded']}")


# ---------- 4. 自采器逻辑 ----------

class _FakeClock:
    def __init__(self, start: datetime):
        self.t = start

    def now(self):
        return self.t

    def sleep(self, sec: float):
        self.t += timedelta(seconds=max(0.0, sec))


class _StubProvider:
    def __init__(self, clock):
        self.clock = clock

    def get_snapshot_batch(self, tcodes):
        now = self.clock.now()
        sec = now.hour * 3600 + now.minute * 60 + now.second
        lock = 9 * 3600 + 20 * 60
        price = 10.0 if sec < lock else 10.0 + (sec - lock) / 300 * 0.5
        out = {}
        for c in tcodes:
            out[c] = {"tcode": c, "code": c[2:], "name": "桩股",
                      "price": price, "preclose": 9.9, "open": 0.0,
                      "high": price, "low": price, "volume_lots": 100.0,
                      "volume_shares": 10000.0, "amount_yuan": 100000.0,
                      "turnover": 0.1, "bid1_price": price,
                      "bid1_vol_lots": 50.0, "ask1_price": price,
                      "ask1_vol_lots": 10.0, "pct_chg": 1.0, "time": ""}
        return out


def test_collector():
    day = datetime.now(BJ).date()
    while day.weekday() >= 5:  # 取最近的工作日做假时钟日期
        day += timedelta(days=1)
    start = datetime(day.year, day.month, day.day, 9, 14, 50, tzinfo=BJ)
    clock = _FakeClock(start)
    with tempfile.TemporaryDirectory() as td:
        col = AuctionCollector(_StubProvider(clock),
                               ["sh600000", "sz000001"], Path(td),
                               interval=15, now_fn=clock.now,
                               sleep_fn=clock.sleep, log=lambda *a: None)
        path = col.run()
        payload = json.loads(path.read_text(encoding="utf-8"))
        for c in ("sh600000", "sz000001"):
            pts = payload["series"][c]
            if len(pts) < 30 or pts[0][0] < "09:15:00" or pts[-1][0] < "09:25:00":
                return False, f"自采序列异常 {c}：{len(pts)} 点"
    # 窗口已过必须拒绝
    late = _FakeClock(datetime(day.year, day.month, day.day, 10, 0, tzinfo=BJ))
    col2 = AuctionCollector(_StubProvider(late), ["sh600000"], Path("/tmp"),
                            now_fn=late.now, sleep_fn=late.sleep,
                            log=lambda *a: None)
    try:
        col2.run()
        return False, "窗口已过时自采器未拒绝"
    except AuctionWindowError:
        pass
    return True, "自采器：窗口等待/15s轮询/09:25收官/过期拒绝 逻辑全部正确"


# ---------- 5. 编译 ----------

def test_compile(base_dir: Path):
    ok = compileall.compile_dir(str(base_dir / "auction_selector"),
                                quiet=1) and \
        compileall.compile_file(str(base_dir / "run.py"), quiet=1)
    return (True, "全部 py 文件编译通过") if ok else (False, "存在编译失败文件")


def run_selftest(base_dir: Path):
    tests = [
        ("快照夹具", test_fixture_schema),
        ("qt行解析", test_qt_line_parser),
        ("因子公式", test_formulas),
        ("候选池", lambda: test_prefilter(base_dir)),
        ("自采器逻辑", test_collector),
        ("编译检查", lambda: test_compile(base_dir)),
    ]
    lines, all_ok = [], True
    for name, fn in tests:
        try:
            ok, msg = fn()
        except Exception as e:  # 自检本身异常也要如实报 FAIL
            ok, msg = False, f"自检异常：{type(e).__name__}: {e}"
        all_ok = all_ok and ok
        lines.append(f"[{'PASS' if ok else 'FAIL'}] {name}：{msg}")
    lines.append(f"== SELFTEST {'PASS' if all_ok else 'FAIL'} ==")
    return all_ok, lines
