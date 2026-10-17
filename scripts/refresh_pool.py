#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""双线刷池：① 反复重点频道标签；② 多城市 × 关键词 × 薪资档 重复搜索。

为什么是「双线」
----------------
实测（2026-10-14，两轮共 3000+ 条）：
- 频道标签的岗位会被平台**轮换**，同一标签每重点一轮就吐出一批新的，
  但单轮增量有限（首轮 +13、单轮最高 +26），靠滚动深度是刷不出量的
  ——「查看更多」只指向 App，网页端滚到底不再加载；
- 真正的大头是**多城市搜索**：同一天同一批关键词换城市/薪资档，
  单轮贡献 +331，是频道线的 25 倍。
两者叠加才是稳定的岗位供给。

用法
----
    # 双线全跑（默认）
    python3 refresh_pool.py

    # 只轮刷频道标签（反复重点）
    python3 refresh_pool.py --mode channel --ch-passes 3

    # 只做多城市搜索，指定城市与关键词
    python3 refresh_pool.py --mode search \
        --cities 北京,上海,深圳 \
        --kws "AI产品经理,大模型产品经理,Agent产品经理"

    # 提高每块滚动轮数（更慢但更全）
    python3 refresh_pool.py --rounds 8 --ch-rounds 10

参数也可用环境变量给定（BOSS_MODE / BOSS_CITIES / BOSS_KWS / BOSS_ROUNDS /
BOSS_CH_ROUNDS / BOSS_CH_PASSES），命令行参数优先。

产出：<BOSS_APPLY_HOME>/pool.json 与 src.json（增量合并，不覆盖已有岗位）。
注意：需要 Kimi 浏览器桥接扩展处于已连接状态；遇到风控会立即停止。
"""

import argparse
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths                     # noqa: E402
import run_pipeline as rp        # noqa: E402
import webbridge as wb           # noqa: E402

SESSION = "boss-zhipin"

CITY_CODES = {
    "北京": "101010100", "上海": "101020100", "广州": "101280100",
    "深圳": "101280600", "杭州": "101210100",
    # 2026-10-15 用户同意扩城
    "成都": "101270100", "南京": "101190100", "武汉": "101200100", "苏州": "101190400",
}

#: 未指定关键词时的兜底（画像 keywords 为空时使用）
FALLBACK_KWS = [
    "AI产品经理", "AI解决方案", "大模型产品经理", "Agent产品经理",
    "AI产品专家", "AI应用产品", "AI商业化", "智能体产品经理",
]


def _env(name, default=None):
    v = os.environ.get(name)
    return v if v not in (None, "") else default


def _split(v):
    return [x.strip() for x in (v or "").split(",") if x.strip()]


def main():
    ap = argparse.ArgumentParser(
        description="双线刷池：频道标签轮刷 + 多城市搜索（反复运行以获取更新的岗位）")
    ap.add_argument("--mode", default=_env("BOSS_MODE", "both"),
                    choices=["both", "channel", "search"], help="刷哪条线（默认 both）")
    ap.add_argument("--profile", default=None, help="画像 JSON（默认用已配置的个人画像）")
    ap.add_argument("--cities", default=_env("BOSS_CITIES"), help="逗号分隔，如 北京,上海")
    ap.add_argument("--kws", default=_env("BOSS_KWS"), help="逗号分隔的搜索关键词")
    ap.add_argument("--rounds", type=int, default=int(_env("BOSS_ROUNDS", 6)),
                    help="每个搜索块的滚动轮数（默认 6）")
    ap.add_argument("--ch-rounds", type=int, default=int(_env("BOSS_CH_ROUNDS", 8)),
                    help="每个频道标签的滚动轮数（默认 8）")
    ap.add_argument("--ch-passes", type=int, default=int(_env("BOSS_CH_PASSES", 2)),
                    help="频道标签重复重点的遍数（默认 2）")
    a = ap.parse_args()

    paths.ensure_home()
    profile_path = paths.resolve_profile(a.profile)   # 未配置会直接拦下并给引导
    profile = rp.load_json(profile_path, {})

    channels = profile.get("channels") or []
    use_recommend = bool(profile.get("use_recommend_tab"))
    cities = _split(a.cities) or [c.get("name") for c in (profile.get("cities") or [])]
    kws = _split(a.kws) or (profile.get("keywords") or [])[:8] or FALLBACK_KWS
    tiers = profile.get("salary_tiers") or []

    try:
        addr = wb.ensure_daemon()
    except wb.BridgeError as e:
        print(f"[环境未就绪] {e}", flush=True)
        print("  可先运行 python3 scripts/doctor.py 做环境体检", flush=True)
        sys.exit(2)
    ok, msg = wb.check_extension(addr)
    print(f"[env] {msg}", flush=True)
    if not ok:
        print("浏览器桥接扩展未连接，无法继续。先运行 python3 scripts/doctor.py 排查。",
              file=sys.stderr, flush=True)
        return 2

    pool = rp.load_json(paths.POOL, {})
    src_map = rp.load_json(paths.SRC, {})
    start = len(pool)
    print(f"[start] 池={start} mode={a.mode} 城市={cities} 关键词={len(kws)} "
          f"薪资档={[t.get('label') for t in tiers]}", flush=True)

    def do_channels():
        targets = [("推荐", True)] if use_recommend else []
        targets += [(c, False) for c in channels]
        if not targets:
            print("[skip] 画像没有配置频道标签，跳过频道线", flush=True)
            return
        for p in range(a.ch_passes):
            print(f"===== 频道标签 第 {p + 1}/{a.ch_passes} 遍 =====", flush=True)
            for name, is_rec in targets:
                try:
                    n = rp.collect_channel_chunk(
                        name, a.ch_rounds, SESSION, addr, pool, paths.POOL,
                        src_map=src_map, src_path=paths.SRC, is_recommend=is_rec)
                    print(f"[标签 {name}] +{n} (池={len(pool)})", flush=True)
                except rp.RiskHalt as e:      # noqa: PERF203
                    print(f"[RISK] {name}: {e}", flush=True)
                    raise
                except Exception as e:
                    print(f"[ERR] {name}: {type(e).__name__}: {e}", flush=True)
                time.sleep(1.5)

    def do_search():
        for city in cities:
            code = CITY_CODES.get(city, city)
            for kw in kws:
                for t in (tiers or [{"code": "", "label": "不限"}]):
                    tcode = str(t.get("code") or "")
                    try:
                        n = rp.collect_chunk(
                            code, kw, a.rounds, SESSION, addr, pool, paths.POOL,
                            salary_code=tcode, src_tag=f"search:{tcode}",
                            src_map=src_map, src_path=paths.SRC)
                        print(f"[搜索 {city}/{kw}@{t.get('label')}] +{n} "
                              f"(池={len(pool)})", flush=True)
                    except rp.RiskHalt as e:  # noqa: PERF203
                        print(f"[RISK] {city}/{kw}: {e}", flush=True)
                        raise
                    except Exception as e:
                        print(f"[ERR] {city}/{kw}: {type(e).__name__}: {e}", flush=True)
                    time.sleep(1.0)

    try:
        if a.mode in ("both", "channel"):
            do_channels()
        if a.mode in ("both", "search"):
            do_search()
    except rp.RiskHalt:
        print("[HALT] 命中风控，已停止。请人工查看页面后决定是否继续。", flush=True)

    rp.save_json(paths.POOL, pool)
    rp.save_json(paths.SRC, src_map)
    print(f"DONE {start} -> {len(pool)} (+{len(pool) - start})", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
