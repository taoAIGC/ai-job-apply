#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""环境体检 —— 装完先跑这个，一次看清「还差什么才能投递」。

    python3 scripts/doctor.py            # 人话版
    python3 scripts/doctor.py --json     # 机器可读（AI 引导时用）
    python3 scripts/doctor.py --fix      # 顺手把能自动修的修掉（目前只有：拉起守护进程）

只做诊断，不改任何业务状态。--fix 只会执行 SKILL.md 里声明为「幂等、安全」的动作
（``kimi-webbridge start``），绝不触碰 stop / restart / upgrade / uninstall。
"""

import argparse
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402

MIN_PY = (3, 8)
REQUIRED_SCRIPTS = [
    "run_pipeline.py", "send_greetings.py", "fetch_jd.py",
    "collect_jobs.py", "webbridge.py", "paths.py",
]


def _check_python():
    v = sys.version_info
    ok = (v.major, v.minor) >= MIN_PY
    return ok, "Python %d.%d.%d" % (v.major, v.minor, v.micro), \
        "需要 >= %d.%d" % MIN_PY


def _check_scripts():
    missing = [s for s in REQUIRED_SCRIPTS
               if not os.path.exists(os.path.join(paths.SKILL_DIR, "scripts", s))]
    ok = not missing
    return ok, ("%d 个脚本齐全" % len(REQUIRED_SCRIPTS)) if ok else ("缺失：" + ", ".join(missing)), \
        "技能包可能不完整，请重新安装"


def _check_home():
    try:
        paths.ensure_home(migrate=False)
        probe = os.path.join(paths.HOME, ".write-probe")
        with open(probe, "w") as f:
            f.write("ok")
        os.remove(probe)
        return True, paths.HOME, ""
    except OSError as e:
        return False, paths.HOME, "目录不可写：%s（可用 BOSS_APPLY_HOME 换一个位置）" % e


def _check_bridge(start=False):
    try:
        import webbridge as wb
    except Exception as e:  # pragma: no cover
        return False, "无法导入 webbridge.py：%s" % e, "技能包可能损坏"

    if not os.path.exists(wb.BIN):
        return False, "未安装", "请安装浏览器扩展：curl -fsSL https://cdn.kimi.com/webbridge/install.sh | bash"

    st = wb._status() or {}
    if not st.get("running"):
        if start:
            try:
                wb.ensure_daemon()
                st = wb._status() or {}
            except Exception as e:
                return False, "启动失败", str(e)
        else:
            return False, "守护进程未运行", "运行 python3 scripts/doctor.py --fix 自动拉起"
    if not st.get("running"):
        return False, "守护进程未运行", "运行 ~/.kimi-webbridge/bin/kimi-webbridge start"

    ok, msg = wb.check_extension()
    if not ok:
        return False, "守护进程在跑，但浏览器扩展未连接", \
            "请在浏览器打开 Kimi 侧边栏，确认已连接 ws://127.0.0.1:10086/ws"
    return True, msg, ""


def _check_profile():
    st = paths.profile_status()
    if st["ready"]:
        return True, "%s（%s）" % (st["owner"] or "已配置", st["path"]), ""
    if not st["exists"]:
        return False, "尚未配置", "运行 python3 scripts/setup_wizard.py --interactive"
    return False, "配置不完整，缺 " + "、".join(st["missing"]), \
        "补齐后重跑本体检，或 python3 scripts/setup_wizard.py --show"


def _stats():
    def n(p):
        try:
            with open(p, encoding="utf-8") as f:
                d = json.load(f)
            return len(d.get("msgs", d)) if isinstance(d, dict) else len(d)
        except Exception:
            return 0
    return {
        "岗位池": n(paths.POOL),
        "JD 库": n(paths.JD),
        "话术库": n(paths.MESSAGES),
        "已触达": n(paths.STATE),
    }


def main():
    ap = argparse.ArgumentParser(description="BOSS 投递环境体检")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--fix", action="store_true", help="自动修复可自动修复的项（拉起守护进程）")
    a = ap.parse_args()

    checks = []
    for name, fn in [
        ("Python 运行时", lambda: _check_python()),
        ("技能包完整性", lambda: _check_scripts()),
        ("数据目录可写", lambda: _check_home()),
        ("浏览器桥接", lambda: _check_bridge(a.fix)),
        ("个人配置", lambda: _check_profile()),
    ]:
        try:
            ok, detail, fix = fn()
        except Exception as e:
            ok, detail, fix = False, "检查时异常：%s" % e, ""
        checks.append({"name": name, "ok": ok, "detail": detail, "fix": fix})

    blocking = [c for c in checks if not c["ok"]]
    result = {
        "ok": not blocking,
        "home": paths.HOME,
        "profile": paths.PROFILE,
        "checks": checks,
        "stats": _stats(),
    }

    if a.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result["ok"] else 1

    print("=" * 58)
    print(" BOSS 直聘投递 · 环境体检")
    print("=" * 58)
    for c in checks:
        print("  %s  %-12s %s" % ("[ok]  " if c["ok"] else "[缺]  ", c["name"], c["detail"]))
        if not c["ok"] and c["fix"]:
            print("         → %s" % c["fix"])
    print("-" * 58)
    s = result["stats"]
    print("  数据目录：%s" % paths.HOME)
    print("  当前存量：%s" % " | ".join("%s %d" % (k, v) for k, v in s.items()))
    print("-" * 58)
    print("  %s" % ("全部就绪，可以开始投递。" if result["ok"]
                    else "以上 %d 项待处理。" % len(blocking)))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
