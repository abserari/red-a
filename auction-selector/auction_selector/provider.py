"""数据源层：Provider 抽象接口 + 腾讯实现。

设计原则：策略核只依赖本模块定义的规范化数据结构，不感知任何具体数据源。
代码统一使用带市场前缀的代码（tcode）：sh600519 / sz000001 / sz300750。
"""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

import requests

from . import config

UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)"}


def board_of(code6: str) -> str:
    """按 6 位代码判断板块。"""
    if code6.startswith(("300", "301", "302")):
        return "创业板"
    if code6.startswith(("688", "689")):
        return "科创板"
    if code6.startswith(("43", "83", "87", "88", "92")):
        return "北交所"
    return "主板"


def is_gem_or_star(code6: str) -> bool:
    return board_of(code6) in ("创业板", "科创板")


class Transport:
    """HTTP 抓取：直连优先，失败自动回退家里中转代理（可配置）。"""

    def __init__(self, mode: str = None, proxy: str = None):
        self.mode = (mode or os.environ.get("AUCTION_HTTP_MODE")
                     or config.HTTP_MODE)
        self.proxy = proxy or config.PROXY_URL
        self._proxy_ok = None  # None=未验证

    def _proxies(self):
        return {"http": self.proxy, "https": self.proxy}

    def get_bytes(self, url: str, tries: int = 3) -> bytes:
        """返回响应字节；直连与代理都失败时返回空字节。"""
        use_proxy_first = self.mode == "proxy"
        for attempt in range(tries):
            for via_proxy in ([True, False] if use_proxy_first else [False, True]):
                if via_proxy and self.mode == "direct":
                    continue
                if via_proxy and self._proxy_ok is False and self.mode == "auto":
                    continue
                try:
                    r = requests.get(
                        url, headers=UA, timeout=config.HTTP_TIMEOUT,
                        proxies=self._proxies() if via_proxy else None)
                    if r.status_code == 200 and r.content:
                        if via_proxy:
                            self._proxy_ok = True
                        return r.content
                except Exception:
                    if via_proxy:
                        self._proxy_ok = False
                # 直连失败且 mode=auto 时，本轮直接尝试代理（上面的循环已覆盖）
            time.sleep(1.2 * (attempt + 1))
        return b""

    def get_text(self, url: str, encoding: str = "utf-8", tries: int = 3) -> str:
        raw = self.get_bytes(url, tries=tries)
        if not raw:
            return ""
        return raw.decode(encoding, errors="ignore")

    def get_json(self, url: str, tries: int = 3):
        text = self.get_text(url, encoding="utf-8", tries=tries)
        if not text or not text.strip().startswith("{"):
            return None
        try:
            return json.loads(text)
        except ValueError:
            return None


class DataProvider:
    """数据源抽象接口。策略核只依赖以下规范化结构：

    - get_universe() -> [{tcode, code, name, board, price,
                          total_cap_yuan, float_cap_yuan}]
    - get_daily_bars(tcode, days) -> [{date, open, close, high, low,
                                       volume(股), amount(元), turnover(%)}]
                                       按日期升序
    - get_snapshot_batch(tcodes) -> {tcode: {price, preclose, open, high, low,
                                       volume_lots(手), volume_shares(股),
                                       amount_yuan(元), turnover(%),
                                       bid1_price, bid1_vol_lots(手),
                                       ask1_price, ask1_vol_lots(手),
                                       pct_chg(%), time}}
    - get_auction_series(tcode) -> 可选能力：[(时间HH:MM:SS, 指示价, 累计量(股))]
                                   或 None（腾讯无此接口，由自采器实现，见 collector）
    """

    def get_universe(self) -> List[Dict]:
        raise NotImplementedError

    def get_daily_bars(self, tcode: str, days: int = 45) -> List[Dict]:
        raise NotImplementedError

    def get_snapshot_batch(self, tcodes: List[str]) -> Dict[str, Dict]:
        raise NotImplementedError

    def get_auction_series(self, tcode: str):
        return None  # 默认无此能力


# ---------------- 腾讯 qt 快照行解析 ----------------

def parse_qt_line(line: str) -> Optional[Dict]:
    """解析 qt.gtimg.cn 一行快照。字段下标（已实测）：
    [1]名称 [2]代码 [3]现价 [4]昨收 [5]今开 [6]成交量(手) [9]买一价 [10]买一量(手)
    [19]卖一价 [20]卖一量(手) [30]时间 [32]涨跌幅% [33]最高 [34]最低
    [36]成交量(手) [37]成交额(万元) [38]换手率% [44]流通市值(亿) [45]总市值(亿)
    """
    if '="' not in line:
        return None
    head = line.split("=", 1)[0].strip()
    tcode = head[2:] if head.startswith("v_") else head
    if len(tcode) != 8:
        return None
    inner = line.split('"')[1] if '"' in line else ""
    f = inner.split("~")
    if len(f) < 46:
        return None

    def num(i):
        try:
            return float(f[i])
        except (TypeError, ValueError, IndexError):
            return 0.0

    code = f[2]
    if not code or len(code) != 6:
        return None
    vol_lots = num(6)
    return {
        "tcode": tcode,
        "code": code,
        "name": f[1],
        "price": num(3),
        "preclose": num(4),
        "open": num(5),
        "volume_lots": vol_lots,
        "volume_shares": vol_lots * 100,
        "bid1_price": num(9),
        "bid1_vol_lots": num(10),
        "ask1_price": num(19),
        "ask1_vol_lots": num(20),
        "time": f[30] if len(f) > 30 else "",
        "pct_chg": num(32),
        "high": num(33),
        "low": num(34),
        "amount_yuan": num(37) * 10000,   # 接口为万元
        "turnover": num(38),
        "float_cap_yuan": num(44) * 1e8,  # 接口为亿元
        "total_cap_yuan": num(45) * 1e8,
    }


