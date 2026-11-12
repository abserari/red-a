"""竞价序列自采器：09:15-09:25 每 ~15 秒轮询快照，拼出每只的指示价序列。

竞价时段快照的「现价」即虚拟撮合价、「累计量」即累计指示量，
序列点格式：(时间 HH:MM:SS, 指示价, 累计量-股)。
结果落盘 data/auction_series_YYYYMMDD.json，并把 09:25 最终累计量
写入竞价量历史（供量比分母使用）。
"""

import json
import time as time_module
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Dict, List

from . import config

BJ = timezone(timedelta(hours=8))


class AuctionWindowError(RuntimeError):
    """竞价窗口不可用（已过/未到且无法等待）时抛出，调用方应报错退出。"""


def _at(day, hhmmss: str) -> datetime:
    h, m, s = (int(x) for x in hhmmss.split(":"))
    return datetime(day.year, day.month, day.day, h, m, s, tzinfo=BJ)


class AuctionCollector:
    def __init__(self, provider, tcodes: List[str], data_dir: Path,
                 interval: int = None,
                 now_fn: Callable[[], datetime] = None,
                 sleep_fn: Callable[[float], None] = None,
                 log=print):
        self.provider = provider
        self.tcodes = list(tcodes)
        self.data_dir = Path(data_dir)
        self.interval = interval or config.COLLECT_INTERVAL_SEC
        self.now_fn = now_fn or (lambda: datetime.now(BJ))
        self.sleep_fn = sleep_fn or time_module.sleep
        self.log = log

    def run(self, cache=None) -> Path:
        now = self.now_fn()
        if now.weekday() >= 5:
            raise AuctionWindowError("今日为周末，非交易日，不启动自采")
        start = _at(now.date(), config.AUCTION_START)
        end = _at(now.date(), config.AUCTION_END)
        if now > end + timedelta(seconds=30):
            raise AuctionWindowError(
                f"竞价窗口已过（现在 {now.strftime('%H:%M:%S')} > 09:25:30），"
                "拒绝补采/假跑")
        if now < start:
            wait = (start - now).total_seconds()
            self.log(f"距离竞价开始还有 {wait:.0f}s，等待至 09:15...")
            while self.now_fn() < start:
                self.sleep_fn(min(30.0, (start - self.now_fn()).total_seconds()))

        series: Dict[str, list] = {c: [] for c in self.tcodes}
        polls = 0
        while True:
            tick_start = self.now_fn()
            snap = self.provider.get_snapshot_batch(self.tcodes)
            ts = self.now_fn().strftime("%H:%M:%S")
            for tcode, rec in snap.items():
                if tcode in series and rec.get("price", 0) > 0:
                    series[tcode].append(
                        [ts, rec["price"], rec.get("volume_shares", 0)])
            polls += 1
            self.log(f"自采 {ts} 第{polls}轮：{len(snap)} 只")
            if self.now_fn() >= end:
                break
            elapsed = (self.now_fn() - tick_start).total_seconds()
            self.sleep_fn(max(1.0, self.interval - elapsed))

        date_str = now.strftime("%Y%m%d")
        self.data_dir.mkdir(parents=True, exist_ok=True)
        path = self.data_dir / f"auction_series_{date_str}.json"
        payload = {
            "date": now.strftime("%Y-%m-%d"),
            "polls": polls,
            "interval_sec": self.interval,
            "codes": len(self.tcodes),
            "series": series,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False),
                        encoding="utf-8")
        self.log(f"竞价序列已保存：{path}（{polls} 轮）")

        # 最终累计量 → 竞价量历史（量比真实分母的数据积累）
        if cache is not None:
            final_vol = {}
            for tcode, pts in series.items():
                if pts:
                    final_vol[tcode] = pts[-1][2]
            cache.record_auction_volumes(now.strftime("%Y-%m-%d"), final_vol)
        return path


def load_series(data_dir: Path, date: str) -> Dict[str, list]:
    """读取某日自采序列 {tcode: [[时间, 价, 累计量], ...]}，不存在返回 {}。"""
    path = Path(data_dir) / f"auction_series_{date.replace('-', '')}.json"
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return {k: [tuple(x) for x in v]
                for k, v in payload.get("series", {}).items()}
    except (ValueError, OSError):
        return {}
