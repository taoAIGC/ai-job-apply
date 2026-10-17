#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""统一路径与用户配置解析（面向多人分发的版本）。

为什么需要这个文件
------------------
改造前，所有可变状态硬编码在 ``/tmp/boss-*.json``（9 个文件、57 处引用），
用户画像写在技能包内的 ``assets/profile-template.json`` —— 里面是**某个具体人的
真实简历**。技能包一旦分发出去会同时踩两个坑：

1. 别人机器上没有那些 ``/tmp`` 文件，且 ``/tmp`` 是共享目录，多人/多任务会互相污染；
2. 别人会直接拿到并投递**你的简历**。

本模块把这两件事收口：

1. 状态与配置统一放 ``BOSS_APPLY_HOME``（默认 ``~/.boss-apply``），可用环境变量覆盖，
   目录本身即是这个用户的全部私有数据边界；
2. 个人画像放 ``<HOME>/profile.json`` —— **它在技能包之外，永远不会被分发**；
   技能包里的 ``assets/profile-template.json`` 只是空白骨架。

老用户无痛迁移
--------------
首次 ``import`` 时调用 :func:`ensure_home`，若 HOME 下没有状态文件、而 ``/tmp`` 下
存在历史文件，则**自动复制**（只复制、不删除、不覆盖已有文件）过去。
"""

import json
import os
import shutil

# --------------------------------------------------------------------------
# 根目录
# --------------------------------------------------------------------------

#: 该用户的私有数据根目录。多账号/多身份时可用 BOSS_APPLY_HOME 隔离。
HOME = os.path.abspath(
    os.path.expanduser(os.environ.get("BOSS_APPLY_HOME") or "~/.boss-apply")
)

# --------------------------------------------------------------------------
# 状态文件（全部位于 HOME 下，互相隔离）
# --------------------------------------------------------------------------

POOL = os.path.join(HOME, "pool.json")            # 岗位池
JD = os.path.join(HOME, "jd.json")                # 抓到的 JD 正文
MESSAGES = os.path.join(HOME, "messages.json")    # AI 逐条写的话术
STATE = os.path.join(HOME, "contacted.json")      # 已触达（断点续跑依据）
SKIPPED = os.path.join(HOME, "skipped.json")      # 跳过池
SEND_LOG = os.path.join(HOME, "send-log.json")    # 发送日志
SRC = os.path.join(HOME, "src.json")              # 岗位来源标记
DAILY_CAP = os.path.join(HOME, "daily-cap.json")  # 当日封顶记录
RISK = os.path.join(HOME, "risk.json")            # 风控事件
LOCK = os.path.join(HOME, "run.lock")             # 单实例锁

# --------------------------------------------------------------------------
# 用户配置
# --------------------------------------------------------------------------

#: 简历画像。**个人隐私，绝不进技能包。**
PROFILE = os.path.join(HOME, "profile.json")
LOG_DIR = os.path.join(HOME, "logs")

#: 技能包根目录（本文件在 <skill>/scripts/ 下）
SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
#: 技能包内置的空白骨架
TEMPLATE = os.path.join(SKILL_DIR, "assets", "profile-template.json")

# --------------------------------------------------------------------------
# 历史路径迁移
# --------------------------------------------------------------------------

LEGACY = {
    "/tmp/boss-pool.json": POOL,
    "/tmp/boss-jd.json": JD,
    "/tmp/boss-messages.json": MESSAGES,
    "/tmp/boss-contacted.json": STATE,
    "/tmp/boss-skipped.json": SKIPPED,
    "/tmp/boss-send-log.json": SEND_LOG,
    "/tmp/boss-src.json": SRC,
    "/tmp/boss-daily-cap.json": DAILY_CAP,
    "/tmp/boss-risk.json": RISK,
}

_ENSURED = False


def ensure_home(migrate=True):
    """建目录 + 搬迁历史文件。幂等。

    返回本次实际搬迁的 ``[(旧路径, 新路径)]`` 列表。
    """
    global _ENSURED
    moved = []
    os.makedirs(HOME, exist_ok=True)
    os.makedirs(LOG_DIR, exist_ok=True)
    if migrate and not _ENSURED:
        for old, new in LEGACY.items():
            if os.path.exists(old) and not os.path.exists(new):
                try:
                    shutil.copy2(old, new)
                    moved.append((old, new))
                except OSError:
                    pass  # 权限等偶发问题不阻断主流程
    _ENSURED = True
    return moved


def legacy_leftovers():
    """还有哪些老文件没搬过来（供 doctor 提示手工清理）。"""
    return [old for old, new in LEGACY.items()
            if os.path.exists(old) and os.path.exists(new)]


# --------------------------------------------------------------------------
# 画像解析
# --------------------------------------------------------------------------

def resolve_profile(cli_value=None, required=True):
    """决定本次任务用哪份画像，返回绝对路径（或 None）。

    优先级：命令行显式传入 > 用户 profile.json > 未配置。
    """
    if cli_value:
        path = os.path.abspath(os.path.expanduser(cli_value))
        if not os.path.exists(path):
            raise SystemExit("[profile] 画像文件不存在：%s" % path)
        return path
    if os.path.exists(PROFILE):
        st = profile_status(PROFILE)
        if not st["ready"]:
            import sys as _sys
            print("[profile] 警告：%s 尚未配置完整，缺：%s\n"
                  "          建议先跑 python3 scripts/setup_wizard.py"
                  % (PROFILE, "、".join(st["missing"])), file=_sys.stderr)
        return PROFILE
    if required:
        raise SystemExit(
            "[profile] 尚未完成配置，无法开始投递。\n"
            "  请先完成首次配置引导：\n"
            "      python3 scripts/setup_wizard.py --check      # 看还缺什么\n"
            "      python3 scripts/setup_wizard.py              # 交互式填写\n"
            "  （若由 AI 引导，见 SKILL.md 的「Step -1 首次配置引导」）"
        )
    return None


def load_profile(path=None):
    """读取画像 JSON；不存在返回 None。"""
    p = path or (PROFILE if os.path.exists(PROFILE) else None)
    if not p or not os.path.exists(p):
        return None
    with open(p, encoding="utf-8") as f:
        return json.load(f)


def load_template():
    """读取技能包内的空白骨架。"""
    with open(TEMPLATE, encoding="utf-8") as f:
        return json.load(f)


#: 判定「配置可用」的必填项：(点分路径, 中文说明, 最少条数)
REQUIRED_FIELDS = [
    ("resume_points.summary", "一句话自我介绍", 0),
    ("resume_points.highlights", "真实经历亮点", 3),
    ("keywords", "搜索关键词", 3),
    ("cities", "目标城市", 1),
    ("salary_filter.min_k", "薪资下限（K）", 0),
]


def _dig(obj, dotted):
    cur = obj
    for part in dotted.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur


def profile_status(path=None):
    """体检画像是否可用于投递。

    返回 ``{"path", "exists", "ready", "missing": [中文说明], "owner"}``。
    """
    p = path or PROFILE
    out = {"path": p, "exists": os.path.exists(p), "ready": False,
           "missing": [], "owner": ""}
    if not out["exists"]:
        out["missing"] = [desc for _, desc, _ in REQUIRED_FIELDS]
        return out

    data = load_profile(p) or {}
    out["owner"] = data.get("owner", "")
    missing = []
    for dotted, desc, minlen in REQUIRED_FIELDS:
        val = _dig(data, dotted)
        empty = (
            val is None
            or (isinstance(val, (str, list, dict, tuple)) and len(val) == 0)
            or (isinstance(val, (int, float)) and not isinstance(val, bool) and val <= 0)
        )
        if empty:
            missing.append(desc)
        elif minlen and isinstance(val, list) and len(val) < minlen:
            missing.append("%s（至少 %d 条，当前 %d 条）" % (desc, minlen, len(val)))
    out["missing"] = missing
    out["ready"] = not missing and bool(data.get("_ready", True))
    return out
