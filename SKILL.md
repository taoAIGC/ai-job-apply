---
name: 闪电AI求职助手
name_en: ai-job-apply
description: |
  BOSS 直聘（zhipin.com）求职投递全流程自动化。This skill should be used when the user wants to
  search jobs, screen postings, mass-send tailored greetings (打招呼/立即沟通/投递简历), or track
  replies on BOSS 直聘 / zhipin.com. Covers: collecting job pools by scrolling search pages,
  filtering postings against the user's own resume profile, generating per-job greeting messages by
  having the AI read each job description (JD) one by one (never by picking from templates), and
  batch-sending them through the user's own logged-in browser via the Kimi browser extension.
  Triggered by phrases like "帮我投简历/打招呼/找工作", "BOSS 上找 XX 岗位", "继续投 10 个",
  "boss直聘投递", or any request to search or contact employers on BOSS 直聘.
description_en: |
  End-to-end automation for applying to jobs on BOSS Zhipin (zhipin.com): collect postings,
  screen them against the user's own resume profile, write a tailored greeting for each job by
  reading its description, and batch-send via the user's own logged-in browser.
version: 2.1.0
license: 仅供个人求职自用。使用者需自行遵守 BOSS 直聘用户协议，并承担账号相关风险。见「使用前必读」。
agent_created: true
---

# 闪电AI求职助手 · BOSS 直聘投递自动化（分发版）

## 用途

把「找岗位 → 筛岗位 → 写话术 → 打招呼 → 核验」这条链路自动化。所有操作跑在用户**自己已登录**的浏览器里（通过 Kimi 浏览器扩展 / kimi-webbridge），不接触账号密码，不伪造请求。

## 何时使用

- 用户要求「帮我在 BOSS 上找 XX 岗位 / 投简历 / 打招呼 / 联系 HR」
- 用户要求「继续投 N 个」、「再发 10 家」
- 用户要求筛选、分析 BOSS 直聘上的岗位
- 用户询问 BOSS 上已沟通岗位的进展

---

## ⚠️ 使用前必读（合规与风险）

本技能会**代替你向真实 HR 发消息**，这是对外动作，请先确认你接受以下几点：

1. **平台规则**：BOSS 直聘用户协议通常**不允许**自动化批量投递。使用本工具可能导致账号被限制、降权或封禁。**风险由使用者自负**，请自行确认并遵守平台协议。
2. **不要调成群发机器**：本技能的设计初衷是「像真人一样，认真读 JD、认真写话术、一天投几十个」。把它当垃圾投放器用，既害别人也害自己。
3. **数据只在本机**：你的简历、岗位池、聊天记录全部存在本机 `~/.boss-apply/`，不上传任何服务器。技能包本身**不含任何人的简历**。
4. **首次使用必须完成配置引导**（见下），不要拿别人的配置投自己的岗位。

---

## 环境要求与安装

| 依赖 | 说明 | 检查方式 |
|---|---|---|
| Python ≥ 3.8 | 跑脚本 | 无第三方包依赖，标准库即可 |
| **Kimi 浏览器扩展** | **必须**。所有页面操作（打开、点击、填写、截图）都通过它在你自己的浏览器里执行 | `python3 scripts/doctor.py` |
| 你自己登录的 BOSS 直聘 | 同一浏览器里登录好 | 同上 |
| 可写的 HOME 目录 | 默认 `~/.boss-apply`，可用环境变量 `BOSS_APPLY_HOME` 改 | 同上 |

**安装浏览器扩展**：

```bash
curl -fsSL https://cdn.kimi.com/webbridge/install.sh | bash
```

> 先下载脚本审查内容再执行。安装后在浏览器里打开 Kimi 侧边栏，确认连接到 `ws://127.0.0.1:10086/ws`。

**装完先体检**：

```bash
python3 scripts/doctor.py          # 人话版
python3 scripts/doctor.py --json   # 机器可读（AI 引导时用）
python3 scripts/doctor.py --fix    # 顺手拉起没在跑的守护进程
```

> `--fix` 只会执行 `kimi-webbridge start`（幂等、安全）。**永远不要**自动执行 `stop` / `restart` / `upgrade` / `uninstall`。

---

## Step -1：首次配置引导（第一次用必做，AI 必须执行）

**先判断是否已配置**：

