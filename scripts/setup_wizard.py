#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""首次配置引导 —— 让每个安装者填自己的信息，而不是用作者的简历投递。

用法
----
1) 看现在缺什么（AI 或用户都可先跑这个）::

       python3 scripts/setup_wizard.py --check

   输出 JSON：``{"configured":..., "ready":..., "missing":[...], "path":"..."}``

2) **AI 引导模式（推荐）**：AI 在对话里分几轮问清楚，把答案写成一份 draft，再一次性落盘::

       python3 scripts/setup_wizard.py --from-json /tmp/my-profile-draft.json

3) 用户自己在终端逐项填写::

       python3 scripts/setup_wizard.py --interactive

4) 看看当前生效的配置（脱敏）::

       python3 scripts/setup_wizard.py --show

draft 的结构（除 resume 外均可省略）::

    {
      "owner": "张先生",
      "cities": ["北京", "上海"],                 // 中文名，或直接给 BOSS 城市代码
      "keywords": ["AI产品经理", "大模型产品经理"],
      "salary_min_k": 30,
      "channels": ["AI产品经理(北京)"],            // 可选：BOSS 求职意向频道标签
      "resume": {
        "summary": "一句话自我介绍",
        "current": "最近一段经历（公司·职位·时间）",
        "highlights": ["亮点1（带量化指标最好）", "亮点2", "亮点3"]
      },
      "exclude_extra": "教育|医疗",                // 追加到通用排除正则后面
      "note": "任何要告诉 AI 的补充说明"
    }
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

#: 已实测验证的城市代码（其余城市请直接填 BOSS 搜索页 URL 里的代码）
CITY_CODES = {
    "北京": "101010100",
    "上海": "101020100",
    "广州": "101280100",
    "深圳": "101280600",
    "杭州": "101210100",
    "成都": "101270100",
    "武汉": "101200100",
    "南京": "101190100",
    "西安": "101110100",
    "苏州": "101190400",
    "天津": "101030100",
    "重庆": "101040100",
    "长沙": "101250100",
    "郑州": "101180100",
    "青岛": "101120100",
    "合肥": "101220100",
    "厦门": "101230200",
    "福州": "101230100",
    "济南": "101120200",
    "宁波": "101210400",
    "东莞": "101281600",
    "佛山": "101280800",
}

VERIFIED_CITIES = ["北京", "上海", "广州", "深圳", "杭州"]


def norm_cities(raw):
    """把 ["北京","101020100"] 归一化成 [{"code","name"}]。"""
    out = []
    for item in raw or []:
        name = str(item).strip()
        if not name:
            continue
        if name.isdigit():
            out.append({"code": name, "name": name})
        elif name in CITY_CODES:
            out.append({"code": CITY_CODES[name], "name": name})
        else:
            out.append({"code": name, "name": name + "（未收录，请核对代码）"})
    return out


def build_profile(draft):
    """以技能包内空白骨架为底，叠加用户草稿，产出可用的 profile.json 内容。"""
    base = paths.load_template()

    base["owner"] = (draft.get("owner") or "").strip()

    cities = norm_cities(draft.get("cities"))
    if cities:
        base["cities"] = cities
        base["city"] = cities[0]["code"]
        base["city_name"] = cities[0]["name"]

    kws = [k.strip() for k in (draft.get("keywords") or []) if str(k).strip()]
    if kws:
        base["keywords"] = kws

    if draft.get("channels"):
        base["channels"] = [c.strip() for c in draft["channels"] if str(c).strip()]

    min_k = draft.get("salary_min_k")
    if isinstance(min_k, (int, float)) and min_k > 0:
        base.setdefault("salary_filter", {})
        base["salary_filter"]["min_k"] = int(min_k)

    resume = draft.get("resume") or {}
    base["resume_points"] = {
        "summary": (resume.get("summary") or "").strip(),
        "current": (resume.get("current") or "").strip(),
        "highlights": [h.strip() for h in (resume.get("highlights") or []) if str(h).strip()],
    }

    extra = (draft.get("exclude_extra") or "").strip()
    if extra:
        base["exclude"] = (base.get("exclude") or "").rstrip("|") + "|" + extra

    if draft.get("note"):
        base["note"] = draft["note"]

    # 兜底模板/关键词句全部来自作者个人经历，一律清空——话术由 AI 读 JD 现场写
    base["templates"] = {}
    base["jd_lines"] = {}
    base["_templates_note"] = (
        "【已清空】模板与关键词句包含作者个人经历，分发版不携带。"
        "正常投递不使用模板：话术由 AI 读 JD + resume_points 现场撰写。"
    )

    base["_schema_version"] = 2
    base["_ready"] = True
    base["_configured_at"] = __import__("datetime").datetime.now().isoformat(timespec="seconds")
    return base


def cmd_check():
    st = paths.profile_status()
    print(json.dumps({
        "configured": st["exists"],
        "ready": st["ready"],
        "path": st["path"],
        "owner": st["owner"],
        "missing": st["missing"],
    }, ensure_ascii=False, indent=2))
    return 0 if st["ready"] else 1


