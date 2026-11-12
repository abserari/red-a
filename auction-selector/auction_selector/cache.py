"""本地缓存：股票池、日K（CSV）、竞价量历史。全部落在 data/ 下（不入仓）。"""

import csv
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

BJ = timezone(timedelta(hours=8))
BAR_FIELDS = ["tcode", "date", "open", "close", "high", "low",
              "volume", "amount", "turnover"]
KEEP_BARS = 40  # 每只保留最近交易日数


def today_str() -> str:
    return datetime.now(BJ).strftime("%Y-%m-%d")


class LocalCache:
    def __init__(self, data_dir: Path):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.universe_path = self.dir / "universe.json"
        self.bars_path = self.dir / "bars.csv"
        self.auction_vol_path = self.dir / "auction_vol_history.json"

    # ---------- 股票池 ----------
    def save_universe(self, universe: List[Dict]):
        payload = {"fetched_at": datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S"),
                   "stocks": universe}
        self.universe_path.write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    def load_universe(self) -> List[Dict]:
        if not self.universe_path.exists():
            return []
        try:
            return json.loads(
                self.universe_path.read_text(encoding="utf-8")).get("stocks", [])
        except (ValueError, OSError):
            return []

    # ---------- 日K ----------
    def load_bars(self) -> Dict[str, List[Dict]]:
        bars: Dict[str, List[Dict]] = {}
        if not self.bars_path.exists():
            return bars
        with open(self.bars_path, newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                try:
                    bars.setdefault(row["tcode"], []).append({
                        "date": row["date"],
                        "open": float(row["open"]), "close": float(row["close"]),
                        "high": float(row["high"]), "low": float(row["low"]),
                        "volume": float(row["volume"]),
                        "amount": float(row["amount"]),
                        "turnover": float(row["turnover"]),
                    })
                except (TypeError, ValueError):
                    continue
        for v in bars.values():
            v.sort(key=lambda b: b["date"])
        return bars

    def save_bars(self, bars: Dict[str, List[Dict]]):
        tmp = self.bars_path.with_suffix(".csv.tmp")
        with open(tmp, "w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=BAR_FIELDS)
            w.writeheader()
            for tcode in sorted(bars):
                for b in bars[tcode][-KEEP_BARS:]:
                    w.writerow({"tcode": tcode, **b})
        os.replace(tmp, self.bars_path)

    def refresh(self, provider, full: bool = False, workers: int = 12,
                log=print) -> Dict:
        """刷新股票池与日K。

        full=True 或无缓存：全量拉 KEEP_BARS+5 根；
        否则增量：每只只拉最近 8 根合并（只补最新交易日）。
        """
        t0 = time.time()
        universe = provider.get_universe()
        if len(universe) < 1000:
            raise RuntimeError(f"股票池拉取异常：仅 {len(universe)} 只，放弃刷新")
        self.save_universe(universe)
        log(f"股票池 {len(universe)} 只")

        old = {} if full else self.load_bars()
        want = KEEP_BARS + 5 if (full or not old) else 8
        merged: Dict[str, List[Dict]] = {k: list(v) for k, v in old.items()}
        lock = threading.Lock()
        stats = {"ok": 0, "fail": 0, "new_bars": 0}

        def job(stock):
            tcode = stock["tcode"]
            try:
                rows = provider.get_daily_bars(tcode, days=want)
            except Exception:
                rows = []
            with lock:
                if not rows:
                    stats["fail"] += 1
                    return
                stats["ok"] += 1
                by_date = {b["date"]: b for b in merged.get(tcode, [])}
                for b in rows:
                    if b["date"] not in by_date:
                        stats["new_bars"] += 1
                    by_date[b["date"]] = b
                merged[tcode] = sorted(by_date.values(),
                                       key=lambda b: b["date"])[-KEEP_BARS:]

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(job, s) for s in universe]
            for i, fut in enumerate(as_completed(futs), 1):
                fut.result()
                if i % 1000 == 0:
                    log(f"  日K进度 {i}/{len(universe)}...")
        self.save_bars(merged)
        stats["universe"] = len(universe)
        stats["elapsed_sec"] = round(time.time() - t0, 1)
        log(f"日K刷新完成：成功 {stats['ok']}，失败 {stats['fail']}，"
            f"新增K线 {stats['new_bars']} 根，用时 {stats['elapsed_sec']}s")
        return stats

    # ---------- 竞价量历史（量比分母：近5日竞价成交量均值） ----------
    def load_auction_volumes(self) -> Dict[str, Dict[str, float]]:
        if not self.auction_vol_path.exists():
            return {}
        try:
            return json.loads(self.auction_vol_path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            return {}

    def record_auction_volumes(self, date: str, volumes: Dict[str, float]):
        hist = self.load_auction_volumes()
        for tcode, vol in volumes.items():
            if vol and vol > 0:
                hist.setdefault(tcode, {})[date] = float(vol)
                # 每只只留最近 10 个交易日
                keep = sorted(hist[tcode])[-10:]
                hist[tcode] = {d: hist[tcode][d] for d in keep}
        self.auction_vol_path.write_text(
            json.dumps(hist, ensure_ascii=False), encoding="utf-8")

    def avg_auction_volume(self, tcode: str, days: int = 5) -> float:
        """近 N 个有记录交易日的竞价成交量均值（股）；无记录返回 0。"""
        hist = self.load_auction_volumes().get(tcode, {})
        if not hist:
            return 0.0
        dates = sorted(hist)[-days:]
        vals = [hist[d] for d in dates if hist[d] > 0]
        return sum(vals) / len(vals) if vals else 0.0