```bash
python3 scripts/setup_wizard.py --check
```

返回 `"ready": true` → 配置就绪，直接进 Step 0。
返回 `"ready": false` 或 `"configured": false` → **不要开始投递**，先走下面的引导。

### 引导怎么做（由对话里的 AI 完成）

目标：把**这个人自己的**求职信息写进 `~/.boss-apply/profile.json`。

> 铁律：**不得沿用技能包里的任何示例**，也不得替用户编造经历。技能包里的 `assets/profile-template.json` 是空白骨架，不含任何人的简历。

**分 4 轮问，一次问一组，不要一口气问完**：

| 轮次 | 问什么 | 对应 draft 字段 |
|---|---|---|
| 1 求职目标 | 想找什么岗位？哪几个城市？薪资底线多少？ | `keywords` / `cities` / `salary_min_k` |
| 2 你的背景 | 一句话自我介绍 + 最近一段经历 + 3~8 条真实亮点（**带数字最好**） | `resume.summary` / `resume.current` / `resume.highlights` |
| 3 排除项 | 哪些行业 / 岗位类型不想投？ | `exclude_extra` |
| 4 频道（可选） | BOSS 顶部有没有「求职意向」标签？分别叫什么？ | `channels` |

把答案写成一份 draft（可直接用 `Write` 工具落盘）：

```json
{
  "owner": "张先生",
  "cities": ["北京", "上海"],
  "keywords": ["AI产品经理", "大模型产品经理", "AIGC产品经理"],
  "salary_min_k": 40,
  "channels": ["AI产品经理(北京)"],
  "resume": {
    "summary": "一句话自我介绍",
    "current": "最近一段经历（公司·职位·时间）",
    "highlights": ["亮点1（带量化指标）", "亮点2", "亮点3"]
  },
  "exclude_extra": "教育|医疗"
}
```

落盘并复核：

```bash
python3 scripts/setup_wizard.py --from-json /tmp/my-profile-draft.json
python3 scripts/setup_wizard.py --check     # 应当 ready: true
python3 scripts/setup_wizard.py --show      # 念给用户核对
```

用户也可以自己在终端填（不通过 AI）：

```bash
python3 scripts/setup_wizard.py --interactive
```

### 引导时必须守住的几条

- `resume.highlights` **必须是用户真实说过的**。AI 可以帮忙改通顺，但不许脑补出对方没提过的经历或数字。
- `cities` 填中文城市名；内置表已覆盖 20+ 主要城市。**不在表里的城市**，让用户去 BOSS 搜索页复制 URL 里的城市代码（形如 `101010100`）直接填。
- 用户说不清薪资底线时，建议「按区间**上限**判定，默认 40K」，让 ta 确认。
- 配置只是起点：**跑几轮后回头调 `keywords` 和 `exclude`** 是常态，不要指望一次配准。
- 配好后，把 `--show` 的输出念一遍给用户确认，**再开始投递**。

---

## 标准工作流

> **推荐使用流水线模式（Step 1）**：小批量「边收集、边投递」。旧的「先收满大池再批量发」模式容易触发平台风控，仅在需要离线分析岗位时使用。

### Step 0：确认画像

配置存在 `~/.boss-apply/profile.json`（由 Step -1 生成）。用户换方向时改这份文件，**不要改脚本**。

需要临时用另一份画像时，加 `--profile <路径>` 覆盖即可。

### Step 1（推荐）：流水线模式——边收集边投递

```bash
python3 scripts/run_pipeline.py --per-cycle 4 --collect-per-cycle 2 --scrolls 3
```

> **不要自设每日额度**：`--target` 默认为 `0`＝不设上限。停止条件只有三个——① 没有「有 AI 话术」的可投岗位；② 平台提示当日上限；③ 命中风控。**平台有自己的限制，以平台为准，不要用累计触达数当额度。**
> 若确实想临时封顶，再显式传 `--target N`。

**岗位来源顺序（内置于流水线）**：

1. **频道优先**：先投 BOSS 推荐标签下的岗位——「推荐」tab + 求职意向频道标签（`profile.channels`）。
   某频道一轮收集新增为 0 即视为枯竭；全部枯竭后才进入搜索。
   `profile.channels` 为空时只刷「推荐」。`--skip-channels` 可完全跳过频道阶段。
