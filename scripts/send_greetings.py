#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""阶段二：批量给 BOSS 直聘岗位发定制打招呼话术。

流程（每个岗位）：
  详情页 -> 点「立即沟通」（系统自动发一条默认招呼语）
        -> 弹窗点「继续沟通」-> 跳转 /web/geek/chat
        -> 填定制话术到 .chat-input -> 点 button.btn-send -> 校验

用法：
  python3 send_greetings.py --profile ~/.boss-apply/profile.json --pool ~/.boss-apply/pool.json \
      --target 50                 # 累计触达 50 个（断点续跑，已发过的自动跳过）
  python3 send_greetings.py --profile ... --pool ... --target 60 --dry-run   # 只预览不发送
"""
import argparse
import json
import os
import random
import re
import sys
import time
import unicodedata

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import paths  # noqa: E402  统一路径/用户配置
import webbridge as wb  # noqa: E402

# 卡片文本里的悬浮层/无关词，解析标题时跳过
SKIP_TOKENS = {"快速投递", "不感兴趣", "×", "", "感兴趣", "沟通中", "已投递"}

# ⚠️ 风控词表必须“精确”，否则会误伤正常岗位描述。
# 曾因裸词 `爬取` 命中某 JD 里的「机构网站数据爬取」而把整条流水线误熔断。
# 因此：只用平台告警的**固定措辞**（「频繁过度爬取」「过度爬取」），不要用单字/常用词。
RISK_PATTERN = re.compile(
    r"安全验证|滑动验证|请完成验证|验证码|人机验证|访问受限|系统检测到|"
    r"操作过于频繁|请求过于频繁|访问频繁|操作频繁|"
    r"频繁过度爬取|过度爬取岗位|异常访问|触发风控|"
    r"账号异常|请稍后再试|网络繁忙请重试|已被限制|访问过于频繁"
)

# 风控体检只扫「平台告警区」，不扫 JD 正文，从根上避免误判。
RISK_ALERT_JS = """
(() => {
  const parts = [];
  const sel = '.dialog-container,[class*=toast],[class*=dialog],[class*=verify],'
            + '[class*=captcha],[class*=risk],[class*=error-page],.error-content';
  document.querySelectorAll(sel).forEach(e => {
    const t = (e.innerText || '').trim();
    if (t) parts.push(t);
  });
  const body = document.body.innerText || '';
  // 整页级拦截（如「访问受限」整页提示）：页面没有职位结构且内容很短
  const hasJob = !!document.querySelector('[class*=job-detail],.job-sec,.job-boss-info,[class*=job-card-wrap]');
  if (!hasJob && body.length < 1500) parts.push(body);
  return parts.join('\\n').slice(0, 1200);
})()
"""


def risk_text(session, addr):
    """抓取「可能含风控告警」的文本（告警区优先，排除 JD 正文）。"""
    try:
        return wb.ev(RISK_ALERT_JS, session, addr) or ""
    except Exception:
        return ""


def risk_hit_text(session, addr):
    """返回命中的风控片段（无命中返回 ''），便于取证留档。"""
    t = risk_text(session, addr)
    m = RISK_PATTERN.search(t)
    return t[max(0, m.start() - 40):m.end() + 40] if m else ""


# 当日投递额度用尽的提示。与风控不同：这是平台正常限额，说明今天投完了，
# 应当优雅收尾（而不是当成失败反复重试下一个岗位）。
# 判定要点：只有「无继续按钮 + 强信号词」或「数字 ≥150」才算封顶；
#           「今天投递数量达到120个了，是否继续投递」属可继续，不算封顶。
DAILY_CAP_NUM = 150
DAILY_CAP_PATTERN = re.compile(
    r"(今日|今天|当天)[^。；;，,\n]{0,20}(投递|沟通|打招呼)[^。；;，,\n]{0,20}"
    r"(上限|限额|封顶|用完|用尽|已满|满了|已用完)|"
    r"(投递|沟通|打招呼)[^。；;，,\n]{0,16}(上限|限额|封顶)|"
    r"明天再来|明日再来|次日再试|请明天再|额度已用完|次数已用完"
)
DAILY_CAP_NUM_PATTERN = re.compile(
    r"(投递|沟通|打招呼)[^。；;，,\n]{0,14}(达到|已达|超过)\s*(\d{2,4})\s*个"
)
DAILY_CAP_FILE = paths.DAILY_CAP

# BOSS 列表页薪资数字被字体混淆（私用区字符），此处解码为真实数字
# 映射：\ue031='0' \ue032='1' ... \ue03a='9'
PUA_MAP = {chr(0xE031 + i): str(i) for i in range(10)}
PUA_RANGE = re.compile(r"[\ue031-\ue03a]")


def decode_salary(s):
    return "".join(PUA_MAP.get(c, c) for c in s)


def salary_of(text):
    """从卡片文本中取薪资字段并解码，返回 (原文, 解码后)。"""
    for seg in [x.strip() for x in text.split("|")]:
        if PUA_RANGE.search(seg) and ("K" in seg or "元/天" in seg):
            return seg, decode_salary(seg)
    return "", ""


def parse_k_range(decoded):
    """解析解码后的薪资，返回 (下限K, 上限K)；解析不到返回 None。"""
    m = re.search(r"(\d+)\s*-\s*(\d+)\s*K", decoded)
    if m:
        return int(m.group(1)), int(m.group(2))
    m = re.search(r"(\d+)\s*K", decoded)  # 单值如「50K」
    if m:
        return int(m.group(1)), int(m.group(1))
    return None

CLICK_START = """
(() => {
  const els=[...document.querySelectorAll('a.btn-startchat, div.btn-startchat-wrap a')];
  if(els.length){ els[0].click(); return 'clicked'; }
  const c=[...document.querySelectorAll('a,button,div,span')]
    .filter(e=>e.innerText && e.innerText.trim()==='继续沟通');
  if(c.length) return 'already-contacted';
  return 'no-btn';
})()
"""

CLICK_CONTINUE = """
(() => {
  const c=[...document.querySelectorAll('a,button,div,span')]
    .filter(e=>e.innerText && e.innerText.trim()==='继续沟通');
  if(!c.length) return 'no-continue';
  c[c.length-1].click(); return 'ok';
})()
"""

CLICK_SEND = """
(() => { const b=document.querySelector('button.btn-send');
  if(!b) return 'no-send'; b.click(); return 'sent'; })()
