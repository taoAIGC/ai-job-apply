#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""抓取候选岗位的 JD 全文，供 AI 逐条分析后生成个性化打招呼话术。

**只读操作**：只浏览详情页抓取文本，绝不点击「沟通」，不产生任何触达、不消耗当日额度。

三段式流程（用户 2026-10-12 要求：话术必须逐条读 JD 由 AI 生成，不得从模板里挑）：

  1) 抓 JD    python3 scripts/fetch_jd.py --profile assets/profile-template.json --limit 20
              → 产出 <BOSS_APPLY_HOME>/jd.json（每条的 标题/公司/薪资/JD 正文/英语要求）
  2) AI 生成  读 <BOSS_APPLY_HOME>/jd.json → 逐条分析 JD → 写 <BOSS_APPLY_HOME>/messages.json
              （由对话中的 AI 完成；格式见 references/zhipin-dom-and-flow.md）
  3) 发送     python3 scripts/send_greetings.py --profile assets/profile-template.json --target 520
              默认只投「有话术」的岗位；缺话术的岗位跳过，不发群发式模板。

挑选顺序与投递一致：频道岗位（推荐/求职意向标签）优先 → 50K以上档 → 20-50K档。
"""
import argparse
import os
import random
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths                    # noqa: E402
import webbridge as wb          # noqa: E402
import send_greetings as sg     # noqa: E402
import run_pipeline as rp       # noqa: E402  复用 select_candidates / load_json / save_json


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None,
                    help="简历画像 JSON；默认用 %s" % paths.PROFILE)
    ap.add_argument("--pool", default=paths.POOL)
    ap.add_argument("--state", default=paths.STATE)
    ap.add_argument("--skip-file", default=paths.SKIPPED)
    ap.add_argument("--src-file", default=paths.SRC)
    ap.add_argument("--jd-file", default=paths.JD, help="JD 库（抓取结果落盘处）")
    ap.add_argument("--messages", default=paths.MESSAGES, help="AI 话术文件（已有话术的岗位不再重复抓）")
    ap.add_argument("--limit", type=int, default=15, help="本轮最多抓几条（建议 10-20，便于 AI 逐条分析）")
    ap.add_argument("--session", default="boss-zhipin")
    ap.add_argument("--refresh", action="store_true", help="已抓过的岗位也重新抓一次")
    ap.add_argument("--min-delay", type=float, default=2.5)
    ap.add_argument("--max-delay", type=float, default=5.0)
    a = ap.parse_args()
    paths.ensure_home()
    a.profile = paths.resolve_profile(a.profile)

    profile = rp.load_json(a.profile, {})
    pool = rp.load_json(a.pool, {})
    sg.migrate_state(a.state)
    contacted = sg.load_state_ids(a.state)
    skipped = {sg.job_id(x) for x in rp.load_json(a.skip_file, [])}
    src_map = rp.load_json(a.src_file, {})
    jd_db = rp.load_json(a.jd_file, {})
    msgs = sg.load_ai_messages(a.messages)

    sf = profile.get("salary_filter") or {}
    tiers = profile.get("salary_tiers") or []
    tier_order = {"search:" + t.get("code", ""): i for i, t in enumerate(tiers)}
    markers = profile.get("exclude_text_markers", ["元/天", "天/周", "在校"])

    cands = rp.select_candidates(profile, pool, contacted, markers,
                                 int(sf.get("min_k", 0) or 0), sf.get("mode", "upper"),
                                 bool(sf.get("strict", False)),
                                 src_map=src_map, tier_order=tier_order)

    todo = []
    for j in cands:
        jid = sg.job_id(j["href"])
        if jid in skipped or jid in msgs:
            continue                                  # 已跳过 / 已有话术 → 不必再抓
        if not a.refresh and (jd_db.get(jid) or {}).get("jd"):
            continue                                  # 已抓过且 JD 非空
        todo.append(j)

    print(f"池 {len(pool)} | 候选 {len(cands)} | 已有话术 {len(msgs)} 条 | "
          f"JD 库 {len(jd_db)} 条 | 本轮待抓 {min(len(todo), a.limit)} 条", flush=True)
    if not todo:
        print("没有需要抓取的岗位（候选都已抓过 JD 或已有话术）。", flush=True)
        return

    todo = todo[: a.limit]

    try:
        addr = wb.ensure_daemon()
    except wb.BridgeError as e:
        print(f"[环境未就绪] {e}", flush=True)
        print("  可先运行 python3 scripts/doctor.py 做环境体检", flush=True)
        sys.exit(2)
    ok, msg = wb.check_extension(addr)
    print(f"[env] {msg}", flush=True)
    if not ok:
        sys.exit(2)

    got, empty = 0, 0
    for i, j in enumerate(todo, 1):
        href, title = j["href"], j["title"]
        try:
            wb.navigate("https://www.zhipin.com" + href, a.session, addr)
        except wb.BridgeError as e:
            print(f"  [{i}/{len(todo)}] nav fail: {title} :: {e}", flush=True)
            continue
        time.sleep(random.uniform(a.min_delay, a.max_delay))

        rk = sg.risk_hit_text(a.session, addr)
        if rk:
            print("!!! 命中平台风控提示，停止抓取（本轮为只读操作，未产生任何触达）", flush=True)
            print(f"    命中原文: {rk[:160]}", flush=True)
            break

        jd = sg.extract_jd(a.session, addr)
        if not (jd or {}).get("jd"):
            time.sleep(1.5)
            jd = sg.extract_jd(a.session, addr)       # 详情页偶发延迟渲染，重试一次

        rec = {
            "href": href,
            "title": (jd or {}).get("title") or title,
            "company": (jd or {}).get("company", ""),
            "salary": (jd or {}).get("salary") or j.get("salary", ""),
            "src": j.get("src", ""),
            "jd": (jd or {}).get("jd", ""),
            "english_hit": sg.jd_requires_english((jd or {}).get("jd", "")),
            "not_fit_hit": sg.jd_not_fit((jd or {}).get("jd", "")),
            "fetched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        # 同公司 + 同 JD 的重复发布（BOSS 上常见）：标注 dup_of，AI 只给其中一个写话术，
        # 避免同一家公司同一个岗位被打扰两次
        ckey, jkey = rec["company"].strip(), rec["jd"][:60]
        if jkey:
            for other_id, other in jd_db.items():
                if other_id == sg.job_id(href):
                    continue
                if other.get("company", "").strip() == ckey and other.get("jd", "")[:60] == jkey:
                    rec["dup_of"] = other_id
                    break

        jd_db[sg.job_id(href)] = rec
        rp.save_json(a.jd_file, jd_db)                # 立即落盘，中断不丢
        if rec["jd"]:
            got += 1
        else:
            empty += 1
        flag = ""
        if rec["english_hit"]:
            flag += f" | 英语要求: {rec['english_hit'][:16]}"
        if rec["not_fit_hit"]:
            flag += f" | 岗位错配: {rec['not_fit_hit'][:24]}"
        if rec.get("dup_of"):
            flag += f" | 重复发布(同公司同JD): {rec['dup_of'][:10]}…"
        print(f"  [{i}/{len(todo)}] {'OK' if rec['jd'] else 'JD空'} {rec['title']} | "
              f"{rec['company']} | {rec['salary']} | JD {len(rec['jd'])} 字{flag}", flush=True)
        time.sleep(random.uniform(a.min_delay, a.max_delay))

    print(f"\n抓取完成：成功 {got} 条，JD 为空 {empty} 条；JD 库累计 {len(jd_db)} 条 → {a.jd_file}", flush=True)
    print(f"下一步：由 AI 读取 {a.jd_file}，逐条分析 JD 后写入 {a.messages}", flush=True)


if __name__ == "__main__":
    main()