2. **搜索分档**：搜索时按 `profile.salary_tiers` 顺序先「50K以上」（salary=407）投完，再「20-50K」（salary=406）。code 与页面「薪资待遇」菜单选项一一对应。
   ⚠️ 菜单下拉经自动化合成/原生点击都展不开（React 受控组件），故用 URL 参数等效实现——页面上会显示与手选菜单完全相同的筛选标签，效果一致。
3. **候选排序**：频道岗位 > 50K以上档 > 20-50K档 > `priority` 词命中 > 标题短者。
   来源标记存 `~/.boss-apply/src.json`（`channel:推荐` / `channel:频道名` / `search:档位码`）。

每个周期做三件事，循环直到「没有可投岗位」或「平台提示当日上限」：

1. **收集小块**：按上述顺序取来源，滚动数轮，**立即落盘**（中断不丢数据）；
2. **投递少量**：从池中筛选候选，发 `--per-cycle` 条（默认 4），逐条校验；
3. **周期冷却**：随机 15-40s。

**拟人化节奏**（内置于 `run_pipeline.py`，降低风控概率）：

- 滚动步长随机、时有回滚、停顿随机（1.2-3.6s）
- 进详情页先「扫一眼 JD」（滚动一下）再点沟通
- 岗位间隔 4-9s；每发 `--rest-every` 条来一次 25-70s 长休息（模拟真人离开）
- 收集与投递交替，不长时间只做一类动作
- 搜索时城市×关键词顺序随机化

先跑小批量（如临时 `--target 20`）验证流程，确认无误再放开。
命中风控关键词立即停止，状态已落盘，人工处理后重跑即可断点续跑。

> 频道收集坑位：① 点击频道后页面 SPA 重渲染会**丢失标签栏**，因此每个频道都从干净的
> `/web/geek/jobs` 页开始；② 偶发点击后被弹到 job_detail 页，脚本检测到后放弃本轮、
> 下轮重试（返回 -1，不算枯竭，不会误删频道）。

### Step 1.5：打招呼话术 = AI 逐条读 JD 现场撰写

**不要用模板挑话术。** 话术一律由 AI 逐条读 JD 后现场撰写；**脚本不自己拼话术，也不从模板里挑**。

**三段式（按序执行）**：

**① 抓 JD**（脚本，只读、零触达、不消耗当日额度）

```bash
python3 scripts/fetch_jd.py --limit 15
```

- 按投递优先级选候选（频道 → 50K以上 → 20-50K），逐条打开详情页读 `.job-sec-text` 正文
- 落盘 `~/.boss-apply/jd.json`：`{job_id: {title, company, salary, jd, english_hit, not_fit_hit, src}}`
- `--limit` 建议 **10-20**（一次交给 AI 的量，太多会稀释注意力）；已有话术的自动跳过，`--refresh` 强制重抓

**② AI 写话术**（本步主体，由对话中的 AI 完成）

- 读 `~/.boss-apply/jd.json`，**逐条分析 JD** 后写 `~/.boss-apply/messages.json`：

```json
{"msgs": {"<job_id>": {"text": "话术正文", "hook": "引用了 JD 的哪一点",
                       "title": "岗位标题", "company": "公司"}}}
```

- 写作规范见 `profile.ai_message_rules`：引用 JD 的具体内容（业务场景/技术栈/职责）、
  只用 `resume_points` 里的**真实经历**、只挑最相关的 1-2 项、100-250 字、
  同一批里不同岗位的骨架/句式不得重复
- **结尾固定**：统一只用一句「期待和您聊聊。」，不要写「想聊聊你们的XX业务/产品/阶段」
  「方便聊 10 分钟吗」这类具体邀约

**③ 发送**（脚本，默认只投「有话术」的岗位）

```bash
python3 scripts/send_greetings.py
# 或流水线：python3 scripts/run_pipeline.py
```

- 启动时读 `~/.boss-apply/messages.json`，按 `job_id` 取话术（`--ai-messages` 可改路径）
- **缺话术的岗位直接跳过**（日志 `[skip 无AI话术]`），绝不退回模板群发语
- 流水线模式下若候选全都没有话术：打印指引并 `exit(6)`，不会空转
- 应急/离线场景可用 `--allow-template` 退回模板（不推荐，且分发版模板为空）

