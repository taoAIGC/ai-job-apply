#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""把长跑任务真正「脱壳」成守护进程（macOS 没有 setsid，用双 fork 自己实现）。

用途：投递要跑几十分钟到几小时，不能挂在对话回合的后台任务上——
回合结束/被打断时，harness 会回收该进程组，任务就「莫名停了」。
本启动器双 fork 后调用 exec，进程脱离当前会话、被 init 接管，
不再随对话回合结束而消失。

用法：
  python3 scripts/daemonize.py [被守护的脚本.py] [参数...]
  # 默认守护 scripts/run_forever.py
日志：默认写到 ~/.boss-apply/logs/daemon-YYYYmmdd-HHMM.log（可用 BOSS_DAEMON_LOG 覆盖）
"""
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))


def main():
    args = sys.argv[1:]
    target = args[0] if args else os.path.join(HERE, "run_forever.py")
    extra = args[1:]
    if not os.path.isabs(target):
        target = os.path.join(HERE, target)

    logpath = os.environ.get("BOSS_DAEMON_LOG")
    if not logpath:
        home = os.environ.get("HOME", "/tmp")
        logdir = os.path.join(home, ".boss-apply", "logs")
        os.makedirs(logdir, exist_ok=True)
        logpath = os.path.join(logdir, "daemon-%s.log" % time.strftime("%Y%m%d-%H%M"))

    # 第一次 fork：父进程立即返回，让调用方拿到控制权
    if os.fork() > 0:
        print(f"[daemon] 已派生守护进程，日志 {logpath}")
        return
    os.setsid()                      # 脱离控制终端 / 进程组
    if os.fork() > 0:                # 第二次 fork：确保不是会话首进程，无法重新获得终端
        os._exit(0)

    os.chdir("/")
    os.umask(0)
    fd = os.open(logpath, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    os.dup2(fd, 1)
    os.dup2(fd, 2)
    devnull = os.open(os.devnull, os.O_RDONLY)
    os.dup2(devnull, 0)
    os.execv(sys.executable, [sys.executable, "-u", target] + extra)


if __name__ == "__main__":
    main()