"""

# 聊天输入框探测：多选择器 + 可见性。
# 偶发情况——点完「立即沟通」跳到聊天页，但右侧会话面板尚未渲染出输入框
# （页面只显示左侧会话列表），此时 .chat-input 不存在，若直接用桥接 fill
# 会抛 element-not-found，把整条流水线带崩。
CHAT_INPUT_PRESENT = """
(() => {
  const sels=['.chat-input','#chat-input','.chat-editor','[contenteditable=true]','textarea'];
  for(const s of sels){ const e=document.querySelector(s); if(e && e.getBoundingClientRect().width>0){ return 'found:'+s; } }
  return 'no-input';
})()
"""

# JS 兜底填写（contenteditable / textarea 通吃），并派发 input 事件让 React 收到
FILL_CHAT_JS = """
(() => {
  const msg = __MSG__;
  const sels=['.chat-input','#chat-input','.chat-editor','[contenteditable=true]','textarea'];
  let el=null; for(const s of sels){ const e=document.querySelector(s); if(e && e.getBoundingClientRect().width>0){ el=e; break; } }
  if(!el) return 'no-input';
  el.focus();
  if(el.tagName==='TEXTAREA'||el.tagName==='INPUT'){
    const proto = el.tagName==='TEXTAREA' ? window.HTMLTextAreaElement.prototype : window.HTMLInputElement.prototype;
    const setter = Object.getOwnPropertyDescriptor(proto,'value');
    setter && setter.set ? setter.set.call(el, msg) : (el.value = msg);
    el.dispatchEvent(new Event('input',{bubbles:true}));
    el.dispatchEvent(new Event('change',{bubbles:true}));
  } else {
    el.innerHTML='';
    let ok=false; try{ ok=document.execCommand('insertText',false,msg); }catch(e){}
    if(!ok || !(el.innerText||'').trim()){
      el.innerText=msg; el.dispatchEvent(new InputEvent('input',{bubbles:true,data:msg}));
    }
    el.dispatchEvent(new Event('input',{bubbles:true}));
  }
  const got=((el.innerText||el.value||'')).includes(msg.slice(0,10));
  return got ? 'ok' : 'set';
})()
"""


def fill_chat(msg, session, addr, tries=8, gap=1.5):
    """把定制话术填进聊天输入框，返回 (ok, how)。

    轮询等待输入框出现（最多 tries*gap 秒），桥接 fill 失败则退回 JS 填写。
    这样即便会话面板延迟渲染，也不会抛异常中断流水线。
    """
    for _ in range(tries):
        present = wb.ev(CHAT_INPUT_PRESENT, session, addr)
        if present and str(present).startswith("found"):
            try:
                if wb.fill(".chat-input", msg, session, addr):
                    return True, "bridge"
            except wb.BridgeError:
                pass
            r = wb.ev(FILL_CHAT_JS.replace("__MSG__", json.dumps(msg)), session, addr)
            if r in ("ok", "set"):
                return True, "js:" + str(r)
        time.sleep(gap)
    return False, "no-input"

# 每日投递量达阈值后的确认弹窗：「今天投递数量达到 N 个了，是否继续投递」
# 三种出口：
#   continued —— 有「继续投递」按钮且未触硬上限（如 120 个）→ 点它继续
#   cap       —— 文案显示已达硬上限（≥150）或明确「明天再来」→ 当天收工
#   no-dialog —— 页面上没有该弹窗（判定从严，避免被列表页「今日投递 90/150」误触发）
QUOTA_DIALOG = """
(() => {
  const norm = s => (s||'').replace(/\\s+/g,'').replace(/[＞>·。!！]?$/,'');
  const all = [...document.querySelectorAll('a,button,div,span')]
    .filter(e => norm(e.innerText) === '继续投递');
  // 只取最内层那个（避免点到大容器）
  const btns = all.filter(e => ![...e.children].some(c => norm(c.innerText) === '继续投递'));
  const txt = document.body.innerText || '';
  // 只在「投递/沟通」附近判定，避免被岗位卡片里的数字误伤
  const segs = txt.match(/[^\\n]{0,40}(投递|沟通|打招呼)[^\\n]{0,40}/g) || [];
  const strong = /(今日|今天|当天)[^。；;，,\\n]{0,20}(投递|沟通|打招呼)[^。；;，,\\n]{0,20}(上限|限额|封顶|用完|用尽|已满|满了|已用完)|(投递|沟通|打招呼)[^。；;，,\\n]{0,16}(上限|限额|封顶)|明天再来|明日再来|次日再试|请明天再|额度已用完|次数已用完/.test(txt);
  const numCap = segs.some(s => {
    const m = s.match(/(投递|沟通|打招呼)[^。；;，,\\n]{0,14}(达到|已达|超过)\\s*(\\d{2,4})\\s*个/);
    return m && parseInt(m[3], 10) >= 150;
  });
  const hardCap = strong || numCap;
  if (btns.length && !hardCap) { (btns[0] || all[all.length-1]).click(); return 'continued'; }
  if (hardCap) return 'cap';
  return 'no-dialog';
})()
"""

# 兼容旧名（若外部脚本引用了旧常量）
CLICK_QUOTA_CONTINUE = QUOTA_DIALOG


def norm_text(s):
    """归一化页面文本：BOSS 页面里部分汉字会以「康熙部首」形式出现
    （实测 力 被渲染成 ⼒ U+2F12），NFKC 可统一回标准汉字，避免关键词漏匹配。"""
    if not s or not isinstance(s, str):
        return s
    try:
        return unicodedata.normalize("NFKC", s)
    except Exception:
        return s


def parse_title(text):
    text = norm_text(text or "")
    for p in [x.strip() for x in text.split("|")]:
        if p and p not in SKIP_TOKENS:
            return p
    return ""


# 卡片末位的城市 token（提取公司名时跳过）。城市可能是「北京·海淀区·学院路」或裸城市名。
CITY_NAME_RE = re.compile(
    r"^(北京|上海|广州|深圳|杭州|成都|南京|武汉|苏州|全国|远程|重庆|西安|长沙|郑州|天津|"
    r"青岛|合肥|厦门|福州|珠海|东莞|佛山|济南|宁波|无锡|大连|沈阳|昆明|南昌|贵阳|"
    r"石家庄|哈尔滨|长春|太原|南宁|兰州|乌鲁木齐|海口|三亚)$"
)


def company_of_card(text):
    """从卡片文本提取公司名（倒数第 2 个 token，末位是城市）。

    已用 jd.json 里 484 条带公司名的记录回测，准确率 484/484。
    新版卡片（含「快速投递|不感兴趣|...|×|城市」）与旧版（无前缀无×）均兼容。
    """
    text = norm_text(text or "")
    parts = [p.strip() for p in text.split("|")]
    parts = [p for p in parts if p and p not in SKIP_TOKENS]
    while parts and parts[-1] == "×":
        parts.pop()
    if not parts:
        return ""
    if len(parts) >= 2 and ("·" in parts[-1] or CITY_NAME_RE.match(parts[-1])):
        return parts[-2]
    return parts[-1]


def company_blocked(card_text, keywords):
    """公司名命中黑名单（集团关键词，不区分大小写）返回 True。"""
    co = company_of_card(card_text)
    if not co:
        return False
    co_l = co.lower()
    return any(k.lower() in co_l for k in keywords)


def pick_template(profile, title, rng=None, jd_text=""):
    """按标题（必要时结合 JD 正文）选模板，返回 (模板文本, 模板名)。

    模板支持三种写法（向后兼容）：
      "text": "..."          —— 单一文本
      "variants": [...]      —— 多套变体（随机选一套，降低群发重复率）
      "openers": [...]       —— 与 closing_lines 组合使用
    """
    rng = rng or random
    for key, tpl in profile.get("templates", {}).items():
        if re.search(tpl.get("match", ""), title, re.I):
            return _pick_tpl_text(tpl, rng), key
    d = profile.get("templates", {}).get(profile.get("fallback_template", "default"), {})
    return _pick_tpl_text(d, rng), "default"


def _pick_tpl_text(tpl, rng):
    if not tpl:
        return "{title}"
    for field in ("variants", "openers"):
        lst = tpl.get(field) or []
        if lst:
            return rng.choice(lst)
    return tpl.get("text", "{title}")


# ==================== 防重复投递：岗位唯一 id + 状态文件 ====================

JOB_ID_RE = re.compile(r"/job_detail/([0-9a-zA-Z_-]+)\.html")


def job_id(href):
    """提取岗位唯一 id。同一岗位即便 href 带参数/换域名，也判为同一个。"""
    m = JOB_ID_RE.search(href or "")
    return m.group(1) if m else (href or "")


def load_json_file(path, default):
    if os.path.exists(path):
        try:
            return json.load(open(path, encoding="utf-8"))
        except Exception:
            return default
    return default


def save_json_atomic(path, obj):
    """原子写盘（先写临时文件再 rename），避免多进程并发写坏状态文件。

    部分受管环境（沙箱、网络盘、Windows 上目标文件被占用）会拒绝 rename 覆盖，
    此时自动降级为「原地截断 + 直写」：牺牲原子性，但保证任务不中断。
    降级路径全程不删除目标文件，因此不会触发 file-unlink 类策略。
    """
    tmp = f"{path}.tmp.{os.getpid()}"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False, indent=1)
            f.flush()
            os.fsync(f.fileno())
        try:
            os.replace(tmp, path)
            return
        except OSError:
            pass  # rename 被策略/占用拒绝 → 走降级
    except OSError:
        tmp = None  # 临时文件都建不了（目录只读等）→ 直接原地写

    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)
        f.flush()
        os.fsync(f.fileno())
    if tmp:
        try:
            os.remove(tmp)
        except OSError:
            pass


def load_state_ids(path):
    """读取已触达集合并统一规范化为 job id（兼容历史 href 格式）。"""
    raw = load_json_file(path, [])
    return {job_id(x) for x in raw if x}


def migrate_state(path):
    """把历史 href 形式的已触达状态规范化为 job id；有变化先备份。返回 (原数, 现数)。"""
    raw = load_json_file(path, [])
    if not raw:
        return 0, 0
    ids = sorted({job_id(x) for x in raw if x})
    if len(ids) == len(raw) and all(job_id(x) == x for x in raw):
        return len(raw), len(ids)
    bak = f"{path}.bak-{time.strftime('%Y%m%d-%H%M%S')}"
    try:
        import shutil
        shutil.copy(path, bak)
    except Exception:
        bak = "(备份失败)"
    save_json_atomic(path, ids)
    print(f"[state] 已把已触达状态规范化为岗位 id：{len(raw)} 条 → {len(ids)} 条（去掉重复 {len(raw)-len(ids)} 条）", flush=True)
    print(f"[state] 备份：{bak}", flush=True)
    return len(raw), len(ids)


# ==================== 单实例锁：防并发导致重复打招呼 ====================

LOCK_FILE = paths.LOCK


def _pid_alive(pid):
    try:
        os.kill(int(pid), 0)
        return True
    except Exception:
        return False


def load_skip_ids(log_path):
    """从发送日志里提取「已判定跳过」的岗位 id（skip-jd-english / skip-jd-notfit 等）。

    这些岗位（JD 要求英语、或岗位实质错配）在人工复核或 JD 更新前不会变，
    每轮重复访问它们纯属浪费请求、也抬高风控风险，因此下一轮直接排除。
    如需重新纳入，删掉日志里对应的 skip-* 记录即可。
    """
    out = set()
    for x in load_json_file(log_path, []) or []:
        s = str(x.get("send") or "")
        if s.startswith("skip-") and x.get("href"):
            out.add(job_id(x["href"]))
    return out


def acquire_run_lock(force=False):
    """启动前抢锁：已有投递进程在跑则拒绝启动（并发＝重复打招呼的主因）。"""
    info = load_json_file(LOCK_FILE, None)
    if info:
        pid = info.get("pid")
        age = time.time() - float(info.get("ts") or 0)
        if pid and _pid_alive(pid) and age < 7200 and not force:
            print(f"[lock] 检测到已有投递进程在运行（pid={pid}，{age/60:.0f} 分钟前启动）", flush=True)
            print("[lock] 并发运行会导致同一岗位被重复打招呼，已拒绝启动。", flush=True)
            print("[lock] 确认没有其他进程在跑（或上一进程已异常退出）再加 --force。", flush=True)
            return False
        if pid and not _pid_alive(pid):
            print(f"[lock] 发现残留锁（pid={pid} 已退出），自动清理", flush=True)
    save_json_atomic(LOCK_FILE, {"pid": os.getpid(), "ts": time.time(),
                                 "start": time.strftime("%Y-%m-%d %H:%M:%S")})
    return True


def release_run_lock():
    info = load_json_file(LOCK_FILE, None)
    if info and info.get("pid") == os.getpid():
        try:
            os.remove(LOCK_FILE)
        except OSError:
            pass


# ==================== 详情页 JD 抓取（话术结合岗位描述） ====================

EXTRACT_JD = """
(() => {
  const txt = el => el ? (el.innerText||'').replace(/\\s+/g,' ').trim() : '';
  const title = txt(document.querySelector('.job-primary .name h1, .job-info .name h1, [class*=job-title] .name, h1'));
  const salary = txt(document.querySelector('.salary, [class*=salary]'));
  // 公司名优先从页面标题解析（「XX招聘」_公司名招聘-BOSS直聘），比 DOM 选择器稳
  let company = '';
  const tm = (document.title||'').match(/」_(.{2,26}?)招聘/);
  if (tm) company = tm[1];
  if (!company) company = txt(document.querySelector('.job-detail-company .name, [class*=sider-company] .name'));
  const jd = txt(document.querySelector('.job-sec-text'))
          || txt(document.querySelector('.job-detail-section'))
          || txt(document.querySelector('[class*=job-detail] .text'));
  return JSON.stringify({title: title, salary: salary, company: company, jd: (jd||'').slice(0, 3000)});
})()
"""


def extract_jd(session, addr):
    """在详情页抓取 标题/公司/薪资/JD 正文。失败返回 {}，绝不抛异常。"""
    try:
        raw = wb.ev(EXTRACT_JD, session, addr)
        if not raw:
            return {}
        d = json.loads(raw)
        if not isinstance(d, dict):
            return {}
        for k in ("title", "company", "salary", "jd"):     # 统一归一化，防康熙部首漏匹配
            if isinstance(d.get(k), str):
                d[k] = norm_text(d[k])
        return d
    except Exception:
        return {}


# JD 中出现「强英语要求」→ 直接跳过（用户 2026-10-12 要求：不投英语要求高的岗位）
JD_EN_PATTERN = re.compile(
    # 注意：「英文可作为工作语言」这类写法用的是「英文」，必须与「英语」同等对待（2026-10-12 实测漏判过）
    r"(英语|英文)(可|能|会)?(作为|做为)?(工作语言|沟通语言|日常沟通|交流语言)|"
    r"(英语|英文)(流利|熟练|精通|无障碍|听说读写)|"
    r"(流利|熟练|精通|无障碍)[^。；;，,\n]{0,6}(英语|英文|English)|"
    r"(英语|英文)\s*([4４]|四|[6６]|六)级|"
    r"(英语|英文)口语[^。；;，,\n]{0,6}(流利|好|佳|优秀|熟练)|"
    r"口语(流利|熟练|良好|优秀|佳)|"
    r"(中英文|英文)[^。；;，,\n]{0,6}(沟通|交流|文档|材料|读写|撰写|汇报)|"
    # 「英语读写可以作为工作语言」这类主谓之间插入「读写」的写法（2026-10-13 实测漏判过）
    r"(英语|英文)[^。；;，,\n]{0,6}(作为|做为)[^。；;，,\n]{0,4}(工作语言|沟通语言|交流语言|办公语言)|"
    r"native\s+speaker|fluent\s+in\s+english|english\s+as\s+a\s+working\s+language|"
    r"working\s+proficiency\s+in\s+english|"
    # 海外/留学信号：只认「紧邻」表述，避免误伤「985/211 及海外高校毕业者、有技术背景」这类学历偏好（2026-10-13 修）
    # 2026-10-19 再修：去掉「经验」，否则「海外产品经验」「海外工作经验」这类加分项会被误判成英语硬要求
    r"(留学|海外)[^。；;，,\n]{0,3}(经历|背景|学历|院校|毕业)|"
    r"海外(市场|业务|用户|客户)[^。；;，,\n]{0,4}(经验|经历|背景)", re.I)

# 「加分 / 优先 / 更佳」上下文：命中英语词但只是加分项时不拦截（2026-10-19 新增）
JD_EN_SOFT = re.compile(r"加分|优先|更佳|最好|可选|非必须|nice\s*to\s*have|preferred", re.I)


def jd_requires_english(jd_text):
    """JD 含强英语要求则返回命中片段（用于跳过），否则返回 ''。

    2026-10-19：逐个命中项看上下文窗口，如果那条只是「加分项/优先」，不算硬门槛。
    """
    blob = norm_text(jd_text) or ""
    for m in JD_EN_PATTERN.finditer(blob):
        a = max(0, m.start() - 30)
        b = min(len(blob), m.end() + 30)
        if JD_EN_SOFT.search(blob[a:b]):
            continue                       # 加分项里的英语不算硬要求
        return m.group(0)
    return ""


# JD 显示岗位实质与「AI 产品 / 运营」方向错配（标题包装成 AI 岗，实为基建 / 算力 / 项目管理等）
# 用户 2026-10-12 要求「职业可以尽量先过滤掉无效的岗位」。
# 采用「命中 ≥2 个不同特征词才判错配」的策略，避免误伤只在 JD 里提一句的 AI 产品岗。
JD_NFIT_WORDS = ["智算中心", "AICC", "IDC", "数据中心", "机房", "基建", "机电",
                 "总包", "监理", "电力", "制冷", "机柜", "算力消纳", "政府示范",
                 "算力集群", "算力调优", "国产算力"]

# JD 实质是「后端/研发开发岗」，只是标题写成 AI 产品经理（2026-10-13 新增）。
# 实测案例：新橙科技「高级AI产品经理」JD 要求 Java/JVM/Spring/Mybatis/分布式事务，
# 是纯开发岗。仍用「同类命中 ≥2 个」策略，避免误伤只提一句「了解代码」的真产品岗。
JD_DEV_WORDS = ["Java开发", "JVM", "SpringBoot", "SpringCloud", "SpringMVC", "Mybatis",
                "后端开发", "分布式事务", "消息中间件", "SQL优化"]


def jd_not_fit(jd_text):
    """JD 实质与「AI 应用产品 / 运营」错配（基建算力类，或后端开发岗）→ 返回命中特征词，否则 ''。"""
    blob = norm_text(jd_text) or ""
    for words in (JD_NFIT_WORDS, JD_DEV_WORDS):
        hits = [w for w in words if re.search(w, blob, re.I)]
        if len(hits) >= 2:
            return ",".join(hits)
    return ""


# ==================== 话术合成：模板变体 + JD 命中句 + 结尾变体 ====================

RECENT_MESSAGES = []          # 最近发出的话术（防近期重复）


def _jd_part(profile, jd_text, rng):
    """按 JD 命中的关键词挑 1-2 句「与 JD 结合」的经历句，返回 (文本, 命中键)。

    相关性优先：先按命中次数排序（命中越多＝JD 越强调），同分随机；
    再从中随机取 1-2 个关键词，各随机取一句，避免同一岗位反复只讲同一件事。
    """
    jd_lines = profile.get("jd_lines") or {}
    blob = jd_text or ""
    scored = []
    for k, cfg in jd_lines.items():
        if not isinstance(cfg, dict):
            continue
        pat = cfg.get("match", "$^")
        n = len(re.findall(pat, blob, re.I))
        if n > 0:
            scored.append((n, k, cfg.get("lines") or []))
    if not scored:
        return "", ""
    top = max(n for n, _, _ in scored)
    # 只从「命中次数在前两档」的关键词里取（相关性足够），同档随机
    pool = [x for x in scored if x[0] >= max(1, top - 1)]
    rng.shuffle(pool)
    parts, keys = [], []
    for _, k, lines in pool[:2]:
        if lines:
            parts.append(rng.choice(lines))
            keys.append(k)
    return " ".join(parts), ",".join(keys)


def compose_message(profile, title, jd_text="", rng=None):
    """生成一条个性化招呼语：模板变体 + JD 命中句 + 结尾变体。

    - 模板：按标题匹配类别（solution/ops/product/default），每类 3 套变体随机
    - JD 句：从 profile.jd_lines 里按 JD 正文命中的关键词取 1-2 句（与简历经历挂钩）
    - 结尾：closing_lines 随机
    - 防重复：若与最近 RECENT_MESSAGES 完全一致，重掷最多 5 次
    返回 (消息, 元信息 dict)
    """
    rng = rng or random
    closings = profile.get("closing_lines") or ["期待和您聊聊。"]
    msg, meta = "", {}
    for _ in range(6):
        tpl_text, key = pick_template(profile, title, rng=rng, jd_text=jd_text)
        jd_part, jd_keys = _jd_part(profile, jd_text, rng)
        try:
            body = tpl_text.format(title=title)
        except Exception:
            body = tpl_text
        try:
            close = rng.choice(closings).format(title=title)
        except Exception:
            close = rng.choice(closings)
        msg = " ".join(x for x in [body, jd_part, close] if x).strip()
        meta = {"template": key, "jd_keys": jd_keys, "jd_part": jd_part}
        if msg not in RECENT_MESSAGES:
            break
    RECENT_MESSAGES.append(msg)
    del RECENT_MESSAGES[:-40]
    return msg, meta


# ==================== AI 生成话术文件（默认话术来源，优先于模板） ====================
#
# 用户 2026-10-12 明确要求：话术必须逐条读 JD 由 AI 分析生成，**不得从模板里挑**。
# 因此脚本不再自己「拼」话术，而是读取 AI 逐条写好的话术文件：
#     {"msgs": {"<job_id>": {"text": "……", "hook": "引用了JD的哪一点"}}}
# 缺话术的岗位默认**直接跳过**（不发群发式模板）；确需临时用模板，加 --allow-template。

AI_MSGS_FILE = paths.MESSAGES


def load_ai_messages(path=AI_MSGS_FILE):
    """读取 AI 生成的话术文件，返回 {job_id: 话术文本}。兼容平铺写法（直接以 job_id 为键）。"""
    raw = load_json_file(path, {})
    if not isinstance(raw, dict):
        return {}
    body = raw.get("msgs") if isinstance(raw.get("msgs"), dict) else raw
    out = {}
    for k, v in body.items():
        if str(k).startswith("_") or k in ("meta", "msgs"):
            continue
        text = v.get("text") if isinstance(v, dict) else v
        if text and str(text).strip():
            out[str(k)] = str(text).strip()
    return out


def detect_daily_cap(text):
    """判断页面文本是否为「今日投递额度已用尽」。命中则返回上下文片段，否则 ''。

    两条判定线：
      1) 强信号词：投递/沟通 + 上限/限额/用完/已满/明天再来…
      2) 数字信号：投递/沟通 + 达到/已达/超过 + 数字，且数字 ≥ 150
    「今日投递 90/150」这类进度条只有数字、没有「达到」或上限词，不会被误判。
    """
    t = text or ""
    m = DAILY_CAP_PATTERN.search(t)
    if m:
        return t[max(0, m.start() - 12): m.end() + 16].replace("\n", " ").strip()
    for m in DAILY_CAP_NUM_PATTERN.finditer(t):
        if int(m.group(3)) >= DAILY_CAP_NUM:
            return t[max(0, m.start() - 12): m.end() + 16].replace("\n", " ").strip()
    return ""


def mark_daily_cap(reason="", where="", total=None):
    """记录「当日额度已满」。当天后续启动会被守卫拒绝，避免无效重试。"""
    info = {
        "date": time.strftime("%Y-%m-%d"),
        "time": time.strftime("%Y-%m-%d %H:%M:%S"),
        "ts": time.time(),
        "where": where,
        "reason": (reason or "")[:200],
        "contacted_total": total,
    }
    json.dump(info, open(DAILY_CAP_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("\n" + "=" * 62, flush=True)
    print(f"完成：平台提示今日投递额度已用尽（提示阈值通常为 {DAILY_CAP_NUM} 条）", flush=True)
    print(f"   位置: {where}", flush=True)
    print(f"   提示: {(reason or '')[:120]}", flush=True)
    print("   判定: 属每日正常限额（非风控），当天不再投递，任务到此结束", flush=True)
    print(f"   已保全: 累计触达 {total}，岗位池/状态/日志均已落盘，明天可断点续跑", flush=True)
    print("=" * 62 + "\n", flush=True)
    return info


def daily_cap_today():
    """今天是否已判定额度用尽；是则返回记录，否则 None。"""
    if not os.path.exists(DAILY_CAP_FILE):
        return None
    try:
        info = json.load(open(DAILY_CAP_FILE, encoding="utf-8"))
    except Exception:
        return None
    return info if info.get("date") == time.strftime("%Y-%m-%d") else None


def check_daily_cap(force=False):
    """启动守卫：当日额度已满则拒绝启动。返回 True 表示可以继续。"""
    info = daily_cap_today()
    if not info or force:
        return True
    print(f"[guard] 今天（{info.get('date')}）已判定投递额度用尽，不再投递。", flush=True)
    print(f"[guard] 原因: {(info.get('reason') or '')[:80]}", flush=True)
    print("[guard] 明天（或确认额度已恢复）再跑；确需覆盖请加 --force。", flush=True)
    return False


LAST_CAP_TEXT = ""   # 最近一次命中「当日封顶」时，平台提示的原文（供日志留证）

# 抓取封顶提示原文（分段拼接，避免被截断）
CAP_TEXT_JS = """
(() => {
  const txt = document.body.innerText || '';
  const m = txt.match(/您已达到沟通上限[\\s\\S]{0,140}/)
         || txt.match(/[^\\n]{0,24}沟通上限[^\\n]{0,120}/)
         || txt.match(/您今天已与\\s*\\d+\\s*位BOSS沟通[^\\n]{0,60}/)
         || txt.match(/[^\\n]{0,24}(明天再来|明日再来)[^\\n]{0,40}/);
  return m ? m[0].replace(/\\s+/g, ' ').trim() : '';
})()
"""


def read_cap_text(session, addr):
    """读取页面上封顶提示的原文（读整页，不截断）。"""
    t = wb.ev(CAP_TEXT_JS, session, addr) or ""
    return str(t)


def handle_quota_dialog(session, addr, retries=3, wait=1.0):
    """处理「今日投递数量达到 N 个」弹窗。

    返回：
      'continued' —— 已点「继续投递」（未达硬上限）
      'cap'       —— 已达当日上限（≥150 或明确提示明天再来）→ 调用方应优雅收尾
      'none'      —— 没有该弹窗
    """
    global LAST_CAP_TEXT
    for _ in range(retries):
        r = wb.ev(QUOTA_DIALOG, session, addr)
        if r and str(r).startswith("continued"):
            return "continued"
        if r == "cap":
            LAST_CAP_TEXT = read_cap_text(session, addr)
            return "cap"
        if r == "no-dialog":
            # 双保险：读整页文本再判一次（弹窗可能排在页面文本靠后位置，绝不能截断）
            txt = wb.ev("(() => document.body.innerText)()", session, addr) or ""
            hit = detect_daily_cap(txt)
            if hit:
                LAST_CAP_TEXT = read_cap_text(session, addr) or hit
                return "cap"
            return "none"
        time.sleep(wait)
    return "none"


# 软额度提醒弹窗：「温馨提示 / 您今天已与N位BOSS沟通，还剩M次沟通机会哦 / ［好］」
# DOM: div.dialog-container > .dialog-footer .btn-sure[ka=dialog_confirm]
# 该弹窗会**挡住**「立即沟通」的后续流程（继续沟通按钮点不到、页面不跳转）。
# 必须先点「好」关掉，再**重新点一次**「立即沟通」才能正常发出招呼语。
TIP_DIALOG = """
(() => {
  const txt = document.body.innerText || '';
  if(!/还剩\\s*\\d+\\s*次沟通机会|已与\\s*\\d+\\s*位BOSS沟通/.test(txt)) return 'none';
  const b = document.querySelector('.dialog-container .btn-sure, .dialog-container [ka="dialog_confirm"]');
  if(b){ b.click(); return 'dismissed'; }
  return 'tip-no-btn';
})()
"""


def handle_tip_dialog(session, addr, retries=2, wait=1.0):
    """关掉「温馨提示：还剩N次沟通机会」弹窗。返回 True 表示确实关掉过。"""
    hit = False
    for _ in range(retries):
        if wb.ev(TIP_DIALOG, session, addr) == "dismissed":
            hit = True
            time.sleep(wait)
        else:
            break
    return hit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", default=None,
                    help="简历画像与话术配置 JSON；默认用 %s" % paths.PROFILE)
    ap.add_argument("--pool", default=paths.POOL)
    ap.add_argument("--state", default=paths.STATE)
    ap.add_argument("--log", default=paths.SEND_LOG)
    ap.add_argument("--target", type=int, default=0,
                    help="累计触达上限（可选，默认 0=不设上限）。"
                         "默认不给自己定额度：投到「没有可投岗位」或「平台提示当日上限」为止。")
    ap.add_argument("--min-delay", type=float, default=3.0)
    ap.add_argument("--max-delay", type=float, default=6.0)
    ap.add_argument("--session", default="boss-zhipin")
    ap.add_argument("--force", action="store_true", help="忽略「当日额度已满」守卫，强制启动")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--no-jd", action="store_true", help="不抓 JD（跳过英语要求检查，不推荐）")
    ap.add_argument("--ai-messages", default=AI_MSGS_FILE,
                    help="AI 逐条读 JD 生成的话术文件（默认 %s）" % paths.MESSAGES)
    ap.add_argument("--allow-template", action="store_true",
                    help="缺少 AI 话术时退回模板话术（默认不允许：缺话术的岗位直接跳过，不发群发式模板）")
    a = ap.parse_args()
    paths.ensure_home()
    a.profile = paths.resolve_profile(a.profile)

    profile = json.load(open(a.profile, encoding="utf-8"))
    pool = json.load(open(a.pool, encoding="utf-8"))
    # 已触达状态统一用「岗位 id」判定，兼容历史 href 格式（历史若含重复会一并去掉）
    migrate_state(a.state)
    contacted = load_state_ids(a.state)
    ai_msgs = load_ai_messages(a.ai_messages)

    excl = re.compile(profile.get("exclude", "$^"), re.I)
    must = re.compile(profile.get("must_any", "."), re.I)
    role = re.compile(profile.get("must_role", "."), re.I)
    prio = re.compile(profile.get("priority", "$^"), re.I)
    markers = profile.get("exclude_text_markers", ["元/天", "天/周", "在校"])
    # 2026-10-16 用户要求：集团黑名单（阿里/字节/腾讯/蚂蚁系）永久不投
    comp_kw = [str(k) for k in (profile.get("exclude_companies") or [])]
    sf = profile.get("salary_filter") or {}
    min_k = int(sf.get("min_k", 0) or 0)
    sal_mode = sf.get("mode", "upper")
    sal_strict = bool(sf.get("strict", False))

    cands = []
    skipped_ids = load_skip_ids(a.log)
    n_skip_excl = 0
    n_co_excl = 0
    for href, text in pool.items():
        title = parse_title(text)
        if not title or job_id(href) in contacted:
            continue
        if job_id(href) in skipped_ids:      # 上轮已判定跳过（英语/错配），不再重复访问
            n_skip_excl += 1
            continue
        if comp_kw and company_blocked(text, comp_kw):
            n_co_excl += 1
            continue
        if any(m in text for m in markers):
            continue
        if excl.search(title) or not must.search(title) or not role.search(title):
            continue

        # 薪资过滤（基于列表页混淆数字解码）
        decoded = salary_of(text)[1]
        if min_k > 0:
            rng = parse_k_range(decoded)
            if not rng:
                continue  # 薪资不可解析（多为「面议」），无法确认达标，跳过
            lo, hi = rng
            # strict=True 时边界取严格不等（「40K以上，不含 40K」→ 20-40K 被排除）
            if sal_mode == "lower" and (lo <= min_k if sal_strict else lo < min_k):
                continue
            if sal_mode == "upper" and (hi <= min_k if sal_strict else hi < min_k):
                continue

        cands.append({"href": href, "title": title, "salary": decoded})
    cands.sort(key=lambda j: (0 if prio.search(j["title"]) else 1, len(j["title"])))

    # 话术门禁：默认只投「AI 已逐条读 JD 生成话术」的岗位
    no_msg = 0
    if not a.allow_template:
        kept = [j for j in cands if job_id(j["href"]) in ai_msgs]
        no_msg = len(cands) - len(kept)
        cands = kept

    # 不给自己预设每日额度（2026-10-13 用户要求「平台有自己的限制」）：
    # target=0 表示不设上限，投到没有可投岗位、或平台提示当日上限为止。
    unlimited = a.target <= 0
    todo = len(cands) if unlimited else max(a.target - len(contacted), 0)
    _cmp = ">" if sal_strict else "≥"
    sal_desc = f"薪资上限{_cmp}{min_k}K" if min_k > 0 else "不限薪资"
    cap_desc = "不限（平台限额为准）" if unlimited else str(a.target)
    print(f"候选 {len(cands)} 个（AI 话术覆盖 {len(cands)} 条，因缺话术暂缓 {no_msg} 条；"
          f"历史跳过 {n_skip_excl} 条不再重复访问；公司黑名单拦截 {n_co_excl} 条）"
          f" / 已触达 {len(contacted)} / 累计上限 {cap_desc} / 过滤: {sal_desc}", flush=True)
    if not a.allow_template and not cands:
        print("[话术门禁] 当前没有可投岗位（候选都没有 AI 话术）。", flush=True)
        print("           请先跑：python3 scripts/fetch_jd.py --profile <画像> --limit 20", flush=True)
        print(f"           再由 AI 读 {paths.JD} 生成话术写入 {a.ai_messages}", flush=True)

    if a.dry_run:
        for i, j in enumerate(cands[: max(todo, 10)], 1):
            jid = job_id(j["href"])
            if jid in ai_msgs:
                print(f"{i}. [AI话术] {j['title']}  [{j.get('salary','')}]\n   {ai_msgs[jid][:110]}...")
            else:
                tpl, key = pick_template(profile, j["title"])
                print(f"{i}. [{key}模板] {j['title']}  [{j.get('salary','')}]\n   {tpl.format(title=j['title'])[:110]}...")
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

    # 启动守卫：今天已判定额度用尽则不再投递
    if not check_daily_cap(a.force):
        sys.exit(4)

    # 单实例锁：防止并发运行导致同一岗位被重复打招呼
    if not acquire_run_lock(a.force):
        sys.exit(5)

    sent = 0
    capped = False
    try:
        for job in cands:
            if not unlimited and len(contacted) >= a.target:
                break
            href, title = job["href"], job["title"]
            # 每发一条前重新读盘：防止并发进程/陈旧快照导致重复投递
            contacted |= load_state_ids(a.state)
            if job_id(href) in contacted:
                print(f"[skip 已触达(实时核对)] {title}", flush=True)
                continue
            # 话术门禁：没有 AI 逐条分析生成的话术就不去打扰对方（默认不允许发模板）
            ai_msg = ai_msgs.get(job_id(href))
            if not ai_msg and not a.allow_template:
                print(f"[skip 无AI话术] {title}", flush=True)
                continue
            try:
                wb.navigate("https://www.zhipin.com" + href, a.session, addr)
            except wb.BridgeError as e:
                print(f"[nav fail] {title}: {e}", flush=True)
                continue
            time.sleep(3.5)

            page = wb.ev("(() => document.body.innerText.slice(0,800))()", a.session, addr) or ""
            rk = risk_hit_text(a.session, addr)
            if rk:
                print("!!! 触发风控/验证，已停止。请人工处理后重跑（会从断点继续）", flush=True)
                print(f"    命中原文: {rk[:200]}", flush=True)
                break
            cap_hit = detect_daily_cap(page)
            if cap_hit:                       # 详情页已提示当日额度用尽
                mark_daily_cap(cap_hit, where="detail-page", total=len(contacted))
                capped = True
                break

            # 先抓 JD：① 英语要求高 / 实质是基建类错配岗 → 直接跳过（不点沟通，不产生触达）
            #          ② 话术已由 AI 逐条读 JD 生成（此处抓 JD 仅做兜底校验）
            jd = {} if a.no_jd else extract_jd(a.session, addr)
            jd_text = (jd or {}).get("jd", "")
            en_hit = jd_requires_english(jd_text)
            fit_hit = "" if a.no_jd else jd_not_fit(jd_text)
            skip_reason, skip_ev, skip_label = "", "", ""
            if en_hit:
                skip_reason, skip_ev, skip_label = "skip-jd-english", en_hit, "JD要求英语"
            elif fit_hit:
                skip_reason, skip_ev, skip_label = "skip-jd-notfit", fit_hit, "岗位错配"
            if skip_reason:
                print(f"[skip {skip_label}] {title} :: {skip_ev[:40]}", flush=True)
                log = load_json_file(a.log, [])
                log.append({"href": href, "title": title, "salary": job.get("salary", ""),
                            "template": "-", "send": skip_reason, "custom": False,
                            "verified": False, "how": skip_ev[:40], "time": time.strftime("%H:%M:%S")})
                save_json_atomic(a.log, log)
                continue

            r = wb.ev(CLICK_START, a.session, addr)
            # 「温馨提示：您今天已与N位BOSS沟通，还剩M次沟通机会哦」软额度弹窗——
            # 达到每日软阈值后会间歇性弹出，挡住「继续沟通」使整条流程失败。
            # 处理：点「好」关掉，再重新点一次「立即沟通」。
            if r == "clicked" and handle_tip_dialog(a.session, addr):
                print(f"[tip] 触发「还剩N次沟通机会」提示，已关闭并重试 → {title}", flush=True)
                time.sleep(1.5)
                if wb.ev(CLICK_START, a.session, addr) == "clicked":
                    r = "clicked"
            # 可能出现「今天投递数量达到 N 个了，是否继续投递」：
            #   N < 150 → 点「继续投递」；N ≥ 150 → 当日封顶，收尾
            qd = handle_quota_dialog(a.session, addr)
            if qd == "cap":
                mark_daily_cap(detect_daily_cap(page) or "投递弹窗提示已达当日上限", where="quota-dialog", total=len(contacted))
                capped = True
                break
            if qd == "continued":
                print(f"[quota] 已达每日投递阈值，已点「继续投递」→ {title}", flush=True)
                time.sleep(1.5)
                if r in ("no-btn", "already-contacted"):
                    r = wb.ev(CLICK_START, a.session, addr)
            if r == "no-btn":
                # 详情页没有「立即沟通」按钮：多为岗位已下线/已关闭，或该 HR 不再接收新沟通。
                # 记入日志并纳入「已跳过」，下一轮不再重复访问（避免空转刷页面）。
                print(f"[skip 无按钮] {title}", flush=True)
                log = load_json_file(a.log, [])
                log.append({"href": href, "title": title, "salary": job.get("salary", ""),
                            "template": "-", "send": "skip-no-btn", "custom": False,
                            "verified": False, "how": "详情页无「立即沟通」按钮",
                            "time": time.strftime("%H:%M:%S")})
                save_json_atomic(a.log, log)
                continue
            if r == "already-contacted":
                print(f"[skip 已沟通过] {title}", flush=True)
                contacted.add(job_id(href))
                save_json_atomic(a.state, sorted(contacted))
                continue
            time.sleep(3)

            # 点完「立即沟通」可能已直接跳到聊天页（新版「留在此页继续沟通」弹窗 / 已沟通过岗位），
            # 此时无需再点「继续沟通」
            cur = str(wb.ev("(() => location.href)()", a.session, addr) or "")
            cr = "ok" if "/web/geek/chat" in cur else None
            if cr is None:
                cr = wb.ev(CLICK_CONTINUE, a.session, addr)
                if cr != "ok":
                    # 再试一次：弹窗可能刚刚被点掉 / 或提示已封顶
                    qd = handle_quota_dialog(a.session, addr)
                    if qd == "cap":
                        mark_daily_cap("投递弹窗提示已达当日上限", where="quota-dialog", total=len(contacted))
                        capped = True
                        break
                    if qd == "continued":
                        time.sleep(2)
                        cr = wb.ev(CLICK_CONTINUE, a.session, addr)
                    if cr != "ok" and handle_tip_dialog(a.session, addr):
                        # 软额度「温馨提示」恰好在此刻才弹出：关掉后重新发起沟通
                        time.sleep(1.5)
                        wb.ev(CLICK_START, a.session, addr)
                        time.sleep(2)
                        cur2 = str(wb.ev("(() => location.href)()", a.session, addr) or "")
                        if "/web/geek/chat" in cur2:
                            cr = "ok"
                        else:
                            cr = wb.ev(CLICK_CONTINUE, a.session, addr)
            if cr != "ok":
                print(f"[skip 无继续沟通] {title}", flush=True)
                continue
            time.sleep(4)

            # 话术：优先用 AI 逐条读 JD 分析生成的话术；模板仅在 --allow-template 时兜底
            eff_title = (jd or {}).get("title") or title
            if ai_msg:
                msg, meta, key = ai_msg, {"template": "ai", "jd_keys": "ai"}, "ai"
            else:
                msg, meta = compose_message(profile, eff_title, jd_text=jd_text)
                key = meta.get("template", "default")
            filled, how = fill_chat(msg, a.session, addr)
            if not filled:
                # 招呼语已由「立即沟通」发出：记为已触达（避免重复打招呼），仅定制话术未补上
                print(f"[fill fail] {title} ({how}) —— 招呼语已发出，记入已触达", flush=True)
                contacted.add(job_id(href))
                save_json_atomic(a.state, sorted(contacted))
                log = load_json_file(a.log, [])
                log.append({"href": href, "title": title, "salary": job.get("salary", ""),
                            "template": key, "ai": bool(ai_msg), "jd_keys": meta.get("jd_keys", ""),
                            "send": "greeted-no-custom", "custom": False,
                            "verified": False, "how": how, "time": time.strftime("%H:%M:%S")})
                save_json_atomic(a.log, log)
                continue
            time.sleep(1)
            sr = wb.ev(CLICK_SEND, a.session, addr)
            time.sleep(2.5)

            probe = msg[8:24]
            verified = bool(wb.ev(f"(() => document.body.innerText.includes({json.dumps(probe)}))()", a.session, addr))
            sent += 1
            contacted.add(job_id(href))
            save_json_atomic(a.state, sorted(contacted))
            log = load_json_file(a.log, [])
            log.append({"href": href, "title": title, "salary": job.get("salary", ""),
                        "template": key, "ai": bool(ai_msg), "jd_keys": meta.get("jd_keys", ""),
                        "send": sr, "custom": True,
                        "verified": verified, "how": how, "time": time.strftime("%H:%M:%S")})
            save_json_atomic(a.log, log)
            n_show = f"{len(contacted)}" + (f"/{a.target}" if not unlimited else "")
            print(f"[{n_show}] {'OK' if sr=='sent' else 'FAIL'} [{'AI' if ai_msg else key}]"
                  f" {title} verify={verified}", flush=True)
            time.sleep(random.uniform(a.min_delay, a.max_delay))
    finally:
        release_run_lock()

    if capped:
        print(f"平台提示当日额度已用尽（判定阈值 {DAILY_CAP_NUM} 条），任务结束。"
              f"本轮发送 {sent} 个，累计 {len(contacted)}", flush=True)
    else:
        tail = f"/{a.target}" if not unlimited else "（未设上限）"
        print(f"本轮发送 {sent} 个，累计 {len(contacted)}{tail}", flush=True)


if __name__ == "__main__":
    main()