> **为什么不让脚本自己调模型**：脚本是后台 Python 进程，没有理解能力，模板+关键词匹配
> 就是它唯一能做的事——这正是「话术重复」的根因。改由 AI 逐条读 JD 撰写后，
> 同一批岗位在开头、句式、引用点上都不一样。

**岗位过滤同时下沉到 JD 层**（拿到正文再判断，比只看标题准得多）：

- `jd_requires_english()`：JD 里出现**强英语要求**（英文也可作为工作语言 / 英语流利 / 四六级 / 海外留学优先）→ 跳过，记 `skip-jd-english`
- `jd_not_fit()`：JD 命中 **≥2 个**基建特征词（智算中心 / AICC / IDC / 机房 / 基建 / 机电 / 总包 / 监理 / 电力 / 制冷 …）→ 判为「标题包装成 AI 岗」的无效岗位，跳过，记 `skip-jd-notfit`
  （阈值取 2 是为了不误伤只在 JD 里提一句「服务智算中心行业」的产品岗）

> 这两条是**默认开着的示例规则**，不代表每个人都适用。不需要时在 `profile.json` 里
> 清空对应的词表即可。想加自己的规则，直接往 `profile.exclude` 里续正则。

### Step 1.6：防重复投递（四道防线，已内置）

1. **单实例锁**（`acquire_run_lock()`）：启动时抢 `~/.boss-apply/run.lock`；若已有存活进程在跑则**拒绝启动**（`exit(5)`），并用 `atexit` 保证任何退出路径都释放锁。陈旧锁（进程已死）自动清理。
   > 这是最关键的一道：并发运行＝重复打招呼的直接原因。确需并行（不推荐）用 `--force` 覆盖。
2. **状态用「岗位 id」判定**：`job_id(href)` 从 `/job_detail/<id>.html` 提 id，同一岗位即使 href 带参数/换域名也只算一个；启动时 `migrate_state()` 会把历史 href 形式自动规范化（**先备份**）。
3. **逐条实时核对**：每次发送前、每周期开始前都**重新读盘上的已触达集合**，命中即 `skip 已触达(实时核对)`。
4. **原子写盘**：状态/日志用 `save_json_atomic()`（写临时文件再 rename），避免并发写坏文件。

### Step 1'（备用）：离线收集大池

```bash
python3 scripts/collect_jobs.py \
  --keywords "AI产品经理" "AI解决方案" \
  --cities 101010100 101020100 101280100 \
  --rounds 6
```

- `--cities` 支持多城市（也可直接传中文城市名），脚本按「城市 × 关键词」遍历
- 支持增量累加（重复跑不会丢已有数据）
- ⚠️ 该脚本**跑完才落盘**，中断会丢失；长任务请用后台运行

### Step 2：筛选并预览（先预览，再发送）

```bash
python3 scripts/run_pipeline.py --dry-run     # 只跑选人逻辑，不发送
```

或 `python3 scripts/send_greetings.py --dry-run`。按 `exclude` / `must_any` / `must_role` / `exclude_text_markers` / `salary_filter` 过滤，并按 `priority` 排序。**把预览结果给用户过一眼**，确认无误再发送。

### Step 3：批量发送

```bash
python3 scripts/send_greetings.py
```

- 默认**不设额度**（`--target` 可选，`0`＝不限）：投到没有可投岗位、或平台提示当日上限为止
- 已触达的岗位自动跳过 → 断点续跑
- 每个岗位：详情页 → 立即沟通（系统自动发默认招呼语）→ 继续沟通 → 填定制话术 → 发送 → 校验
- 岗位间随机延迟 3-6 秒
- ⚠️ 连续大批量发送风控风险高，优先用 Step 1 的流水线模式

### Step 4：核验与交付

- 读 `~/.boss-apply/send-log.json` 统计成功率与 `verified` 比例
- 打开 `https://www.zhipin.com/web/geek/chat` 截图确认会话已生成
- 向用户汇报：累计触达数、岗位构成、失败与跳过情况、今日额度用量

---

## 筛选规则详解

**城市范围**（`cities`）：在 `~/.boss-apply/profile.json` 的 `cities` 数组里配，收集时也可用 `--cities` 传入对应编码。

**薪资过滤**（两层）：

