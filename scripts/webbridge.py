#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kimi Browser Extension（kimi-webbridge）本地守护进程调用封装。

BOSS 直聘的所有操作都通过用户自己浏览器里的扩展完成：
请求 POST 到守护进程 http://127.0.0.1:10086/command，body 形如
    {"action": "...", "args": {...}, "session": "任务名"}
"""
import json
import os
import subprocess
import time
import urllib.error
import urllib.request

DEFAULT_ADDR = os.environ.get("BOSS_BRIDGE_ADDR", "127.0.0.1:10086")
BIN = os.environ.get("BOSS_BRIDGE_BIN", os.path.expanduser("~/.kimi-webbridge/bin/kimi-webbridge"))


class BridgeError(RuntimeError):
    pass


def _status():
    """读取守护进程状态，返回 dict 或 None。"""
    if not os.path.exists(BIN):
        return None
    try:
        out = subprocess.run([BIN, "status"], capture_output=True, text=True, timeout=15).stdout
        return json.loads(out)
    except Exception:
        return None


def ensure_daemon():
    """确保守护进程在跑（幂等：已在跑则 no-op）。返回 addr。"""
    st = _status()
    if st and st.get("running"):
        return f"127.0.0.1:{st.get('port', 10086)}"
    if not os.path.exists(BIN):
        raise BridgeError(
            "未安装 kimi-webbridge。请先安装 Kimi 浏览器扩展：\n"
            "  curl -fsSL https://cdn.kimi.com/webbridge/install.sh | bash"
        )
    subprocess.run([BIN, "start"], capture_output=True, text=True, timeout=60)
    time.sleep(2)
    st = _status() or {}
    if not st.get("running"):
        raise BridgeError("守护进程启动失败，请检查 ~/.kimi-webbridge/logs/daemon.log")
    return f"127.0.0.1:{st.get('port', 10086)}"


def check_extension(addr=DEFAULT_ADDR):
    """确认浏览器扩展已连接，返回 (ok, message)。"""
    try:
        with urllib.request.urlopen(f"http://{addr}/command", data=b'{}', timeout=8) as r:
            json.loads(r.read().decode("utf-8"))
    except Exception:
        pass
    st = _status()
    if st and st.get("extension_connected"):
        return True, f"扩展已连接（{st.get('version')}）"
    return False, (
        "守护进程在运行，但浏览器扩展未连接。请让用户在浏览器中打开 Kimi 侧边栏/扩展并确认已连接"
        "（Kimi 侧边栏 → 设置 → 本地智能体远程控制 → 连接地址 ws://127.0.0.1:10086/ws）。"
    )


def call(action, args=None, session="boss-zhipin", addr=DEFAULT_ADDR, timeout=30, retries=2):
    """调用一次桥接命令，返回 data 字段（失败抛 BridgeError）。"""
    body = json.dumps({"action": action, "args": args or {}, "session": session}).encode("utf-8")
    last = None
    for _ in range(retries + 1):
        try:
            req = urllib.request.Request(
                f"http://{addr}/command", data=body, headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                res = json.loads(r.read().decode("utf-8"))
            if res.get("ok"):
                return res.get("data", {})
            err = res.get("error", {})
            code = err.get("code", "")
            if code == "extension_not_connected":
                raise BridgeError("浏览器扩展未连接：" + err.get("message", ""))
            last = BridgeError(f"{code}: {err.get('message')}")
        except urllib.error.URLError as e:
            last = BridgeError(f"无法连接守护进程（{addr}）：{e}")
        time.sleep(1.5)
    raise last


def ev(code, session="boss-zhipin", addr=DEFAULT_ADDR, timeout=30):
    """执行页面 JS，返回结果值（失败返回 None）。"""
    try:
        return call("evaluate", {"code": code}, session, addr, timeout).get("value")
    except BridgeError:
        return None


def navigate(url, session="boss-zhipin", addr=DEFAULT_ADDR, group_title=None, new_tab=False):
    args = {"url": url}
    if new_tab:
        args["newTab"] = True
    if group_title:
        args["group_title"] = group_title
    return call("navigate", args, session, addr, 45)


def screenshot(path, session="boss-zhipin", addr=DEFAULT_ADDR, fmt="png"):
    return call("screenshot", {"format": fmt, "path": path}, session, addr, 45)


def fill(selector, value, session="boss-zhipin", addr=DEFAULT_ADDR):
    return call("fill", {"selector": selector, "value": value}, session, addr, 30)


def close_session(session="boss-zhipin", addr=DEFAULT_ADDR):
    return call("close_session", {}, session, addr, 30)
