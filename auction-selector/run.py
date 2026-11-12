#!/usr/bin/env python3
"""集合竞价选股系统（数据源无关版）运行入口。

模式：
  refresh   增量刷新日K缓存（--full 强制全量）
  prefilter 用本地缓存生成当日候选池 output/prefilter_YYYYMMDD.json
  morning   早盘完整流程（须在 09:25 前启动；非交易时段明确报错退出）
  selftest  离线自检
"""

import argparse
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent
sys.path.insert(0, str(BASE))

from auction_selector import engine, prefilter, selftest  # noqa: E402
from auction_selector.cache import LocalCache  # noqa: E402
from auction_selector.collector import AuctionWindowError  # noqa: E402
from auction_selector.provider import TencentProvider  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="集合竞价选股系统（数据源无关版）")
    ap.add_argument("--mode", required=True,
                    choices=["refresh", "prefilter", "morning", "selftest"])
    ap.add_argument("--full", action="store_true",
                    help="refresh 时强制全量拉取")
    args = ap.parse_args()

    cache = LocalCache(BASE / "data")

    if args.mode == "refresh":
        stats = cache.refresh(TencentProvider(), full=args.full)
        print(f"refresh 完成：{stats}")
        return 0

    if args.mode == "prefilter":
        universe = cache.load_universe()
        bars_map = cache.load_bars()
        if not universe or not bars_map:
            print("错误：本地缓存为空，请先运行 --mode refresh", file=sys.stderr)
            return 2
        result = prefilter.build_pool(universe, bars_map,
                                      save_dir=BASE / "output")
        print(f"候选池已生成：{result['_path']}，池大小 {result['pool_size']}"
              f"（全市场 {result['total_stocks']} 只）")
        print(f"排除统计：{result['excluded']}")
        return 0

    if args.mode == "morning":
        try:
            result = engine.run_morning(TencentProvider(), cache, BASE)
        except (engine.MorningError, AuctionWindowError) as e:
            print(f"错误：{e}", file=sys.stderr)
            return 2
        print(f"morning 完成：主板 Top {len(result['top_main'])} 只，"
              f"双创 Top {len(result['top_gem_star'])} 只")
        return 0

    if args.mode == "selftest":
        ok, lines = selftest.run_selftest(BASE)
        print("\n".join(lines))
        return 0 if ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