def cmd_from_json(path):
    if not os.path.exists(path):
        print("[error] draft 不存在：%s" % path, file=sys.stderr)
        return 2
    with open(path, encoding="utf-8") as f:
        draft = json.load(f)

    profile = build_profile(draft)
    paths.ensure_home(migrate=False)
    if os.path.exists(paths.PROFILE):
        bak = paths.PROFILE + ".bak-" + __import__("time").strftime("%Y%m%d-%H%M%S")
        __import__("shutil").copy2(paths.PROFILE, bak)
        print("[backup] 旧配置已备份 → %s" % bak)
    with open(paths.PROFILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=2)

    st = paths.profile_status()
    print("[ok] 配置已写入 %s" % paths.PROFILE)
    print("     求职者：%s" % (profile["owner"] or "（未填）"))
    print("     城市  ：%s" % "、".join(c["name"] for c in profile["cities"]))
    print("     关键词：%d 个" % len(profile["keywords"]))
    print("     薪资  ：上限 >%sK" % profile["salary_filter"]["min_k"])
    print("     经历亮点：%d 条" % len(profile["resume_points"]["highlights"]))
    if st["missing"]:
        print("\n[!] 还缺这些，补齐后才能开始投递：")
        for m in st["missing"]:
            print("    - %s" % m)
        return 1
    print("\n[ready] 配置可用，可以开始投递了。")
    return 0


def _ask(prompt, default=""):
    tip = "（默认 %s）" % default if default else ""
    try:
        val = input("%s%s: " % (prompt, tip)).strip()
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(130)
    return val or default


def cmd_interactive():
    print("=" * 60)
    print(" BOSS 直聘投递 · 首次配置引导")
    print("=" * 60)
    print("直接回车可用默认值；随时 Ctrl+C 中断（不会写入半份配置）。\n")

    draft = {}
    draft["owner"] = _ask("1/5 怎么称呼你")

    print("\n2/5 目标城市（多个用逗号隔开）。已实测支持：%s" % "、".join(VERIFIED_CITIES))
    print("    其它城市请直接填 BOSS 搜索页 URL 里的城市代码")
    raw = _ask("    城市")
    draft["cities"] = [c.strip() for c in raw.replace("，", ",").split(",") if c.strip()]

    print("\n3/5 搜索关键词（多个用逗号隔开），例如：AI产品经理, 大模型产品经理")
    raw = _ask("    关键词")
    draft["keywords"] = [k.strip() for k in raw.replace("，", ",").split(",") if k.strip()]

    min_k = _ask("\n4/5 只投薪资上限高于多少 K 的岗位", "40")
    try:
        draft["salary_min_k"] = int(float(min_k))
    except ValueError:
        draft["salary_min_k"] = 40

    print("\n5/5 个人经历（AI 写打招呼话术时会引用，务必真实）")
    draft["resume"] = {
        "summary": _ask("    · 一句话自我介绍"),
        "current": _ask("    · 最近一段经历（公司·职位·时间）"),
        "highlights": [],
    }
    print("    · 经历亮点，一行一条（至少 3 条，带量化指标最好），空行结束：")
    while True:
        line = _ask("      ")
        if not line:
            break
        draft["resume"]["highlights"].append(line)

    extra = _ask("\n    额外想排除的行业/岗位（正则关键词，可留空）")
    if extra:
        draft["exclude_extra"] = extra

    print()
    return cmd_from_json(_dump_temp(draft))


def _dump_temp(draft):
    paths.ensure_home(migrate=False)
    tmp = os.path.join(paths.HOME, "_draft.json")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(draft, f, ensure_ascii=False, indent=2)
    return tmp


def cmd_show():
    data = paths.load_profile()
    if not data:
        print("[!] 还没有配置。运行：python3 scripts/setup_wizard.py --interactive")
        return 1
    rp = data.get("resume_points") or {}
    print("配置文件：%s" % paths.PROFILE)
    print("称呼    ：%s" % (data.get("owner") or "（未填）"))
    print("城市    ：%s" % "、".join(c.get("name", c.get("code", "")) for c in data.get("cities", [])))
    print("关键词  ：%s" % "、".join(data.get("keywords", [])))
    print("频道标签：%s" % ("、".join(data.get("channels", [])) or "（无，只做搜索）"))
    sf = data.get("salary_filter") or {}
    print("薪资    ：上限 >%sK" % sf.get("min_k"))
    print("简介    ：%s" % (rp.get("summary") or "（未填）"))
    print("当前    ：%s" % (rp.get("current") or "（未填）"))
    print("亮点    ：%d 条" % len(rp.get("highlights") or []))
    for h in (rp.get("highlights") or []):
        print("          - %s" % h)
    st = paths.profile_status()
    print("\n状态    ：%s" % ("可用" if st["ready"] else "尚缺 " + "、".join(st["missing"])))
    return 0


def main():
    ap = argparse.ArgumentParser(description="BOSS 直聘投递 · 首次配置引导")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--check", action="store_true", help="只检查配置是否就绪（输出 JSON）")
    g.add_argument("--from-json", metavar="DRAFT", help="从草稿 JSON 生成配置（AI 引导模式）")
    g.add_argument("--interactive", action="store_true", help="交互式逐项填写")
    g.add_argument("--show", action="store_true", help="查看当前配置（脱敏）")
    a = ap.parse_args()

    if a.check:
        return cmd_check()
    if a.from_json:
        return cmd_from_json(a.from_json)
    if a.show:
        return cmd_show()
    if a.interactive or sys.stdin.isatty():
        return cmd_interactive()
    return cmd_check()


if __name__ == "__main__":
    sys.exit(main())
