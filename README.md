# boss-zhipin-auto-apply

BOSS 直聘求职投递全流程自动化：**收岗位 → 按画像筛选 → AI 逐条读 JD 写定制话术 → 拟人化节奏批量发送 → 回执核验**。

所有操作都跑在**你自己已登录的浏览器**里（通过本地浏览器桥接扩展），不接触账号密码、不伪造请求、不碰服务端接口。

> 🇨🇳 本项目为中文求职场景设计，README 以中文为主。

---

## ⚠️ 使用前必读（先读这个，再决定要不要用）

**[完整免责声明见 DISCLAIMER.md](DISCLAIMER.md)**，要点：

1. 本项目与 BOSS 直聘官方**无任何关联与授权**。平台用户协议通常不允许自动化批量投递，使用本项目**可能导致账号被限制或封禁，风险自负**。
2. 本项目**仅供个人求职自用**，禁止用于代投服务、批量营销或任何商业用途（见 LICENSE 附加条款）。
3. 请保持克制：只投你真正感兴趣的岗位。消息以你的名义发出，内容你负全责。
4. 代码中的拟人化间隔、公司黑名单、每日节奏控制是**负责任使用的底线**，请不要调低或移除。

如果以上任何一条你不能接受，请不要使用本项目。

---

## 架构

```
┌────────────────────────────  本机  ────────────────────────────┐
│                                                                │
│  collect_jobs / refresh_pool      fetch_jd                     │
│  （搜索页滚动收池子）──► pool.json ──► 筛选 ──► jd.json          │
│        ▲                              │                        │
│        │                              ▼                        │
│  浏览器扩展 ◄── webbridge 守护    AI 读 JD 逐条写话术            │
│  （用户已登录的浏览器）              ──► messages.json           │
│        ▲                              │                        │
│        │                              ▼                        │
│  send_greetings / run_pipeline / run_forever                   │
│  （拟人化节奏发送 + 回执核验 + 风控/封顶熔断）                     │
└────────────────────────────────────────────────────────────────┘
```

- **状态与个人数据**全部落在 `~/.boss-apply/`（本机，不进仓库）。
- **画像配置**：`assets/profile-template.json` 是空白骨架，首次运行
  `setup_wizard.py` 生成你自己的 `profile.json`。

## 组件一览

| 文件 | 职责 |
|---|---|
| `scripts/collect_jobs.py` | 搜索页滚动收集岗位池（多城市×关键词） |
| `scripts/refresh_pool.py` | 双线刷池：频道标签 + 城市×关键词×薪资档 |
| `scripts/fetch_jd.py` | 批量抓取候选岗位详情页 JD |
| `scripts/send_greetings.py` | 核心发送端：导航→立即沟通→填话术→发送→核验 |
| `scripts/run_pipeline.py` | 流水线模式：边收集边投递，小批量+冷却 |
| `scripts/run_forever.py` | 守护模式：队列投完待命，来了新话术自动续投 |
| `scripts/daemonize.py` | 后台守护化（双 fork，macOS 兼容） |
| `scripts/doctor.py` | 环境体检：桥接/扩展/登录态一键诊断 |
| `scripts/setup_wizard.py` | 首次配置引导，生成 profile.json |
| `scripts/webbridge.py` | 浏览器桥接封装（唯一的外部交互层） |
| `references/zhipin-dom-and-flow.md` | BOSS 页面 DOM 特征与投递流程笔记 |

## 环境要求