1. **搜索档位**（`salary_tiers`）：搜索阶段在页面「薪资待遇」菜单层面先筛一档、再筛下一档，实现方式为搜索 URL 加 `salary=` 参数（407=50K以上，406=20-50K，405=10-20K；与菜单选项一一对应）。档位顺序即投递优先级。
   **档位只用来「在页面捞更宽的池子」，不是投放标准**。
2. **投放判定**（`salary_filter`）：候选筛选时按卡片薪资（字体混淆自动解码）过滤，**这是唯一的投放标准**。

```json
"salary_filter": { "min_k": 40, "mode": "upper", "strict": true }
```

- `mode=upper` + `strict=true`：看薪资区间**上限**且**不含等号** → 上限必须 **>40K**。
  故 `20-40K` / `30-40K` **一律排除**；`25-45K` / `40-50K` / `50-80K` / `30-60K` 通过。
- ⚠️ **历史教训**：曾把这里改成 `mode=lower, min_k=20`（看下限），结果 `20-40K` 这类岗位因下限 20K 全部放行，一天内误投了 7 条上限 ≤40K 的岗位。
  **档位搜索与投放判定是两件事，绝不能用「下限」替代「上限」口径。**
- 薪资解析不到（多为「面议」）的岗位会被跳过，因为无法确认达标
- 解码映射已验证与详情页明文 100% 一致（如 `\ue032\ue032-\ue032\ue033K` = `11-12K`）

用户改薪资要求时：改搜索面改 `salary_tiers`；改投放标准改 `min_k`/`mode`/`strict`。
**改完务必先 `--dry-run` 核对候选与薪资区间**（收紧口径后要有「候选整批消失」的预期）。

**排除规则**（`exclude` 标题正则 + `exclude_text_markers` 卡片全文标记）：

模板里预置的是**通用噪音岗**（实习/校招/销售/客服/人事/财务/法务/培训/讲师 …）。
常见可选追加：

- **技术负责人方向**：`技术专家|算法|架构师|技术负责人|cto|技术总监`
- **英语要求高的岗位**：`英语|英文|口语|外语`

> 这两条不在默认模板里 —— 是否需要取决于你投什么岗。加进 `profile.exclude` 即可。

---

## 风控应对（重要）

BOSS 的风控提示形如「**频繁过度爬取岗位**」「请稍后再试」「访问受限」「安全验证」。**收集（滚动搜索列表）比打招呼更容易触发**，因为滚动列表正是典型的爬虫特征。

### 命中后怎么处理（脚本已内置熔断）

1. **立即熔断**：`run_pipeline.py` 在收集前、滚动后、发送时三处检测，命中即 `mark_risk()` → 停止一切动作 → `sys.exit(3)`。
2. **绝不重试、绝不刷新**：重试＝继续爬，会把软警告升级成硬封禁。
3. **落盘现场**：风控事件写入 `~/.boss-apply/risk.json`（含时间戳与提示原文）；岗位池/已触达/日志均已在过程中落盘。
4. **启动守卫**：之后 30 分钟内再启动会被 `check_recent_risk()` 拒绝（`--risk-guard-min` 可调），防止脚本/定时任务把号跑废；确认无碍用 `--force` 覆盖。
5. **人工处置**：关掉自动化标签页 → 冷却 ≥30 分钟（明确警告建议数小时~次日）→ 若出现滑块/验证码，**人工完成一次正常浏览**再恢复。
6. **降速恢复**：恢复时用 `--per-cycle 2 --scrolls 2`，并把长休息、周期冷却调大。

### 每日投递阈值弹窗与当日封顶（两种出口）

BOSS 有两级提示，**文案完全不同**，脚本按此分流（`QUOTA_DIALOG` + `handle_quota_dialog()`，三态返回）：

| 平台提示原文 | 判定 | 动作 |
|---|---|---|
| 「今天投递数量达到 N 个了，是否继续投递」（N < 150，**带「继续投递」按钮**） | 未达硬上限 | **自动点「继续投递」**，日志打印 `[quota] …已点「继续投递」` |
| **「您已达到沟通上限 / 您今天已与150位BOSS沟通，休息一下，明天再来吧～」（只有「确定」按钮，无「继续投递」）** | **已达当日硬上限** | **判定当日封顶 → 优雅收尾**，当天不再投递 |
| 无关 | 无封顶文案、也无该按钮 | 返回 `none`，零开销 |

