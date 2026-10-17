#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""投递守护进程（解决「投完一批就停」的问题）。

背景：
  send_greetings.py 是「单轮」脚本——它只投「话术库里已有 AI 话术」的岗位，
  一旦这批投完就正常退出（退出码 0）。而 AI 话术是逐条读 JD 现场撰写的，
  所以每批投完看起来就像「又停了」。

本守护做的事：
  循环调用 send_greetings.py：
    · 队列还有话术     → 立刻再跑一轮
    · 队列投完了       → 进入待命，每分钟探测一次；一旦话术库有新条目，自动继续
    · 平台提示当日上限 → 收工
    · 命中风控/验证    → 收工（需人工处理，避免无效重试）
  这样只要话术在持续补写，投递就不会中断。

用法：
  python3 scripts/run_forever.py                # 默认待命上限 6 小时
  BOSS_WATCH_MAX_IDLE_MIN=0 python3 ...         # 无限待命（推荐挂后台时用）
"""
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import paths  # noqa: E402

PY = sys.executable
SENDER = os.path.join(HERE, "send_greetings.py")
SLEEP = int(os.environ.get("BOSS_WATCH_SLEEP", "60"))              # 待命轮询间隔（秒）
MAX_IDLE_MIN = int(os.environ.get("BOSS_WATCH_MAX_IDLE_MIN", "360"))  # 0 = 无限待命

# 风控/验证类文案（只在发送端输出里匹配，避免误伤 JD 正文）
RISK_MARKERS = ("触发风控", "请完成安全验证", "滑动验证", "人机验证", "访问受限")


def _today():
    return time.strftime("%Y-%m-%d")


def capped_today():
    try:
        with open(paths.DAILY_CAP, encoding="utf-8") as f:
            return json.load(f).get("date") == _today()
    except Exception:
        return False


def pending_count():
    """话术库里「有 AI 话术但还没触达」的岗位数；出错返回 -1。"""
    try:
        with open(paths.MESSAGES, encoding="utf-8") as f:
            raw = json.load(f)
        msgs = raw.get("msgs", raw) if isinstance(raw, dict) else raw
        with open(paths.STATE, encoding="utf-8") as f:
            st = set(json.load(f))
        return len([k for k in msgs if k not in st])
    except Exception:
        return -1


def contacted_count():
    try:
        with open(paths.STATE, encoding="utf-8") as f:
            return len(json.load(f))
    except Exception:
        return -1


def main():
    logdir = os.path.join(paths.HOME, "logs")
    os.makedirs(logdir, exist_ok=True)
    logfile = os.path.join(logdir, "watch-%s.log" % time.strftime("%Y%m%d-%H%M"))
    fh = open(logfile, "a", encoding="utf-8", buffering=1)

    def say(line):
        line = line.rstrip("\n")
        print(line, flush=True)
        fh.write(line + "\n")

    say("=" * 62)
    say(f"投递守护启动 | {time.strftime('%Y-%m-%d %H:%M:%S')}")
    say(f"待命轮询 {SLEEP}s | 待命上限 {MAX_IDLE_MIN} 分钟（0=不限）| 日志 {logfile}")
    say("=" * 62)

    cycle = 0
    idle_since = None
    while True:
        cycle += 1
        pend = pending_count()
        say(f"\n--- 守护周期 {cycle} | {time.strftime('%H:%M:%S')} | "
            f"待投 {pend} | 累计已触达 {contacted_count()} ---")

        before = contacted_count()
        proc = subprocess.Popen([PY, "-u", SENDER], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, bufsize=1)
        risk_hit = False
        for line in proc.stdout:
            line = line.rstrip("\n")
            print(line, flush=True)
            fh.write(line + "\n")
            if any(m in line for m in RISK_MARKERS):
                risk_hit = True
        proc.wait()
        gained = contacted_count() - before

        if capped_today():
            say("\n[守护] 平台已提示当日额度用尽 → 今天的投递到此收工。")
            break
        if risk_hit:
            say("\n[守护] 本轮命中风控/验证提示 → 收工，请人工处理后再启动。")
            break

        # 只在“确实投出去了”的时候立刻续跑；否则进入待命，避免空转反复访问页面
        if gained > 0:
            idle_since = None
            say(f"[守护] 本轮新增触达 {gained} 条 → 立即续跑下一轮。")
            time.sleep(3)
            continue

        rest = pending_count()
        if idle_since is None:
            idle_since = time.time()
            say(f"[守护] 本轮无新增触达（待投 {rest}，多为缺话术/已跳过）→ 进入待命，"
                f"每 {SLEEP}s 探测一次；补写话术后会自动继续。")
        if MAX_IDLE_MIN and (time.time() - idle_since) > MAX_IDLE_MIN * 60:
            say(f"[守护] 待命已超过 {MAX_IDLE_MIN} 分钟仍无进展 → 退出。")
            break
        time.sleep(SLEEP)

    fh.close()


if __name__ == "__main__":
    main()
