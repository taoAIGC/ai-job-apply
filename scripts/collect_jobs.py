#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段一：在 BOSS 直聘搜索页滚动收集岗位池。

用法：
  python3 collect_jobs.py --keywords "AI产品经理" "AI解决方案" \
      --cities 101010100 101020100 101280100 --rounds 6 --out <BOSS_APPLY_HOME>/pool.json

产出：<BOSS_APPLY_HOME>/pool.json  {"<job_detail路径>": "<卡片文本>", ...}
说明：--cities 可传多个城市编码（北京=101010100，上海=101020100，广州=101280100，
      深圳=101280600，杭州=101210100）；也兼容旧的 --city 单城市参数。
"""
import argparse
import json
import os
import sys
import time
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402
import webbridge as wb  # noqa: E402

SEARCH_URL = "https://www.zhipin.com/web/geek/jobs?query={q}&city={city}"

# BOSS 的列表卡片：div.job-card-wrap（不是 li），内部含 a[href^=/job_detail/]
EXTRACT_CARDS = """
(() => {
  const cards=[...document.querySelectorAll('[class*=job-card-wrap]')];
  const out=cards.map(el=>{
    const a=el.querySelector('a');
    return {href:a?a.getAttribute('href'):'', text:(el.innerText||'').replace(/\\s*\\n\\s*/g,' | ').trim()};
  });
  return JSON.stringify(out);
})()
"""

SCROLL_BOTTOM = "(() => { window.scrollTo(0, document.body.scrollHeight); return 1; })()"

DEFAULT_KEYWORDS = [
    "AI产品经理", "AI产品专家", "AI解决方案", "AI商业化",
    "大模型产品经理", "AI应用", "Agent产品经理", "AI运营",
    "AI赋能", "人工智能产品经理", "AIGC产品经理",
]

# 常用城市编码
CITY_CODES = {
    "北京": "101010100", "上海": "101020100", "广州": "101280100",
    "深圳": "101280600", "杭州": "101210100",
    # 2026-10-15 用户同意扩城
    "成都": "101270100", "南京": "101190100", "武汉": "101200100", "苏州": "101190400",
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--keywords", nargs="*", default=DEFAULT_KEYWORDS)
    ap.add_argument("--city", default=None, help="单城市编码（兼容旧用法），北京=101010100")
    ap.add_argument("--cities", nargs="*", default=None,
                    help="多城市编码，如 101010100 101020100 101280100")
    ap.add_argument("--rounds", type=int, default=6, help="每个关键词向下滚动加载的轮数")
    ap.add_argument("--out", default=paths.POOL)
    ap.add_argument("--session", default="boss-zhipin")
    a = ap.parse_args()
    paths.ensure_home()

    cities = a.cities or ([a.city] if a.city else ["101010100"])
    # 允许传中文城市名
    cities = [CITY_CODES.get(c, c) for c in cities]

    try:
        addr = wb.ensure_daemon()
    except wb.BridgeError as e:
        print(f"[环境未就绪] {e}", flush=True)
        print("  可先运行 python3 scripts/doctor.py 做环境体检", flush=True)
        sys.exit(2)
    ok, msg = wb.check_extension(addr)
    print(f"[env] {msg}  城市: {cities}", flush=True)
    if not ok:
        sys.exit(2)

    pool = {}
    if os.path.exists(a.out):  # 支持增量累加
        try:
            pool = json.load(open(a.out, encoding="utf-8"))
        except Exception:
            pool = {}

    for city in cities:
        for kw in a.keywords:
            url = SEARCH_URL.format(q=urllib.parse.quote(kw), city=city)
            try:
                wb.navigate(url, a.session, addr)
            except wb.BridgeError as e:
                print(f"[navigate fail] {city}/{kw}: {e}", flush=True)
                continue
            time.sleep(4)
            for _ in range(a.rounds):
                val = wb.ev(EXTRACT_CARDS, a.session, addr)
                if val:
                    try:
                        for it in json.loads(val):
                            h = it.get("href") or ""
                            if h and h not in pool:
                                pool[h] = it.get("text", "")
                    except Exception:
                        pass
                wb.ev(SCROLL_BOTTOM, a.session, addr)
                time.sleep(2.5)
            print(f"[{city}/{kw}] pool={len(pool)}", flush=True)

    json.dump(pool, open(a.out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"DONE unique={len(pool)} -> {a.out}")


if __name__ == "__main__":
    main()