> 实测参考基线：投到 120 时弹的是「可继续」弹窗，点「继续投递」后仍能一路投到 **194**；直到 194 才出现**硬上限弹窗**。也就是说 **150 是弹窗文案里的阈值，不是真实硬上限**；真实硬上限由「您已达到沟通上限」这条提示定义，且当天实际能到多少条并不固定。

**封顶判定（`detect_daily_cap()`）两条线，避免误伤：**

1. **强信号词**：`沟通/投递 + 上限|限额|封顶|用完|用尽`（覆盖「已达到沟通上限」），或「明天再来」等；
2. **数字信号**：`投递/沟通 + 达到|已达|超过 + 数字`，且**数字 ≥ 150**。

> 关键：列表页的「今日投递 90/150」只是进度条（有数字但无「达到」、无上限词），**不会被误判为封顶**。

> ⚠️ **硬上限弹窗是间歇出现的**：实测同一时刻连点 6 个新岗位，只有 2 个弹封顶、另外 4 个能进聊天页。但**即使进了聊天页也可能没有真正发出新消息**（多为早已沟通过的旧会话）。判断当天是否真的投不动，以这两条为准：① 是否出现「您已达到沟通上限」；② 聊天列表最新会话时间是否还停在上一批发送时刻。

### 当日封顶后怎么收尾（这是每日限额，不是风控）

命中封顶时脚本**优雅结束当天任务**，而不是当成失败继续试下一个岗位：

1. 记录 `~/.boss-apply/daily-cap.json`（含日期、时间戳、提示原文、累计触达数）；
2. 流水线打印 `任务结束：当日额度已满` 并以 `sys.exit(0)` **正常退出**（区别于风控的 `exit(3)`）；
3. **启动守卫** `check_daily_cap()`：当天再次启动会被直接拒绝（`exit(4)`），避免无意义空转；确认额度已恢复（或已跨天）用 `--force` 覆盖；
4. 状态文件自动跨天失效——`date` 字段不同即视为新的一天，无需手工清理。

> 与风控的区别：风控是「被盯上了」，需要冷却 + 人工处理；封顶是「今天到点了」，**第二天自然可继续**。

### 预防（比补救更重要）

- 优先用「详情页直接打开」而非「滚动列表」——详情页是正常浏览行为，列表滚动才是爬虫特征
- 减少关键词数量与滚动轮数；同一关键词不要连续反复刷
- 拉长周期冷却与长休息；**不设自定额度**，以平台提示为准，但节奏要拟人、分散
- **不要并发**：始终单会话串行
- 不要在深夜无人值守长时间跑；真人作息反而是最好的伪装

---

## 关键约定

- **一次性授权**：发送消息是对外动作，必须用户明确要求后才执行；批量任务开始前说明会发多少条
- **不设自定额度**：`--target` 默认不传（`0`＝不限）。停止条件只有三个——没有可投岗位 / 平台提示当日上限 / 命中风控。
- **当日封顶即收尾**：出现「**您已达到沟通上限 / 明天再来吧**」时**当天不再投递**，任务正常结束；再启动会被守卫拒绝，次日断点续跑即可（不要用 `--force` 硬顶）
- ⚠️ **不要用「累计触达数」推断是否封顶**：所谓 150 只是弹窗文案里出现过的阈值，**真实封顶一律以页面实际出现的提示原文为准**，否则会误判为「今天投完了」而提前收工。
- ⚠️ **判断封顶必须取证原文，禁止推断**：`mark_daily_cap()` 会把平台提示原文写入 `~/.boss-apply/daily-cap.json`。若记录里只有泛化措辞而**没有原文**，说明可能是推断而非实测——必须回到页面复核。
- **不做垃圾投放**：宁少勿滥，命中排除规则的岗位一律不发
- **不代聊**：用户未明确要求时，只发首条打招呼；HR 回复后的沟通话术需另行确认

### 候选池吃干了怎么办（重要）

跑满 `--max-cycles` 后若「可用候选 0」反复出现，**这不是封顶、也不是风控**，而是可选岗位被挖空了。按顺序排查：

