# BOSS 直聘（zhipin.com）页面结构、操作流程与坑位清单

本文件是实现细节，遇到选择器失效、按钮点不动、结果可疑时先查这里。

## 1. 前置依赖：Kimi 浏览器扩展（kimi-webbridge）

所有操作都跑在**用户自己已登录的浏览器**里，不碰账号密码，也不需要 cookie。

```bash
# 状态检查（含扩展是否连接）
~/.kimi-webbridge/bin/kimi-webbridge status
# 未安装时（脚本会提示）：
# curl -fsSL https://cdn.kimi.com/webbridge/install.sh | bash
```

- 守护进程默认 `http://127.0.0.1:10086`，调用方式 `POST /command`，body：
  `{"action":"<动作>","args":{...},"session":"<任务名>"}`
- 常用动作：`navigate` / `evaluate` / `fill` / `click` / `snapshot` / `screenshot` / `close_session`
- `status` 里 `extension_connected: false` → 守护进程正常但浏览器侧没连上，需用户打开 Kimi 侧边栏确认连接（设置 → 本地智能体远程控制 → `ws://127.0.0.1:10086/ws`）。
- 出错码 `extension_not_connected` → 同上，别去重启守护进程。
- **不要**自动执行 `stop`/`restart`/`upgrade`/`uninstall`。

## 2. 关键 URL

| 用途 | URL |
|---|---|
| 搜索列表 | `https://www.zhipin.com/web/geek/jobs?query=<关键词URL编码>&city=<城市码>` |
| 职位详情 | `https://www.zhipin.com/job_detail/<id>.html` |
| 聊天页 | `https://www.zhipin.com/web/geek/chat` |

城市码：北京 `101010100`（其他城市在搜索页 URL 的 `city=` 参数里能直接看到）。

**详情页可以直接用 URL 打开**，不需要从列表点进去；且详情页的薪资是明文（列表页不是，见第 5 条）。

## 3. 页面结构与选择器

| 元素 | 选择器 | 备注 |
|---|---|---|
| 列表卡片容器 | `[class*=job-card-wrap]` | 是 `div`，**不是 `li`**；`li.job-card-wrapper` 在这版页面拿不到东西 |
| 卡片内链接 | 卡片内 `a` | `href` 形如 `/job_detail/xxxx.html` |
| 详情页「立即沟通」 | `a.btn-startchat`（或 `div.btn-startchat-wrap a`） | 页面上会出现多组（顶部/底部各一套），取第 0 个即可 |
| 「继续沟通」 | 文本完全等于"继续沟通"的 `a/button/div/span` | 出现多个，取**最后一个**点击 |
| 聊天输入框 | `.chat-input` | `contenteditable`，用 `fill` 动作写入（会正确触发 input 事件）；**偶发未渲染，需轮询 + 兜底选择器 + JS，见坑位 ⑧** |
| 输入框兜底选择器 | `.chat-input` → `#chat-input` → `.chat-editor` → `[contenteditable=true]` → `textarea` | 取第一个「可见」的（`getBoundingClientRect().width > 0`） |
| 发送按钮 | `button.btn-send` | 输入内容后 `disabled=false`，`click()` 即发送 |
| 详情页标题 | `.job-primary .name h1, .job-info .name h1, [class*=job-title] .name, h1` | 比列表页标题准 |
| 详情页薪资（明文） | `.salary, [class*=salary]` | 详情页不混淆 |
| 详情页公司名 | 页面标题 `「XX招聘」_<公司名>招聘-BOSS直聘` 正则取 | DOM 选择器不稳，优先用 title 解析 |
| **JD 正文** | `.job-sec-text`（兜底 `.job-detail-section`） | 用于「话术结合 JD」与英语要求过滤，实测可取全文 |
| 搜索页「薪资待遇」筛选头 | `.condition-filter-select .current-select`（文本以「薪资待遇」开头） | 已选条件会显示成「薪资待遇(1)」 |
| 搜索页频道标签 | 「推荐」= `.c-expect-select a.synthesis`；意向频道 = `.expect-list a.expect-item`（文本 = `.text-content`） | 点击后 SPA 重渲染会丢标签栏 |

## 4. 打招呼完整流程（5 步）