class TencentProvider(DataProvider):
    """腾讯公开接口实现（qt.gtimg.cn 快照 + web.ifzq.gtimg.cn 前复权日K）。"""

    # 候选代码段（与 scan_cn.py 一致：沪深主板/创业板/科创板，不含北交所）
    CANDIDATE_RANGES = [
        ("sz", 0, 3999), ("sz", 300000, 301999),
        ("sh", 600000, 600999), ("sh", 601000, 601999),
        ("sh", 603000, 603999), ("sh", 605000, 605999),
        ("sh", 688000, 688999),
    ]
    BATCH = 100  # qt 单批上限：超过会随机丢码（已实测）

    def __init__(self, transport: Transport = None):
        self.http = transport or Transport()

    # ---------- 股票池 ----------
    def _candidate_codes(self) -> List[str]:
        out = []
        for prefix, lo, hi in self.CANDIDATE_RANGES:
            out.extend(f"{prefix}{i:06d}" for i in range(lo, hi + 1))
        return out

    def get_snapshot_batch(self, tcodes: List[str]) -> Dict[str, Dict]:
        result: Dict[str, Dict] = {}
        batches = [tcodes[i:i + self.BATCH]
                   for i in range(0, len(tcodes), self.BATCH)]

        def fetch(batch):
            text = self.http.get_text(
                "https://qt.gtimg.cn/q=" + ",".join(batch), encoding="gbk")
            if not text:
                return None
            got = {}
            for line in text.strip().split("\n"):
                rec = parse_qt_line(line.strip())
                if rec:
                    got[rec["tcode"]] = rec
            return got

        failed = []
        with ThreadPoolExecutor(max_workers=6) as ex:
            futs = {ex.submit(fetch, b): b for b in batches}
            for fut in as_completed(futs):
                got = fut.result()
                if got is None:
                    failed.append(futs[fut])
                else:
                    result.update(got)
        # 失败批次拆小重试一次
        for b in failed:
            for i in range(0, len(b), 50):
                got = fetch(b[i:i + 50])
                if got:
                    result.update(got)
        return result

    def get_universe(self) -> List[Dict]:
        snap = self.get_snapshot_batch(self._candidate_codes())
        universe = []
        for tcode, rec in snap.items():
            if not rec["name"] or rec["price"] <= 0:
                continue
            universe.append({
                "tcode": tcode,
                "code": rec["code"],
                "name": rec["name"],
                "board": board_of(rec["code"]),
                "price": rec["price"],
                "total_cap_yuan": rec["total_cap_yuan"],
                "float_cap_yuan": rec["float_cap_yuan"],
            })
        universe.sort(key=lambda r: r["tcode"])
        return universe

    # ---------- 日K ----------
    def get_daily_bars(self, tcode: str, days: int = 45) -> List[Dict]:
        d = self.http.get_json(
            "https://web.ifzq.gtimg.cn/appstock/app/newfqkline/get"
            f"?param={tcode},day,,,{days},qfq")
        if not d or not d.get("data") or tcode not in d["data"]:
            return []
        dd = d["data"][tcode]
        rows = dd.get("qfqday") or dd.get("day")  # 无除权时只有 day 键
        if not rows:
            return []
        bars = []
        for k in rows:
            # [日期, 开, 收, 高, 低, 量(手), {...}, 换手%, 成交额(万元), ...]
            if len(k) < 6:
                continue
            try:
                vol_shares = float(k[5]) * 100
                o, c = float(k[1]), float(k[2])
                h, l = float(k[3]), float(k[4])
                if len(k) >= 9:
                    turnover = float(k[7] or 0)
                    amount_yuan = float(k[8] or 0) * 10000
                else:  # 极旧格式兜底：额用典型价估算，换手置 0（README 已注明）
                    turnover = 0.0
                    amount_yuan = vol_shares * (o + h + l + c) / 4
                bars.append({
                    "date": k[0], "open": o, "close": c, "high": h, "low": l,
                    "volume": vol_shares, "amount": amount_yuan,
                    "turnover": turnover,
                })
            except (TypeError, ValueError):
                continue
        bars.sort(key=lambda b: b["date"])
        return bars

    def get_auction_series(self, tcode: str):
        # 腾讯无竞价分时接口；竞价序列由 AuctionCollector 自采（见 collector.py）
        return None
