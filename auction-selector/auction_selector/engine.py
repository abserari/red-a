"""早盘完整流程（morning 模式）：候选池、自采、最终快照、因子过滤打分、输出。

流程与原系统三阶段语义对应：
- 阶段1：池内全量快照因子 + 硬过滤
- 阶段2：按量比取前 30 只为 finalist，叠加自采序列因子，
  撤单率大于 0.7 的直接剔除（同原系统二阶段）
- 阶段3：finalist 内百分位打分，分主板/双创输出 Top 名单
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

from auction_selector import config, factors, prefilter
from auction_selector.cache import LocalCache
from auction_selector.collector import AuctionCollector, load_series
from auction_selector.provider import board_of

BJ = timezone(timedelta(hours=8))


class MorningError(RuntimeError):
    pass


def _benchmark_of(pool_rec):
    return {
        "avg_5d_vol": pool_rec.get("avg_5d_vol", 0),
        "avg_5d_amount": pool_rec.get("avg_5d_amount", 0),
        "close": pool_rec.get("close", 0),
        "name": pool_rec.get("name", ""),
        "board": pool_rec.get("board", ""),
    }


def run_morning(provider, cache, base_dir, log=print):
    base_dir = Path(base_dir)
    data_dir = base_dir / "data"
    output_dir = base_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now(BJ)
    today = now.strftime("%Y-%m-%d")
    if now.weekday() >= 5:
        raise MorningError("今日为周末，非交易日，morning 模式不运行")
    if now.strftime("%H:%M:%S") > "09:25:30":
        raise MorningError(
            "已过竞价窗口（现在 " + now.strftime("%H:%M:%S") + "），"
            "morning 需要在 09:25 前启动，拒绝盘后假跑")

    pool = prefilter.load_pool(output_dir, today)
    if not pool:
        log("未找到当日候选池，用本地日K缓存现生成...")
        universe = cache.load_universe()
        bars_map = cache.load_bars()
        if not universe or not bars_map:
            raise MorningError("本地缓存为空：请先运行 run.py --mode refresh "
                               "再运行 --mode prefilter")
        pool = prefilter.build_pool(universe, bars_map, save_dir=output_dir)
    pool_recs = pool.get("pool", [])
    if not pool_recs:
        raise MorningError("候选池为空，终止")
    log("候选池 " + str(len(pool_recs)) + " 只（" + str(pool.get("date")) + "）")
    tcodes = [r["tcode"] for r in pool_recs]
    benchmarks = {r["tcode"]: _benchmark_of(r) for r in pool_recs}

    collector = AuctionCollector(provider, tcodes, data_dir, log=log)
    collector.run(cache=cache)
    series_map = load_series(data_dir, today)

    snapshot = provider.get_snapshot_batch(tcodes)
    log("最终快照 " + str(len(snapshot)) + " 只")
    if len(snapshot) < len(tcodes) * 0.5:
        raise MorningError("最终快照严重不完整（" + str(len(snapshot)) + "/"
                           + str(len(tcodes)) + "），数据源疑似故障，终止")

    cache.record_auction_volumes(
        today, {c: r.get("volume_shares", 0) for c, r in snapshot.items()})

    performance = {}
    for tcode, rec in snapshot.items():
        bm = benchmarks.get(tcode, {})
        pre = rec.get("preclose") or bm.get("close") or 0
        px = rec.get("open") or rec.get("price") or 0
        performance[tcode] = {
            "pct_chg": (px - pre) / pre * 100 if pre > 0 and px > 0 else 0.0}
    sector_map = {}

    all_factors = []
    for tcode, rec in snapshot.items():
        bm = benchmarks.get(tcode)
        if bm is None:
            continue
        hist_avg = cache.avg_auction_volume(tcode, days=5)
        if hist_avg > 0:
            denom, fallback = hist_avg, False
        else:
            denom, fallback = bm["avg_5d_vol"] * 0.05, True
        all_factors.append(factors.build_factors(
            rec, bm, series_map.get(tcode), denom, fallback,
            sector_map, performance))
    log("全池因子 " + str(len(all_factors)) + " 只")

    passed = []
    for f in all_factors:
        ok, reason = factors.hard_filter(f)
        f["_filter_reason"] = reason
        if ok:
            passed.append(f)
    log("硬过滤通过 " + str(len(passed)) + " 只")

    passed.sort(key=lambda f: f["auction_volume_ratio"], reverse=True)
    finalists = []
    for f in passed[:config.SCREEN["candidate_count"]]:
        cancel = f.get("cancel_ratio")
        if cancel is not None and cancel > config.FILTER["stage2_cancel_drop"]:
            log("  二阶段剔除 " + f["name"] + "(" + f["code"] + ")：撤单率 "
                + format(cancel, ".1%"))
            continue
        finalists.append(f)
    log("finalist " + str(len(finalists)) + " 只")

    factors.score_all(finalists)
    main_top = [f for f in finalists
                if board_of(f["code"]) == "主板"][:config.OUTPUT["top_n_main"]]
    gem_top = [f for f in finalists
               if board_of(f["code"]) in ("创业板", "科创板")][:config.OUTPUT["top_n_gem"]]

    def clean(f, rank):
        out = {"rank": rank}
        for k in ("tcode", "code", "name", "board", "match_price", "pct_chg",
                  "auction_volume_ratio", "vol_ratio_fallback",
                  "auction_amount", "bid_surplus_ratio", "cancel_ratio",
                  "aggression_slope", "tail_acceleration",
                  "sector_linkage", "has_auction_data", "score"):
            out[k] = f.get(k)
        return out

    result = {
        "date": today,
        "generated_at": datetime.now(BJ).strftime("%Y-%m-%d %H:%M:%S"),
        "pool_size": len(pool_recs),
        "snapshot_size": len(snapshot),
        "hard_filter_passed": len(passed),
        "finalists": len(finalists),
        "top_main": [clean(f, i + 1) for i, f in enumerate(main_top)],
        "top_gem_star": [clean(f, i + 1) for i, f in enumerate(gem_top)],
        "all_finalists": [clean(f, i + 1) for i, f in enumerate(finalists)],
    }
    date_nodash = today.replace("-", "")
    rec_path = output_dir / ("recommendations_" + date_nodash + ".json")
    rec_path.write_text(json.dumps(result, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    rep_path = output_dir / ("report_" + date_nodash + ".txt")
    rep_path.write_text(render_report(result), encoding="utf-8")
    log("已写出 " + str(rec_path) + " 与 " + str(rep_path))
    return result


def render_report(result):
    lines = [
        "=" * 72,
        "集合竞价选股推荐报告",
        "日期: " + result["date"] + "  生成时间: " + result["generated_at"],
        "候选池 " + str(result["pool_size"]) + " 只，硬过滤通过 "
        + str(result["hard_filter_passed"]) + " 只，finalist "
        + str(result["finalists"]) + " 只",
        "=" * 72,
    ]

    def section(title, rows):
        lines.append("")
        lines.append("【" + title + "】")
        if not rows:
            lines.append("（无）")
        for r in rows:
            slope = ("-" if r["aggression_slope"] is None
                     else format(r["aggression_slope"], "+.4f"))
            cancel = ("-" if r["cancel_ratio"] is None
                      else format(r["cancel_ratio"], ".1%"))
            fb = "（量比为回退口径）" if r["vol_ratio_fallback"] else ""
            lines.append(
                format(r["rank"], ">2") + ". " + r["name"] + "(" + r["code"]
                + ") [" + r["board"] + "] 撮合 "
                + format(r["match_price"], ".2f") + " 涨幅 "
                + format(r["pct_chg"], "+.2f") + "% 量比 "
                + format(r["auction_volume_ratio"], ".1f") + fb + " 竞价额 "
                + format(r["auction_amount"], ",.0f") + "万 封单比 "
                + format(r["bid_surplus_ratio"], ".2f") + " 斜率 " + slope
                + " 撤单率 " + cancel + " 得分 "
                + format(r["score"], ".1f"))

    section("主板 Top", result["top_main"])
    section("创业板/科创板 Top", result["top_gem_star"])
    lines += ["", "=" * 72,
              "说明：量比回退口径=5日日均量乘5%（无竞价量历史时）；"
              "斜率/撤单率为「-」表示该股无真实竞价序列。",
              "风险提示：以上为信息系统输出，仅供参考，不构成投资建议。",
              "=" * 72]
    return "\n".join(lines)