1. `navigate` 到 `https://www.zhipin.com/job_detail/<id>.html`，等 3.5s。
2. 点击「立即沟通」→ **系统会自动发出一条默认招呼语**（"您好，对贵公司很感兴趣，希望能和您聊聊"），按钮变成「继续沟通」，并弹出"已向BOSS发送消息"提示框。
3. 点击「继续沟通」→ 页面跳转到 `/web/geek/chat`，左侧会话列表新增该 Boss 会话。
4. `fill` 定制话术到 `.chat-input`。
5. 点击 `button.btn-send` 发送；校验方式：`document.body.innerText.includes(<话术片段>)` 为 true。

> 每条定制话术都紧跟在那条默认招呼语之后，招聘方看到的是两条连续消息，属正常现象。

> ⚠️ **话术不再由脚本合成**（2026-10-12 定版）：脚本只负责按 `job_id` 从
> `/tmp/boss-messages.json` 取 **AI 逐条读 JD 写好**的话术；取不到就**跳过该岗位**，不退回模板。
> 文件格式：`{"msgs": {"<job_id>": {"text": "...", "hook": "引用了 JD 的哪一点"}}}`（平铺写法也兼容）。
> 抓 JD 与发消息是分开的两步，见 SKILL.md Step 1.5。

## 5. 坑位清单

**① 列表页薪资数字抓不到**
BOSS 对数字做了字体混淆，`innerText` 里薪资只剩 `- K· 薪`，数字是空的（显示为 `\ue0xx` 私有区码位）。
→ 需要薪资时**截图后用 Read 看图**，或直接打开详情页读明文。

**② 卡片文本混入悬浮层文字**
滚动加载后的卡片文本形如：
`快速投递 | 不感兴趣 | AI产品经理 | ... | 公司名 | × | 北京·朝阳区·xx`
→ 解析标题必须跳过 `快速投递 / 不感兴趣 / × / 感兴趣` 等词，取第一个有效 token。

**③ 实习岗混在结果里**
标题不带"实习"，但文本里有 `元/天`、`天/周`、`在校`（按天计薪 + 每周天数 + 应届）。
→ 把这三个标记当作排除条件。

**④ 「继续沟通」按钮偶尔不出现**
偶发点击了「立即沟通」但没渲染出「继续沟通」（页面状态异常）。
→ 记录并跳过，下一轮重跑时该岗位通常会恢复正常（实测重跑 8/8 成功）。
→ **注意**：点「立即沟通」的瞬间默认招呼语就已经发出了，所以此时该岗位其实**已触达**。新逻辑为：不再退回候选池重发（会重复打招呼），而是记入已触达、日志标 `custom:false`。

**⑤ 频控与风控**
- 主动沟通有每日额度（页面上显示 `今日投递 x/150`）。
- 连续快速操作可能触发安全验证。
→ 每个岗位之间随机延迟 3-6 秒；每轮开始检查页面是否出现 `安全验证|滑动验证|请完成验证|访问受限|系统检测到|操作过于频繁`，命中立即停止并交回用户人工处理（脚本支持断点续跑）。

**⑥ 话术重复率**
同一段话术原样群发容易被判定为骚扰。
→ 按岗位类别使用 6 套模板（讲师/培训/解决方案/运营/产品/通用），且每段都带上岗位名做个性化。

**⑦ 窗口焦点**
桥接在后台标签页操作，不需要抢用户当前窗口；但**不要**在此期间让用户手动操作同一浏览器，容易打断流程。
→ 任务开始前提示用户：本次操作的页面会收集在标签组里，不要手动关闭。

**⑧ 聊天页 `.chat-input` 偶发不存在（曾导致整条流水线崩溃）**
点「立即沟通」跳到 `/web/geek/chat` 后，**右侧会话面板偶尔尚未渲染**——页面只显示左侧会话列表，正文是「与您进行过沟通的 Boss 都会在左侧列表中显示」，此时 `.chat-input` 不存在。
→ 旧实现直接 `wb.call("fill", {"selector": ".chat-input", ...})`，元素找不到会抛 `BridgeError`，**未捕获 → 整条进程崩溃**（实测跑 1h、投到 260 时崩）。
→ 正确做法：
  1. **轮询等待**：最多 8 次 × 1.5s，先探测输入框是否可见再填；
  2. **多选择器兜底**（见第 3 节表格）；
  3. **JS 兜底写入**：`contenteditable` 用 `execCommand('insertText')`，失败则 `innerText = msg` 并派发 `input` 事件；`textarea/input` 用原生 setter + `input`/`change` 事件；
  4. **任何单条异常都要 try/except 兜住**，只跳过该条，绝不中断整条流水线；
  5. 填不进去也不回退候选池（招呼语已发出，算已触达）。

