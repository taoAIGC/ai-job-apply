#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""流水线模式：小批量「边收集、边投递」，模拟真实用户节奏，降低风控风险。

与旧模式（先收 1000 个池、再批量发 50 条）的区别：
  1. 收集与投递交替进行，不再长时间只做一件事；
  2. 每个周期只收集 1-2 个「城市×关键词」小块，立即落盘；
  3. 每周期只发少量（默认 4 条），发完即冷却；
  4. 全流程加入拟人化节奏：随机滚动、随机停顿、看 JD 后再点击、
     每若干条来一次长休息、顺序随机化。

用法：
  python3 run_pipeline.py --profile assets/profile-template.json \
      --target 100 --per-cycle 4 --max-cycles 12
  python3 run_pipeline.py ... --dry-run     # 只跑一遍选人逻辑，不发送

设计原则：宁少勿滥；命中风控立即停；状态随时落盘，可断点续跑。
"""
import argparse
import json
import os
import random
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths                    # noqa: E402  统一路径/用户配置
import webbridge as wb          # noqa: E402
import send_greetings as sg     # noqa: E402  复用：parse_title / salary_of / 点击脚本

SEARCH_URL = "https://www.zhipin.com/web/geek/jobs?query={q}&city={city}&salary={salary}"
JOBS_LIST_URL = "https://www.zhipin.com/web/geek/jobs"

EXTRACT_CARDS = """
(() => {
  const cards=[...document.querySelectorAll('[class*=job-card-wrap], li[class*=job-card-box], [class*=job-card-wrapper]')];
  const out=cards.map(el=>{
    const a=el.querySelector('a[href*=\"/job_detail/\"]')||el.querySelector('a');
    return {href:a?a.getAttribute('href'):'', text:(el.innerText||'').replace(/\\s*\\n\\s*/g,' | ').trim()};
  });
  return JSON.stringify(out);
})()
"""

# ---- 频道标签（页面顶部的「推荐」+ 求职意向频道）----
# 用户 2026-10-12 要求：优先投这些标签下的岗位，直到没有可投的，再自行搜索。
# 注意：点击频道后页面 SPA 重渲染会丢失标签栏，因此每个频道都从干净的列表页开始。
TABS_PRESENT = "!!document.querySelector('.expect-list a.expect-item')"

CLICK_RECOMMEND = """
(() => {
  const r = document.querySelector('.c-expect-select a.synthesis');
  if (r) { r.click(); return 'clicked:推荐'; }
  return 'not-found';
})()
"""

CLICK_CHANNEL_TMPL = """
(() => {
  const name = %s;
  const items = [...document.querySelectorAll('.expect-list a.expect-item')];
  for (const it of items) {
    const t = (it.querySelector('.text-content')||it).innerText.trim();
    if (t.startsWith(name)) { it.click(); return 'clicked:'+t; }
  }
  return 'not-found';
})()
"""

CITY_CODES = {
    "北京": "101010100", "上海": "101020100", "广州": "101280100",
    "深圳": "101280600", "杭州": "101210100",
    # 2026-10-15 用户同意扩城
    "成都": "101270100", "南京": "101190100", "武汉": "101200100", "苏州": "101190400",
}

RISK_FILE = paths.RISK


class RiskHalt(Exception):
    """命中平台风控提示，立即熔断整条流水线。"""


def load_json(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(path, obj):
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def risk_hit(session, addr):
    """现场风控体检：返回命中的原文片段（无命中返回 ''）。"""
    return sg.risk_hit_text(session, addr)


def mark_risk(reason, where="", evidence=""):
    """落盘风控事件 + 打印人工处置指引。evidence 为页面上命中的原文片段。"""
    save_json(RISK_FILE, {
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ts": time.time(),
        "where": where,
        "reason": (reason or "")[:200],
        "evidence": (evidence or getattr(sg, "LAST_RISK_TEXT", "") or "")[:300],
    })
    print("\n" + "=" * 62, flush=True)
    print("!!! 触发平台风控提示 —— 已立即熔断，停止一切自动化动作", flush=True)
    print(f"    位置: {where}", flush=True)
    print(f"    提示: {(reason or '')[:120]}", flush=True)
    ev = evidence or getattr(sg, "LAST_RISK_TEXT", "")
    if ev:
        print(f"    命中原文: {ev[:160]}", flush=True)
    print("    已保全: 岗位池/已触达/发送日志均已落盘，可断点续跑", flush=True)
    print("    人工处置建议：", flush=True)
    print("      1) 不要刷新、不要重试、不要继续滚动列表", flush=True)
    print("      2) 关掉自动化标签页，冷却 ≥30 分钟（明显警告建议数小时~次日）", flush=True)
    print("      3) 若出现滑块/验证码，请人工完成一次正常浏览后再恢复", flush=True)
    print("      4) 恢复时降速：--per-cycle 2 --scrolls 2，并加大休息", flush=True)
    print("=" * 62 + "\n", flush=True)


def check_recent_risk(guard_min, force):
    """启动前守卫：近期触发过风控则拒绝启动，防止加重标记。"""
    info = load_json(RISK_FILE, None)
    if not info:
        return True
    age = (time.time() - info.get("ts", 0)) / 60.0
    if age < guard_min and not force:
        print(f"[guard] {age:.0f} 分钟前触发过风控：{info.get('reason','')[:60]}", flush=True)
        print(f"[guard] 冷却期（{guard_min} 分钟）内不启动。确认无碍请加 --force 覆盖。", flush=True)
        return False
    return True


def pause(a, b, note=""):
    t = random.uniform(a, b)
    time.sleep(t)
    return t


def human_read_scroll(session, addr, rounds):
    """拟人化滚动：步长随机、时有回滚、停顿随机。"""
    for _ in range(rounds):
        amt = random.choice([260, 380, 520, 700, 900, 1100])
        wb.ev(f"(() => {{ window.scrollBy(0,{amt}); return window.scrollY; }})()", session, addr)
        pause(1.2, 3.6)
        if random.random() < 0.28:                      # 偶尔往回翻一点，像在比较
            wb.ev(f"(() => {{ window.scrollBy(0,-{random.randint(120,320)}); return window.scrollY; }})()", session, addr)
            pause(0.7, 2.0)


def load_json(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json(path, obj):
    json.dump(obj, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)


def collect_chunk(city, kw, rounds, session, addr, pool, pool_path, salary_code=None,
                  src_tag="", src_map=None, src_path=None):
    """收集一个搜索小块并立即落盘。返回新增数量；命中风控抛 RiskHalt。

    salary_code: 薪资档位参数（407=50K以上, 406=20-50K；与页面「薪资待遇」菜单
    选项一一对应，已实测。菜单下拉经自动化合成事件不可靠，用 URL 参数等效实现，
    页面上会显示相同的已选筛选标签）。
    src_tag: 来源标记（如 "search:407"），写入 src_map 供候选排序（频道优先、档位优先）。
    """
    import urllib.parse
    url = SEARCH_URL.format(q=urllib.parse.quote(kw), city=city, salary=salary_code or "")
    if not salary_code:
        url = url.replace("&salary=", "")
    try:
        wb.navigate(url, session, addr)
    except wb.BridgeError as e:
        print(f"  [collect nav fail] {city}/{kw}: {e}", flush=True)
        return 0
    pause(3.0, 6.0)

    # 进页先做一次风控体检（上次可能已触发提示）——只扫告警区，避免 JD 误伤
    hit = sg.risk_hit_text(session, addr)
    if hit:
        raise RiskHalt(hit)

    before = len(pool)
    human_read_scroll(session, addr, rounds)

    # 滚动后再体检：风控提示多在过度滚动后弹出
    hit = sg.risk_hit_text(session, addr)
    if hit:
        raise RiskHalt(hit)

    val = wb.ev(EXTRACT_CARDS, session, addr)
    if val:
        try:
            for it in json.loads(val):
                h = it.get("href") or ""
                if h and h not in pool:
                    pool[h] = it.get("text", "")
                    if src_map is not None and src_tag:
                        src_map[h] = src_tag
        except Exception:
            pass
    save_json(pool_path, pool)            # 立即落盘，避免中断丢数据
    if src_map is not None and src_path:
        save_json(src_path, src_map)
    added = len(pool) - before
    tier_desc = f"@{src_tag.split(':')[1]}" if src_tag and ":" in src_tag else ""
    print(f"  [collect] {city}/{kw}{tier_desc} +{added} (池={len(pool)})", flush=True)
    return added


def _wait_tabs(session, addr, timeout=24):
    for _ in range(timeout // 2):
        if wb.ev(TABS_PRESENT, session, addr):
            return True
        time.sleep(2)
    return False


def collect_channel_chunk(name, rounds, session, addr, pool, pool_path,
                          src_map=None, src_path=None, is_recommend=False):
    """从频道标签（「推荐」或求职意向频道）收集岗位。返回新增数量。

    每个频道都从干净的列表页开始：点击频道后 SPA 重渲染会丢失标签栏。
    只点击标签、不构造任何搜索 URL。
    """
    wb.navigate(JOBS_LIST_URL, session, addr)
    pause(3.0, 5.0)
    if not _wait_tabs(session, addr):
        print(f"  [channel {name}] 频道标签未渲染，本轮跳过", flush=True)
        return -1                      # -1 = 标签不可用（不算枯竭，下轮再试）

    js = CLICK_RECOMMEND if is_recommend else (CLICK_CHANNEL_TMPL % json.dumps(name))
    r = wb.ev(js, session, addr)
    print(f"  [channel {name}] click -> {r}", flush=True)
    if not r or "clicked" not in str(r):
        return -1
    pause(3.5, 5.5)

    hit = sg.risk_hit_text(session, addr)
    if hit:
        raise RiskHalt(hit)

    src_tag = "channel:" + name
    before = len(pool)
    for i in range(rounds):
        cur = str(wb.ev("(() => location.href)()", session, addr) or "")
        if "/job_detail/" in cur or "/web/geek/chat" in cur:
            print(f"  [channel {name}] 页面被弹走，停止本频道", flush=True)
            break
        hit = sg.risk_hit_text(session, addr)
        if hit:
            raise RiskHalt(hit)
        val = wb.ev(EXTRACT_CARDS, session, addr)
        if val:
            try:
                for it in json.loads(val):
                    h = it.get("href") or ""
                    if h and h not in pool:
                        pool[h] = it.get("text", "")
                        if src_map is not None:
                            src_map[h] = src_tag
            except Exception:
                pass
        human_read_scroll(session, addr, 1)
        save_json(pool_path, pool)
        if src_map is not None and src_path:
            save_json(src_path, src_map)
        pause(1.2, 2.8)
    added = len(pool) - before
    print(f"  [channel {name}] +{added} (池={len(pool)})", flush=True)
    return added


def select_candidates(profile, pool, contacted, markers, min_k, sal_mode, strict=False,
                      src_map=None, tier_order=None):
    """按画像筛岗位。排序：频道岗位优先 → 薪资档位（50K以上先于 20-50K）→ priority 词 → 标题短者先。"""
    excl = re.compile(profile.get("exclude", "$^"), re.I)
    must = re.compile(profile.get("must_any", "."), re.I)
    role = re.compile(profile.get("must_role", "."), re.I)
    prio = re.compile(profile.get("priority", "$^"), re.I)
    # 2026-10-16 用户要求：集团黑名单（阿里/字节/腾讯/蚂蚁系）永久不投
    comp_kw = [str(k) for k in (profile.get("exclude_companies") or [])]
    src_map = src_map or {}
    tier_order = tier_order or {}
    out = []
    blocked_n = 0
    for href, text in pool.items():
        if sg.job_id(href) in contacted:
            continue
        title = sg.parse_title(text)
        if not title:
            continue
        if comp_kw and sg.company_blocked(text, comp_kw):
            blocked_n += 1
            continue
        if any(m in text for m in markers):
            continue
        if excl.search(title) or not must.search(title) or not role.search(title):
            continue
        decoded = sg.salary_of(text)[1]
        if min_k > 0:
            rng = sg.parse_k_range(decoded)
            if not rng:
                continue
            lo, hi = rng
            # strict=True 时边界取严格不等；mode=lower 看起薪（画像层兜底）
            if sal_mode == "lower" and (lo <= min_k if strict else lo < min_k):
                continue
            if sal_mode == "upper" and (hi <= min_k if strict else hi < min_k):
                continue
        src = src_map.get(href, "")
        out.append({"href": href, "title": title, "salary": decoded, "src": src})
    out.sort(key=lambda j: (
        0 if j["src"].startswith("channel") else 1,        # 频道（推荐+意向标签）优先
        tier_order.get(j["src"], 9),                        # 搜索档位：50K以上 → 20-50K
        0 if prio.search(j["title"]) else 1,
        len(j["title"]),
    ))
    if blocked_n:
        print(f"[exclude-companies] 公司黑名单跳过 {blocked_n} 个岗位", flush=True)
    return out


def send_one(job, profile, session, addr, contacted, state_path, log_path, dry=False, no_jd=False,
             ai_msg=None, allow_template=False):
    """发一条定制招呼，拟人化节奏。返回 (ok, verified, reason)。

    ai_msg：AI 逐条读 JD 分析生成的话术（默认唯一话术来源）。
    没有话术且未开 --allow-template 时**不去打扰对方**，直接返回 no-ai-msg。
    """
    href, title = job["href"], job["title"]
    # 实时核对：读盘上的最新已触达（防并发/陈旧快照导致重复投递）
    contacted |= sg.load_state_ids(state_path)
    if sg.job_id(href) in contacted:
        return False, False, "already"
    if not ai_msg and not allow_template:
        return False, False, "no-ai-msg"
    try:
        wb.navigate("https://www.zhipin.com" + href, session, addr)
    except wb.BridgeError as e:
        return False, False, f"nav fail: {e}"
    pause(3.0, 5.5)

    # 风控体检只扫「平台告警区」（弹窗/提示条/整页拦截），不扫 JD 正文——
    # 曾因 JD 里出现「数据爬取」被裸词误伤，导致整条流水线假熔断
    hit = sg.risk_hit_text(session, addr)
    if hit:
        sg.LAST_RISK_TEXT = hit          # 保留命中原文，供日志/落盘取证
        return False, False, "RISK"
    full = wb.ev("(() => document.body.innerText)()", session, addr) or ""
    cap_hit = sg.detect_daily_cap(full)
    if cap_hit:                                # 详情页已提示当日额度用尽
        sg.LAST_CAP_TEXT = sg.read_cap_text(session, addr) or cap_hit
        return False, False, "DAILY_CAP"

    # 抓 JD：① 英语要求高 → 直接跳过（不点沟通、不产生触达）
    #        ② 用于生成「结合岗位描述」的个性化话术（不再只换标题）
    jd = sg.extract_jd(session, addr) if not no_jd else {}
    jd_text = (jd or {}).get("jd", "")
    en_hit = sg.jd_requires_english(jd_text)
    if en_hit:
        return False, False, "skip-jd-english:" + en_hit[:40]
    fit_hit = "" if no_jd else sg.jd_not_fit(jd_text)       # 标题包装成 AI 岗、实为基建类 → 无效岗位
    if fit_hit:
        return False, False, "skip-jd-notfit:" + fit_hit[:40]

    # 像真人一样先扫一眼 JD 再点沟通
    wb.ev(f"(() => {{ window.scrollBy(0,{random.randint(260,620)}); return window.scrollY; }})()", session, addr)
    pause(1.0, 2.6)

    r = wb.ev(sg.CLICK_START, session, addr)
    pause(1.0, 1.8)
    # 「温馨提示：您今天已与N位BOSS沟通，还剩M次沟通机会哦」——软额度提醒弹窗。
    # 它会挡住「立即沟通」的后续流程（继续沟通点不到、页面不跳转）。
    # 处理：点「好」关掉，再重新点一次「立即沟通」才能真正发出招呼语。
    if sg.handle_tip_dialog(session, addr):
        print(f"  [tip] 触发「还剩N次沟通机会」提示，已关闭并重试 → {title}", flush=True)
        pause(1.2, 2.2)
        wb.ev(sg.CLICK_START, session, addr)
        pause(1.6, 2.6)
        r = "clicked"                       # 关掉提示即视为已重新发起沟通
    # 可能出现「今天投递数量达到 N 个了，是否继续投递」：
    #   N < 150 → 点「继续投递」继续；N ≥ 150 → 当日封顶，返回 DAILY_CAP 收尾
    qd = sg.handle_quota_dialog(session, addr)
    if qd == "cap":
        return False, False, "DAILY_CAP"
    if qd == "continued":
        print(f"  [quota] 已达每日投递阈值，已点「继续投递」→ {title}", flush=True)
        pause(1.4, 2.4)
        if r in ("no-btn", "already-contacted"):
            r = wb.ev(sg.CLICK_START, session, addr)
    if r == "no-btn":
        return False, False, "no-btn"
    if r == "already-contacted":
        contacted.add(sg.job_id(href))
        sg.save_json_atomic(state_path, sorted(contacted))
        return False, False, "already"
    pause(2.2, 3.8)

    # 点完「立即沟通」，系统其实已经发出了默认招呼语 —— 从此刻起这条岗位算「已触达」。
    # 后续「继续沟通 + 填定制话术」是增强，失败也不能把它退回候选池（否则重复打招呼）。
    def _finish(send_state, custom, verified, how="", tpl_key="", jd_keys=""):
        contacted.add(sg.job_id(href))
        sg.save_json_atomic(state_path, sorted(contacted))
        log = load_json(log_path, [])
        log.append({"href": href, "title": title, "salary": job.get("salary", ""),
                    "template": tpl_key or key, "ai": bool(ai_msg), "jd_keys": jd_keys,
                    "send": send_state, "custom": custom, "src": job.get("src", ""),
                    "verified": verified, "how": how, "time": time.strftime("%H:%M:%S")})
        save_json(log_path, log)

    # 点完「立即沟通」可能已直接跳到聊天页（新版「留在此页继续沟通」弹窗 / 已沟通过的岗位），
    # 此时无需再点「继续沟通」，直接去填定制话术
    # 标题以详情页真实标题为准（列表页标题偶有截断/改写）
    eff_title = (jd or {}).get("title") or title
    if ai_msg:                                   # 默认路径：用 AI 读 JD 生成的话术
        msg, meta, key = ai_msg, {"template": "ai", "jd_keys": "ai"}, "ai"
    else:                                        # 仅 --allow-template 时兜底
        msg, meta = sg.compose_message(profile, eff_title, jd_text=jd_text)
        key = meta.get("template", "default")

    cur = str(wb.ev("(() => location.href)()", session, addr) or "")
    if "/web/geek/chat" not in cur:
        cr = wb.ev(sg.CLICK_CONTINUE, session, addr)
        if cr != "ok":
            qd = sg.handle_quota_dialog(session, addr)
            if qd == "cap":
                return False, False, "DAILY_CAP"
            if qd == "continued":
                pause(1.5, 2.5)
                cr = wb.ev(sg.CLICK_CONTINUE, session, addr)
        if cr != "ok":
            # 再兜一层：软额度「温馨提示」可能恰好在此刻才弹出来
            if sg.handle_tip_dialog(session, addr):
                pause(1.5, 2.5)
                wb.ev(sg.CLICK_START, session, addr)
                pause(1.6, 2.6)
                cr = "ok"
        if cr != "ok":
            # 数据严谨性：回详情页复核——只有真的出现了「继续沟通」，才证明招呼语已发出。
            # 否则（如被提示弹窗挡住）不得记为已触达，退回候选池等下轮重试。
            greeted = wb.ev(
                "(() => { const c=[...document.querySelectorAll('a,button,div,span')]"
                ".filter(e=>e.innerText&&e.innerText.trim()==='继续沟通'); return c.length?'yes':'no'; })()",
                session, addr)
            if greeted == "yes":
                print(f"  [warn] {title}: 未点到「继续沟通」，但页面已显示「继续沟通」→ 招呼语已发出，记入已触达", flush=True)
                _finish("greeted-no-custom", False, False, how="no-continue")
                return True, False, "greeted-no-custom"
            print(f"  [warn] {title}: 招呼语未发出（被弹窗挡住/按钮无效），退回候选池重试", flush=True)
            return False, False, "not-sent"
    pause(3.0, 5.0)

    # 会话面板偶发延迟渲染：轮询等待输入框 + JS 兜底，失败也绝不抛异常中断流水线
    filled, how = sg.fill_chat(msg, session, addr)
    if not filled:
        print(f"  [warn] {title}: 未填入定制话术（{how}），招呼语已发出，记入已触达", flush=True)
        _finish("greeted-no-custom", False, False, how=how, jd_keys=meta.get("jd_keys", ""))
        return True, False, "greeted-no-custom"
    pause(0.8, 1.8)
    sr = wb.ev(sg.CLICK_SEND, session, addr)
    pause(1.8, 3.0)

    probe = msg[8:24]
    verified = bool(wb.ev(f"(() => document.body.innerText.includes({json.dumps(probe)}))()", session, addr))
    _finish(sr, True, verified, how=how, jd_keys=meta.get("jd_keys", ""))
    return sr == "sent", verified, key


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None,
                    help="简历画像 JSON；默认用 %s（首次使用请先跑 setup_wizard.py）" % paths.PROFILE)
    ap.add_argument("--pool", default=paths.POOL)
    ap.add_argument("--state", default=paths.STATE)
    ap.add_argument("--log", default=paths.SEND_LOG)
    ap.add_argument("--skip-file", default=paths.SKIPPED,
                    help="本轮内点不出按钮/填不进去的岗位，记此文件避免反复重试")
    ap.add_argument("--src-file", default=paths.SRC,
                    help="岗位来源标记（channel:推荐 / channel:频道名 / search:档位码），用于候选排序")
    ap.add_argument("--skip-channels", action="store_true",
                    help="跳过频道阶段（推荐/求职意向标签），直接进入搜索")
    ap.add_argument("--channel-low-yield", type=int, default=2,
                    help="频道单轮新增 <= 该值算「低产出」（默认 2）")
    ap.add_argument("--channel-dry-rounds", type=int, default=2,
                    help="频道连续低产出几轮即判定枯竭、转搜索（默认 2）")
    ap.add_argument("--gate-search-chunks", type=int, default=4,
                    help="话术门禁处自动补搜的搜索块数（默认 4；0=关闭自动搜索）")
    ap.add_argument("--gate-jd-limit", type=int, default=12,
                    help="门禁收尾时建议抓取的 JD 条数（默认 12）")
    ap.add_argument("--target", type=int, default=0,
                    help="累计触达上限（可选，默认 0=不设上限）。默认不给自己定额度，"
                         "投到「没有可投岗位」或「平台提示当日上限」为止。")
    ap.add_argument("--per-cycle", type=int, default=4, help="每个周期发送条数")
    ap.add_argument("--collect-per-cycle", type=int, default=2, help="每个周期收集的「城市×关键词」块数")
    ap.add_argument("--scrolls", type=int, default=3, help="每个收集块的滚动轮数")
    ap.add_argument("--max-cycles", type=int, default=20)
    ap.add_argument("--cities", nargs="*", default=None)
    ap.add_argument("--keywords", nargs="*", default=None)
    ap.add_argument("--rest-every", type=int, default=4, help="每发 N 条长休息一次")
    ap.add_argument("--session", default="boss-zhipin")
    ap.add_argument("--risk-guard-min", type=int, default=30,
                    help="启动守卫：距上次风控不足该分钟数则拒绝启动（防腐化）")
    ap.add_argument("--force", action="store_true", help="忽略风控冷却守卫，强制启动")
    ap.add_argument("--no-jd", action="store_true", help="不抓 JD（跳过英语要求检查，不推荐）")
    ap.add_argument("--ai-messages", default=sg.AI_MSGS_FILE,
                    help="AI 逐条读 JD 生成的话术文件（默认 %s）" % paths.MESSAGES)
    ap.add_argument("--allow-template", action="store_true",
                    help="缺少 AI 话术时退回模板话术（默认不允许：缺话术的岗位跳过，不发群发式模板）")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    paths.ensure_home()
    a.profile = paths.resolve_profile(a.profile)

    # 不给自己预设每日额度（2026-10-13 用户要求「平台有自己的限制」）：
    # target<=0 表示不设上限，投到「没有可投岗位」或「平台提示当日上限」为止。
    unlimited = a.target <= 0

    profile = load_json(a.profile, {})
    cities = [CITY_CODES.get(c, c) for c in (a.cities or ["101010100"])]
    keywords = a.keywords or profile.get("keywords") or ["AI产品经理"]

    markers = profile.get("exclude_text_markers", ["元/天", "天/周", "在校"])
    sf = profile.get("salary_filter") or {}
    min_k = int(sf.get("min_k", 0) or 0)
    sal_mode = sf.get("mode", "upper")
    sal_strict = bool(sf.get("strict", False))

    # 薪资档位（搜索阶段）：默认 50K以上 → 20-50K。code 与页面「薪资待遇」菜单选项一一对应
    tiers = profile.get("salary_tiers") or [{"label": "50K以上", "code": "407"},
                                            {"label": "20-50K", "code": "406"}]
    tier_order = {"search:" + t.get("code", ""): i for i, t in enumerate(tiers)}

    # 频道（BOSS 推荐标签）：优先投，直到枯竭再搜索
    channels = [] if a.skip_channels else list(profile.get("channels") or [])
    ch_rounds = int(profile.get("channels_rounds", 6))
    if not a.skip_channels and profile.get("use_recommend_tab", True):
        channels = ["推荐"] + channels

    pool = load_json(a.pool, {})
    # 已触达状态统一用「岗位 id」判定（历史 href 格式自动规范化并去重，先备份）
    sg.migrate_state(a.state)
    contacted = sg.load_state_ids(a.state)
    skipped = {sg.job_id(x) for x in load_json(a.skip_file, [])}
    src_map = load_json(a.src_file, {})
    ai_msgs = sg.load_ai_messages(a.ai_messages)     # AI 逐条读 JD 写好的话术（默认唯一来源）

    # 搜索来源队列：按档位顺序（50K以上 全部城市×关键词 → 20-50K ...），档内随机
    def build_search_queue():
        q = []
        for t in tiers:
            combos = [(c, k) for c in cities for k in keywords]
            random.shuffle(combos)
            for c, k in combos:
                q.append(("search", c, k, t.get("code", "")))
        return q

    channel_queue = list(channels)        # [("推荐"/频道名, ...)]
    search_queue = build_search_queue()

    if a.dry_run:
        cands = select_candidates(profile, pool, contacted, markers, min_k, sal_mode,
                                  sal_strict, src_map=src_map, tier_order=tier_order)
        ready = [j for j in cands if sg.job_id(j["href"]) in ai_msgs]
        print(f"[dry] 池={len(pool)} 已触达={len(contacted)} 候选={len(cands)} "
              f"（有 AI 话术 {len(ready)}）/ 累计上限="
              f"{'不限（平台限额为准）' if unlimited else a.target}", flush=True)
        for i, j in enumerate(cands[:15], 1):
            jid = sg.job_id(j["href"])
            tag = "AI话术" if jid in ai_msgs else "缺话术"
            print(f"  {i}. [{tag}] [{j.get('src','?')}] {j['title']} [{j['salary']}]", flush=True)
        return

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

    # 启动守卫：近期触发过风控则拒绝启动
    if not check_recent_risk(a.risk_guard_min, a.force):
        sys.exit(3)

    # 启动守卫：今天已判定额度用尽则直接收尾（当天投不了，跑了也没用）
    if not sg.check_daily_cap(a.force):
        sys.exit(4)

    # 单实例锁：并发运行会导致同一岗位被重复打招呼（实测出过 22 条重复）
    if not sg.acquire_run_lock(a.force):
        sys.exit(5)
    import atexit
    atexit.register(sg.release_run_lock)      # 任何退出路径（含 sys.exit）都会释放锁

    sent_since_rest = 0
    cycle = 0
    dry_streak = 0        # 跨周期累计的「招呼语发不出去」次数，用于识别静默封顶
    ch_low = {}           # 频道 -> 连续「低产出」次数：+1/+2 连续几轮即视作枯竭
    gate_searched = 0     # 话术门禁处已自动补搜的次数（防止无限搜）
    cap_desc = "不限（平台限额为准）" if unlimited else str(a.target)
    while (unlimited or len(contacted) < a.target) and cycle < a.max_cycles:
        cycle += 1
        print(f"\n===== 周期 {cycle} | 已触达 {len(contacted)}/{cap_desc} =====", flush=True)

        # --- 1) 收集小块（频道优先：推荐/意向标签枯竭后才轮到搜索；搜索按薪资档位顺序） ---
        try:
            for _ in range(a.collect_per_cycle):
                if channel_queue:
                    name = channel_queue.pop(0)
                    added = collect_channel_chunk(
                        name, ch_rounds, a.session, addr, pool, a.pool,
                        src_map=src_map, src_path=a.src_file,
                        is_recommend=(name == "推荐"))
                    if added > a.channel_low_yield:
                        channel_queue.append(name)   # 产出正常 → 排到频道队尾继续
                        ch_low[name] = 0
                    elif added > 0:
                        # 低产出（+1/+2）：继续观察，连续若干轮都这么点就判定枯竭
                        ch_low[name] = ch_low.get(name, 0) + 1
                        if ch_low[name] >= a.channel_dry_rounds:
                            print(f"  [channel {name}] 连续 {ch_low[name]} 轮仅 +{added}"
                                  f" → 判定枯竭，不再排入队列", flush=True)
                            ch_low.pop(name, None)
                        else:
                            channel_queue.append(name)
                    elif added == -1:
                        channel_queue.append(name)   # 标签未渲染/被弹走 → 下轮重试
                    else:                            # added == 0 → 枯竭，丢弃该频道
                        print(f"  [channel {name}] 无新岗位 → 丢弃", flush=True)
                    if not channel_queue:
                        print("  [switch] 频道标签已全部枯竭 → 自动进入搜索线", flush=True)
                else:
                    if not search_queue:
                        search_queue = build_search_queue()
                    _, city, kw, code = search_queue.pop(0)
                    collect_chunk(city, kw, a.scrolls, a.session, addr, pool, a.pool,
                                  salary_code=code, src_tag="search:" + code,
                                  src_map=src_map, src_path=a.src_file)
                pause(3.0, 7.0)
        except RiskHalt as e:
            mark_risk(str(e), where="collect")
            sys.exit(3)

        # --- 2) 投递少量（频道岗位优先，其次 50K以上档，再 20-50K 档） ---
        contacted |= sg.load_state_ids(a.state)      # 每周期重读盘上状态，防止陈旧快照重复投递
        cands = [j for j in select_candidates(profile, pool, contacted, markers, min_k, sal_mode,
                                              sal_strict, src_map=src_map, tier_order=tier_order)
                 if sg.job_id(j["href"]) not in skipped]
        # 话术门禁：没有 AI 逐条读 JD 生成的话术 → 不投（绝不发模板群发语）
        no_msg = 0
        if not a.allow_template:
            kept = [j for j in cands if sg.job_id(j["href"]) in ai_msgs]
            no_msg = len(cands) - len(kept)
            cands = kept
        ch_n = sum(1 for j in cands if j.get("src", "").startswith("channel"))
        print(f"  [select] 可投候选 {len(cands)}（频道 {ch_n} / 搜索 {len(cands)-ch_n}），"
              f"因缺 AI 话术暂缓 {no_msg} 条，本周期计划发 {a.per_cycle}", flush=True)
        if not a.allow_template and not cands and no_msg:
            # 门禁：没有 AI 话术就不投。但不要就地停住——先把搜索线自动跑起来补量，
            # 让新岗位（含 JD）落进池子，供 AI 写话术；搜够次数仍无话术才收尾。
            if gate_searched < a.gate_search_chunks:
                gate_searched += 1
                channel_queue.clear()            # 标签页已无「有新岗位」的产出，直接转搜索
                if not search_queue:
                    search_queue = build_search_queue()
                _, city, kw, code = search_queue.pop(0)
                print(f"\n[gate] 标签页无新岗位 → 自动执行搜索"
                      f"（{gate_searched}/{a.gate_search_chunks}）: {city}/{kw} @{code}", flush=True)
                try:
                    collect_chunk(city, kw, a.scrolls, a.session, addr, pool, a.pool,
                                  salary_code=code, src_tag="search:" + code,
                                  src_map=src_map, src_path=a.src_file)
                except RiskHalt as e:
                    mark_risk(str(e), where="collect")
                    sys.exit(3)
                pause(3.0, 7.0)
                continue                          # 回到周期顶部重新选人
            print("\n[话术门禁] 搜索补量后仍无「已写话术」的岗位，本轮收尾。下一步：", flush=True)
            print("  1) python3 scripts/fetch_jd.py --profile %s --limit %d"
                  % (a.profile, a.gate_jd_limit), flush=True)
            print("  2) 由 AI 读 %s 逐条分析 JD，生成话术写入 %s" % (paths.JD, a.ai_messages), flush=True)
            print("  3) 重新运行本流水线（会跳过已触达、只投有话术的岗位）", flush=True)
            sys.exit(6)
        sent_this_cycle = 0
        tried = 0
        fail_streak = 0
        fail_buffer = []       # 失败岗位先进缓冲：确认是孤立失败才写入跳过池
        for job in cands:
            if not unlimited and len(contacted) >= a.target or sent_this_cycle >= a.per_cycle:
                break
            if tried >= a.per_cycle * 4:
                break
            tried += 1
            try:
                okk, ver, key = send_one(job, profile, a.session, addr, contacted, a.state, a.log,
                                         no_jd=a.no_jd,
                                         ai_msg=ai_msgs.get(sg.job_id(job["href"])),
                                         allow_template=a.allow_template)
            except RiskHalt as e:
                mark_risk(str(e), where="send")
                sys.exit(3)
            except Exception as e:                      # 单条异常不得中断流水线
                print(f"  [err] {job['title']} 发送异常：{type(e).__name__}: {e}（跳过本条继续）", flush=True)
                okk, ver, key = False, False, "exc-" + type(e).__name__
            if key == "RISK":
                mark_risk(f"发送 {job['title']} 时命中风控词", where="send")
                sys.exit(3)
            if key == "DAILY_CAP":
                # 平台提示当日沟通额度已用尽 —— 当天到此为止，正常收尾
                real = getattr(sg, "LAST_CAP_TEXT", "") or ""
                sg.mark_daily_cap(real or "平台提示今日沟通额度已用尽（未取到原文）",
                                  where="pipeline-send", total=len(contacted))
                print(f"\n任务结束：当日额度已满，累计触达 {len(contacted)}（池 {len(pool)}）", flush=True)
                sys.exit(0)
            n = f"{len(contacted)}" + (f"/{a.target}" if not unlimited else "")
            print(f"  [{n}] {'OK' if okk else 'skip:'+key} [{job.get('src','')}] {job['title']} [{job['salary']}] verify={ver}", flush=True)
            if str(key).startswith("skip-jd-"):
                # JD 明确要求英语 / 岗位实质错配（如标题包装成 AI 岗的基建项目管理）→ 不再投递，
                # 直接写入跳过池（避免反复打开详情页）
                label = "JD要求英语" if key.startswith("skip-jd-english") else "岗位错配"
                print(f"  [skip {label}] {job['title']} :: {str(key).split(':',1)[-1]}", flush=True)
                skipped.add(sg.job_id(job["href"]))
                save_json(a.skip_file, sorted(skipped))
                log = load_json(a.log, [])
                log.append({"href": job["href"], "title": job["title"], "salary": job.get("salary", ""),
                            "template": "-", "send": str(key).split(":", 1)[0], "custom": False,
                            "src": job.get("src", ""), "verified": False,
                            "how": str(key).split(":", 1)[-1], "time": time.strftime("%H:%M:%S")})
                save_json(a.log, log)
                dry_streak = 0
                continue
            if okk or key == "already":
                fail_streak = 0
                dry_streak = 0
                if fail_buffer:      # 之前的失败是孤立事件，落实跳过池
                    skipped.update(fail_buffer)
                    save_json(a.skip_file, sorted(skipped))
                    fail_buffer = []
            else:
                fail_streak += 1
                fail_buffer.append(sg.job_id(job["href"]))
                if key in ("not-sent", "no-btn"):
                    dry_streak += 1          # 招呼语压根没发出去，计入「静默封顶」观察
            if okk:
                sent_this_cycle += 1
                gate_searched = 0        # 投出去了说明补搜有效，下次门禁重新计数
                sent_since_rest += 1
                if sent_since_rest >= a.rest_every:
                    rest = random.uniform(25, 70)
                    print(f"  ...长休息 {rest:.0f}s（模拟真人离开）", flush=True)
                    time.sleep(rest)
                    sent_since_rest = 0
            elif fail_streak >= 5:
                # 连续失败＝疑似平台限流。不写入跳过池（保留重试机会），长冷却后收手
                print(f"  !! 连续 {fail_streak} 个发送失败，疑似平台限流", flush=True)
                print("  !! 本批失败不记入跳过池，长冷却后由后续周期自动重试", flush=True)
                fail_buffer = []
                fail_streak = 0
                cd = random.uniform(300, 480)
                print(f"  ...限流冷却 {cd:.0f}s", flush=True)
                time.sleep(cd)
                break
            pause(4.0, 9.0)

        # --- 2.5) 静默封顶识别 ---
        # 连续大量岗位「招呼语完全发不出去」（点不出按钮 / 被弹窗挡住），
        # 即使没弹确认框，也基本可判定当日额度已尽：读页面原文留证后优雅收尾。
        if dry_streak >= 12:
            txt = wb.ev("(() => document.body.innerText)()", a.session, addr) or ""
            real = sg.read_cap_text(a.session, addr) or sg.detect_daily_cap(txt) or ""
            if not real:
                real = f"连续 {dry_streak} 条岗位无法发出招呼语（页面未弹确认框），判定当日额度疑似用尽"
            sg.LAST_CAP_TEXT = real
            sg.mark_daily_cap(real, where="dry-streak", total=len(contacted))
            print(f"\n任务结束：连续 {dry_streak} 条无法发出招呼语，判定当日额度已尽，"
                  f"累计触达 {len(contacted)}（池 {len(pool)}）", flush=True)
            sys.exit(0)

        # --- 3) 周期冷却 ---
        if unlimited or len(contacted) < a.target:
            cd = random.uniform(15, 40)
            print(f"  ...周期冷却 {cd:.0f}s", flush=True)
            time.sleep(cd)

    tail = f"/{a.target}" if not unlimited else "（未设上限）"
    print(f"\n完成：累计触达 {len(contacted)}{tail}（池 {len(pool)}）", flush=True)


if __name__ == "__main__":
    main()