1. **先看跳过池是否卡住了合格岗位**（最常见）：统计「符合条件但全在跳过池里」的岗位，若严格口径候选几乎全在跳过池 → 备份后清空跳过池让其重试：
   ```bash
   cp ~/.boss-apply/skipped.json ~/.boss-apply/skipped.bak-$(date +%Y%m%d-%H%M).json
   echo '[]' > ~/.boss-apply/skipped.json
   ```
   重试是**安全**的：`send_one` 若发现按钮已是「继续沟通」会走 `already` 分支，不会重复打招呼。
2. **加深滚动没用就当关键词不够**：实测 `--scrolls 3 → 12` 只多挖出个位数岗位，说明搜索面已见底 → **扩 `keywords`**（比加深滚动有效得多）。一次加 10+ 个同方向词。
3. **薪资口径收紧后要重新评估池容量**：口径从 `>=40K` 改成 `>40K` 时，池内「上限=40K」的岗位会**整批失效**。收紧口径前先 `--dry-run` 看候选还剩多少。
4. 城市范围由用户决定，**不要自行扩城**——需要时先问用户。
5. 采完仍不足时，把情况如实告诉用户（今天还剩多少额度、预期还能投多少），不要硬刷。

---

## 数据与文件

所有个人数据都在 `~/.boss-apply/`（可用 `BOSS_APPLY_HOME` 覆盖）。**技能包目录内不含任何个人信息。**

| 文件 | 内容 |
|---|---|
| `profile.json` | **你的简历画像与筛选配置**（隐私，勿外传） |
| `pool.json` | 岗位池 |
| `jd.json` | 抓到的 JD 正文 |
| `messages.json` | AI 逐条写的话术 |
| `contacted.json` | 已触达（断点续跑依据） |
| `skipped.json` | 跳过池 |
| `send-log.json` | 发送日志 |
| `src.json` | 岗位来源标记 |
| `daily-cap.json` | 当日封顶记录 |
| `risk.json` | 风控事件 |
| `run.lock` | 单实例锁 |

## 配套文件

| 文件 | 说明 |
|---|---|
| `scripts/doctor.py` | **先跑这个**：环境体检（Python / 扩展 / 配置 / 数据目录） |
| `scripts/setup_wizard.py` | **首次配置引导**：生成 `profile.json`（`--check` / `--from-json` / `--interactive` / `--show`） |
| `scripts/paths.py` | 统一路径与用户配置解析（`BOSS_APPLY_HOME`，含历史 `/tmp` 数据自动迁移） |
| `scripts/fetch_jd.py` | **话术链第 1 步**：按优先级抓候选的 JD 全文（只读、零触达） |
| `scripts/run_pipeline.py` | **推荐主流程**：边收集边投递的流水线 |
| `scripts/send_greetings.py` | 从大池批量发招呼（默认只投有 AI 话术的岗位；含筛选与薪资解码） |
| `scripts/webbridge.py` | 浏览器桥接调用封装（环境检查、navigate/evaluate/fill/screenshot） |
| `scripts/collect_jobs.py` | 离线收集大池（跑完才落盘，长任务慎用） |
| `references/zhipin-dom-and-flow.md` | **页面结构、选择器、5 步流程、话术文件格式、坑位清单**（改选择器前必读） |
| `assets/profile-template.json` | 空白骨架（无个人信息）；仅作 `setup_wizard.py` 的底稿 |

## 故障处理

| 症状 | 处理 |
|---|---|
| 选择器失效 / 点不到按钮 | 读 `references/zhipin-dom-and-flow.md` 第 3 节，用 `snapshot` 或 `evaluate` 重新定位 |
| 薪资读不到数字 | 列表页为字体混淆，脚本已内置解码；如需人工核对，打开详情页取明文薪资 |
| 「继续沟通」不出现 | 记下岗位，跳过；下一轮重跑通常恢复正常 |
| 提示「频繁过度爬取岗位」 | 脚本已熔断并写 `risk.json`；停止 30 分钟以上，勿刷新勿重试，恢复时降速 |
| 页面出现安全验证 | 立即停止，让用户人工完成验证，再重跑（自动断点续跑）；勿用脚本处理验证 |
| 扩展未连接 | 交给用户确认浏览器侧连接，不要动守护进程 |
| 提示「尚未完成配置」 | 跑 `python3 scripts/setup_wizard.py`，见 Step -1 |