**⑨ 「温馨提示：还剩N次沟通机会」软额度弹窗（最隐蔽，曾导致连续 17 条静默失败）**
当日沟通量达到一定量后，点「立即沟通」不再直接发招呼语，而是弹一个确认框：

```html
<div class="dialog-container">
  <div class="dialog-title"><h3 class="title">温馨提示</h3></div>
  <div class="dialog-con"><p>您今天已与120位BOSS沟通，还剩30次沟通机会哦</p></div>
  <div class="dialog-footer"><div class="btns"><span class="btn btn-sure" ka="dialog_confirm">好</span></div></div>
</div>
```

- **症状**：`CLICK_START` 返回 `clicked`（元素在、`.click()` 调了），但页面**不跳转**、`继续沟通` 点不到 → 后续全失败。它**不是**风控、也不会命中 `DAILY_CAP` 判定（文案里没有「上限/明天再来」），极易被漏掉。
- **处理**：点 `好`（`.dialog-container .btn-sure` 或 `[ka=dialog_confirm]`）关掉，**然后必须重新点一次「立即沟通」**，招呼语才会真正发出、页面才会跳聊天页。
- **判定要点**：文案为「已与N位BOSS沟通，还剩M次沟通机会」——是**软提醒**（还能继续投 M 次），与「您已达到沟通上限…明天再来」（真封顶）不同。
- **数据严谨性**：拿不到「继续沟通」时，必须回详情页复核按钮是「立即沟通」还是「继续沟通」——
  仍显示「立即沟通」＝招呼语**没发出**，绝不能记为已触达（否则统计虚高、且漏掉真实触达）。
  实测本次事故中 17 条被误记为已触达，回查详情页全部仍显示「立即沟通」。
- **相关动作**：排查时优先用桥接**原生 click**（真实鼠标事件）复现该弹窗；纯 JS `.click()` 有时无反应。

**⑩ 风控正则误伤 JD 正文 → 假熔断（2026-10-12 实锤）**

- **症状**：跑得好好的，突然打印「触发平台风控提示 —— 已立即熔断」，累计停在某条岗位上。
- **实际原因**：不是平台风控。旧代码用 `body.innerText.slice(0,800)` 整段跑正则，
  而风控词表里有**裸词 `爬取`**，正好命中了某个岗位 JD 里的「机构网站**数据爬取**」。
- **排查方法**（30 秒确认是不是误报）：
  1. 看当前 URL：仍是 `/job_detail/xxx.html`（没有跳转到验证页）→ 大概率误报；
  2. 只读扫一次告警区（不刷新、不滚动）：
     ```python
     import send_greetings as sg
     print(repr(sg.risk_hit_text('boss-zhipin', addr)))   # 误报时为 ''
     print(sg.RISK_PATTERN.findall(body_text))            # 会看到命中的是 JD 里的词
     ```
  3. 检查有无 `.dialog-container` / 验证弹窗：误报时为空。
- **修复（已落地）**：
  1. **词表精确化**：删掉裸词 `爬取`，只保留平台固定措辞 `频繁过度爬取` / `过度爬取岗位`；
     同理不要用单字、常用名词做风控词。
  2. **只扫告警区**：新增 `RISK_ALERT_JS` + `risk_hit_text()`，只扫
     `.dialog-container / [class*=toast] / [class*=verify] / [class*=captcha] / [class*=error-page]` 等，
     **不扫 JD 正文**；仅当「页面没有职位结构且正文极短」时才回落到整页文本（覆盖整页拦截场景）。
  3. **取证留档**：`mark_risk()` 现在会写入 `evidence`（命中原文片段），日志也打印，
     下次一眼就能分辨真假。
- **教训**：凡是「一键熔断」的判定，**词表要精确 + 扫描范围要收窄 + 必须留原文取证**，
  否则假警报比漏报更耗时（本次白停了 3 小时里的最后一段 + 需要人工复判）。

**⑩ 重复投递（同一岗位被投两次）—— 2026-10-12 实测并修复**