- Python **3.10+**（**零第三方依赖**，纯标准库）
- 一个已登录 BOSS 直聘的桌面浏览器
- 浏览器桥接：[kimi-webbridge](https://www.kimi.com/) 本地守护 + 扩展
  （默认 `127.0.0.1:10086`，可用环境变量 `BOSS_BRIDGE_ADDR` / `BOSS_BRIDGE_BIN` 覆盖）

## 快速开始

```bash
git clone https://github.com/<you>/boss-zhipin-auto-apply.git
cd boss-zhipin-auto-apply

# 1. 首次配置：生成 ~/.boss-apply/profile.json（城市/关键词/薪资底线）
python3 scripts/setup_wizard.py

# 2. 环境体检：桥接守护 + 浏览器扩展 + 登录态
python3 scripts/doctor.py

# 3. 收池子（示例：北京，3 个关键词，各滚 6 轮）
python3 scripts/collect_jobs.py --keywords "AI产品经理" "AI解决方案" "Agent产品经理" --cities 101010100

# 4. 抓 JD（只抓通过了画像筛选的候选）
python3 scripts/fetch_jd.py --limit 20

# 5. 让 AI 读 jd.json，逐条写定制话术写入 ~/.boss-apply/messages.json
#    写作规范在 profile.json 的 ai_message_rules 段
#    （格式：{"msgs": {"<job_id>": {"text": "…"}}}）

# 6a. 小批量流水线（边收边投，推荐）
python3 scripts/run_pipeline.py --target 50

# 6b. 或守护模式：投完队列不退出，来新话术自动续投
python3 scripts/daemonize.py python3 scripts/run_forever.py
```

先跑 `--dry-run` 看发送端会投给谁，再实投。

## 必要信息示例（照着填就行）

初始化要准备的「必要信息」= **你是谁、想去哪、找什么岗、薪资底线、真实经历**。
以下示例人物纯属虚构。

### ① 配置草稿（AI 引导模式 `--from-json` 的输入）

```json
{
  "owner": "李同学",
  "cities": ["北京", "杭州"],
  "keywords": ["AI产品经理", "大模型产品经理", "Agent产品经理"],
  "salary_min_k": 30,
  "channels": ["AI产品经理(北京)"],
  "resume": {
    "summary": "5 年 B 端产品经验，近 2 年专注大模型应用落地",
    "current": "某电商公司 · 高级产品经理（2022.06-至今）",
    "highlights": [
      "主导智能客服 Agent 平台 0→1，人工会话占比下降 40%",
      "搭建 RAG 知识库，检索准确率从 72% 提升到 91%",
      "推动 3 条业务线接入统一的 Prompt 评测体系"
    ]
  },
  "exclude_extra": "军工|涉密",
  "note": "不接受纯远程岗位"
}
```

```bash
python3 scripts/setup_wizard.py --from-json draft.json
```

要点：`highlights` 是 AI 写话术的**唯一素材**，务必真实、尽量带量化指标；
`keywords` 至少 3 个；`cities` 支持中文名（内置 22 城）或 BOSS 搜索页 URL 里的城市代码。

### ② 生成的 profile.json（关键字段节选）

```json
{
  "owner": "李同学",
  "cities": [{"code": "101010100", "name": "北京"}, {"code": "101210100", "name": "杭州"}],
  "keywords": ["AI产品经理", "大模型产品经理", "Agent产品经理"],
  "salary_filter": {"min_k": 30, "mode": "upper", "strict": true},
  "channels": ["AI产品经理(北京)"],
  "use_recommend_tab": true,
  "exclude_companies": ["字节", "抖音", "阿里", "腾讯", "蚂蚁"],
  "exclude_text_markers": ["元/天", "天/周", "在校"]
}
```

`salary_filter` 读法：`min_k=30 + mode=upper + strict=true` ⇒ **只投薪资区间上限 >30K**
的岗位（20-30K、25-30K 被排除；25-40K、30-50K 通过）。`exclude_companies`
是公司黑名单：公司名包含任一关键词即永久不投，适合把投过很多次的巨头整个集团排掉。

### ③ AI 写好的话术（messages.json，一条的样子）

```json
{
  "msgs": {
    "44bcea12e8bc3ada0nN62tu7E1tT": {
      "text": "您好！看到岗位要求搭建 Agent 编排与 RAG 评测体系，正是我去年从 0 到 1 做过的：智能客服 Agent 平台上线后人工会话占比下降 40%，RAG 检索准确率做到 91%。评测这块也踩过坑，有一套现成的指标体系可以直接迁移。期待和您聊聊。"
    }
  }
}
```

键是岗位 id（JD 详情页 URL 里的那串）；`text` 必须引用**该岗位 JD 的具体内容**、
素材只来自 `resume.highlights`、结尾统一「期待和您聊聊。」、单条 120–220 字。
写好后再运行发送端，只有出现在 `msgs` 里的岗位才会被投递（话术门禁）。

> 完整字段说明见 [docs/1-usage-and-config.md](docs/1-usage-and-config.md)。

## 内置的负责任使用设计

- **AI 话术门禁**：没有为该岗位逐条生成定制话术就不发送，杜绝群发模板。
- **公司黑名单**：`profile.json` 的 `exclude_companies` 支持集团级关键词，
  命中即永久不投（选人 + 发送端双重拦截），避免反复骚扰同一家公司。
- **严格薪资过滤**：`salary_filter` 支持「上限 >N K」等精确口径。
- **拟人化节奏**：岗位间隔 4–9s、每 4 条长休息、随机滚动停顿、城市×关键词乱序。
- **三态额度处理**：软提醒自动重发、真封顶熔断当日停止、风控命中立即退出。
- **回执核验**：每条发送后回到详情页确认按钮状态，失败不虚报。

## 换桥接实现（适配器接口）

所有浏览器交互都收敛在 `scripts/webbridge.py`，对外只有 6 个动作。
想接 Playwright / Selenium，实现同样签名即可，上层脚本零改动：

| 函数 | 语义 |
|---|---|
| `ensure_daemon()` | 确保桥接可用，返回地址 |
| `check_extension(addr)` | 返回 `(ok, message)` |
| `navigate(url, session, addr)` | 打开页面 |
| `ev(js_code, session, addr)` | 执行 JS 并返回值（列表页收集/页面探测全靠它） |
| `fill(selector, value, session, addr)` | 向输入框填文本（聊天框） |
| `call(action, args, session, addr)` | 通用动作入口 |

## 测试与 CI

```bash
python3 -m unittest discover -s tests -v     # 纯函数测试，无需浏览器
```

解析器（标题/公司名/薪资解码）、黑名单匹配、风控词表等核心逻辑都有单测，
GitHub Actions 会自动跑 lint（ruff）+ 测试。

## FAQ

**Q：会被封号吗？** 有可能。见 DISCLAIMER。请自行评估，建议小号先行。

**Q：为什么发了消息但脚本报失败？** 发送后脚本会回详情页核验「继续沟通」
按钮状态，核验不过就记失败——宁可少记不可虚报。

**Q：平台改版后失效了？** BOSS 前端 DOM 常改。选择器集中在各脚本顶部的
JS 常量里，按 `references/zhipin-dom-and-flow.md` 自查即可。项目按现状
（as-is）提供，不承诺跟进每次改版。

**Q：支持其他招聘平台吗？** 目前只做了 BOSS 直聘。桥接层与平台无关，
欢迎按适配器接口贡献智联/猎聘实现。

## 深入文档

- [docs/1-usage-and-config.md](docs/1-usage-and-config.md) —— 用户教程：初始化配置的三种方式、profile.json 全字段说明、本机数据文件、典型工作流
- [docs/2-execution-details.md](docs/2-execution-details.md) —— 执行细节：「推荐标签」与「搜索找岗位」双线供给的分工、排序与枯竭策略
- [docs/3-humanized-behavior.md](docs/3-humanized-behavior.md) —— 拟人化设计全解：滚动/节奏/话术/额度/风控的每一处参数与原则

## License

MIT + 非商业附加条款，见 [LICENSE](LICENSE) 与 [DISCLAIMER.md](DISCLAIMER.md)。