- **现象**：`/tmp/boss-send-log.json` 里 22 个 href 各出现两次：第一次 `custom=false`
  （只发了系统默认招呼语），约 20 分钟后第二次 `custom=true`（补齐了定制话术）。
- **根因**：**两次运行/两个进程同时在跑**，各自在启动时把 `contacted` 读进内存，
  写入状态文件时互相覆盖 → 后启动的那个看不到前一个的写入，于是重复打招呼。
  另有一个诱因：状态以 href 判定，href 只要有一点差异（带参/换域名）就会被判成新岗位。
- **四道防线**（已在 `run_pipeline.py` / `send_greetings.py` 内置）：
  1. `acquire_run_lock()` 单实例锁（`/tmp/boss-run.lock`）——并发直接拒绝启动（`exit(5)`）；
  2. 状态改用 `job_id(href)` 判定 + `migrate_state()` 规范化历史文件（先备份）；
  3. 每次发送前 / 每周期开始前 `load_state_ids()` **重新读盘**，不用陈旧内存快照；
  4. `save_json_atomic()` 原子写盘，避免并发写坏文件。
- **不要**用 `--force` 去覆盖锁或额度守卫，除非确认没有其他进程在跑。

**⑪ 话术重复（群发感）**

- 只按「标题」选模板时，同类别岗位话术正文完全相同，仅 `{title}` 不同 → 一眼看出群发。
- 现在：**话术由 AI 逐条读 JD 现场撰写**（三段式见 SKILL.md Step 1.5），脚本只按 `job_id`
  取用；缺话术即跳过，不退回模板。想换方向就改 `profile.ai_message_rules` 与
  `resume_points`（写作规范与真实素材），不要在脚本里拼句子。

**⑫ JD 层过滤（拿到正文后才判断）**

- 英语：`(英语|英文)(可|能)?(作为)?(工作语言|…)` —— **「英文可作为工作语言」这类写法必须覆盖**
  （2026-10-12 实测漏判过一次）；另含「英语流利/四六级/native speaker/海外·留学经验优先」。
- 错配岗：JD 命中 **≥2 个**基建特征词（智算中心/AICC/IDC/机房/基建/机电/总包/监理/电力/制冷…）
  才判无效——阈值取 2 是为了不误伤「服务智算中心行业」这类正常 AI 产品岗。
  实测：某「AI运营总监」JD 实际是机房基建项目管理岗，命中 13 个词被正确拦下。

## 6. 数据文件约定

| 文件 | 内容 |
|---|---|
| `/tmp/boss-pool.json` | 岗位池 `{"/job_detail/xx.html": "卡片文本"}`，增量累加 |
| `/tmp/boss-src.json` | 岗位来源标记 `{href: "channel:推荐" / "channel:频道名" / "search:档位码"}`（候选排序用） |
| `/tmp/boss-jd.json` | **JD 库**：`{job_id: {title, company, salary, jd, english_hit, not_fit_hit, src}}`，`fetch_jd.py` 产出，AI 生成话术的输入 |
| `/tmp/boss-messages.json` | **AI 话术文件**：`{"msgs": {job_id: {"text": ..., "hook": ...}}}`，发送时的唯一话术来源 |
| `/tmp/boss-contacted.json` | **已触达岗位 id 列表**（不是 href！去重与断点续跑的依据） |
| `/tmp/boss-send-log.json` | 发送日志，含岗位、话术来源（`ai: true/false`）、发送结果、校验结果、时间 |
| `/tmp/boss-run.lock` | 单实例锁（内含 pid/启动时间），正常退出自动删除 |
| `/tmp/boss-skipped.json` | 跳过池（岗位 id）：点不出按钮 / 填不进去 / JD 要求英语 / 岗位错配 |

**断点续跑**：调大 `--target` 重跑即可，已触达的会被自动跳过。

**状态文件格式**：统一存「岗位 id」而非 href（`/job_detail/<id>.html` 里的 `<id>`）。
历史 href 格式会在启动时由 `migrate_state()` 自动规范化，并备份为
`/tmp/boss-contacted.json.bak-<YYYYMMDD-HHMMSS>`。

## 7. 结果核验建议

- 脚本日志里 `verify=True` 表示聊天区确实出现了该话术片段。
- 复核可打开 `/web/geek/chat` 截图看会话列表，新会话会排在最上面并显示消息摘要。
