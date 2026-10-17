# 使用教程：初始化配置与全部可配置项

> 本教程对应 v2.0.0。所有配置最终都落在本机 `~/.boss-apply/profile.json`，
> 仓库里不带任何个人数据。

## 1. 初始化：三种方式

### 方式 A：交互式引导（推荐新手）

```bash
python3 scripts/setup_wizard.py --interactive
```

按提示逐项回答 5 组问题：称呼 → 城市 → 关键词 → 薪资底线 → 个人经历。
直接回车用默认值；Ctrl+C 中断不会写入半份配置。

### 方式 B：AI 引导模式（推荐配合 AI 助手使用）

先让 AI 在对话里问清你的情况，然后把答案写成 draft JSON 一次性落盘：

```bash
python3 scripts/setup_wizard.py --from-json /tmp/my-profile-draft.json
```

draft 结构（除 resume 外均可省略）：

```json
{
  "owner": "张先生",
  "cities": ["北京", "上海"],
  "keywords": ["AI产品经理", "大模型产品经理"],
  "salary_min_k": 30,
  "channels": ["AI产品经理(北京)"],
  "resume": {
    "summary": "一句话自我介绍",
    "current": "最近一段经历（公司·职位·时间）",
    "highlights": ["亮点1（带量化指标最好）", "亮点2", "亮点3"]
  },
  "exclude_extra": "教育|医疗",
  "note": "任何要告诉 AI 的补充说明"
}
```

覆盖已有配置时会自动备份为 `profile.json.bak-<时间戳>`。

### 方式 C：辅助命令

```bash
python3 scripts/setup_wizard.py --check   # 检查配置是否就绪（输出 JSON，缺什么列什么）
python3 scripts/setup_wizard.py --show    # 查看当前生效的配置（脱敏）
python3 scripts/doctor.py                 # 环境体检：桥接/扩展/登录态/配置一站式诊断
```

## 2. 可以配置什么（profile.json 全字段）

### 基础项（引导必填）

| 字段 | 说明 |
|---|---|
| `owner` | 称呼，仅用于日志显示 |
| `cities` | 目标城市数组 `[{"code":"101010100","name":"北京"}]`。支持中文名自动转码（内置 22 个城市代码）；其他城市请填 BOSS 搜索页 URL 里的城市代码。**城市代码错会搜出别的城市** |
| `city` / `city_name` | 主城市（cities 第一个），由引导自动生成 |
| `keywords` | 搜索关键词，至少 3 个。池子挖干了优先扩这里，比加深滚动有效得多 |
| `salary_filter` | **唯一的投放薪资标准**：`min_k`（底线）、`mode`（`upper`=看区间上限 / `lower`=看起薪）、`strict`（true=不含等号）。例：`min_k=40 + upper + strict` ⇒ 只投「上限 >40K」，20-40K/30-40K 被排除，25-45K 通过 |
| `resume_points` | `{summary, current, highlights[]}`，AI 写话术的唯一素材来源，**务必真实、量化指标优先**，不得编造 |

### 检索扩展项（可选）

| 字段 | 说明 |
|---|---|
| `channels` | BOSS 页面顶部「求职意向」频道标签，形如 `"AI产品经理(北京)"`。取决于**你账号的求职意向设置**，引导时留空则只刷「推荐」标签 |
| `use_recommend_tab` | 是否刷「推荐」标签（默认 true） |
| `channels_rounds` | 每个频道标签的滚动轮数（默认 6） |
| `salary_tiers` | 搜索时按档位捞池的顺序，`code` 是搜索 URL 的 salary 参数（407=50K以上、406=20-50K、405=10-20K）。**档位只决定搜多宽的池子，不是投放标准** |
| `exclude` | 标题命中即排除的正则（骨架已内置教育/医疗/销售/技术负责人等通用噪音词），可用 `exclude_extra` 追加 |
| `must_any` | 标题必须命中其一（正则），空=不限。如 `"ai\|人工智能\|大模型\|agent"` |
| `must_role` | 标题必须命中的角色词（正则），空=不限。如 `"产品\|运营\|解决方案"` |
| `priority` | 排序加权词，命中的岗位优先投。如 `"专家\|资深\|高级\|总监"` |
| `exclude_text_markers` | 卡片全文命中即排除（兜住标题看不出来的信息），默认 `["元/天","天/周","在校"]` 排除日薪实习/在校岗 |

### 黑名单与话术规范（可选但推荐）

| 字段 | 说明 |
|---|---|
| `exclude_companies` | **公司黑名单**：公司名包含任一关键词即永久不投，选人与发送端双重拦截。支持集团级关键词（如 `["字节","抖音","阿里","腾讯","蚂蚁"]` 一并排掉子公司），避免反复骚扰同一家公司 |
| `ai_message_rules` | AI 逐条读 JD 写话术的写作规范（长度/must/must_not/tone），脚本不执行本段，是给 AI 的约束。核心：**必须引用该岗位 JD 的具体内容、素材只能来自 resume_points、结尾统一「期待和您聊聊。」、同批话术结构不重复** |

### 环境变量（不改代码覆盖桥接）

| 变量 | 说明 |
|---|---|
| `BOSS_BRIDGE_ADDR` | 桥接守护地址（默认 `127.0.0.1:10086`） |
| `BOSS_BRIDGE_BIN` | 桥接二进制路径（默认 `~/.kimi-webbridge/bin/kimi-webbridge`） |
| `BOSS_MODE` / `BOSS_CITIES` / `BOSS_KWS` / `BOSS_ROUNDS` / `BOSS_CH_ROUNDS` / `BOSS_CH_PASSES` | `refresh_pool.py` 的参数环境变量版 |
| `BOSS_WATCH_SLEEP` / `BOSS_WATCH_MAX_IDLE_MIN` | `run_forever.py` 待命轮询间隔（默认 60s）/ 待命上限分钟（默认 360，0=无限） |

## 3. 本机数据文件（`~/.boss-apply/`，不进仓库）

| 文件 | 内容 |
|---|---|
| `profile.json` | 你的画像配置（含真实简历要点，**不要提交到任何公开仓库**） |
| `pool.json` / `src.json` | 岗位池 / 每个岗位的来源标记 |
| `jd.json` | 抓取到的岗位 JD |
| `messages.json` | AI 逐条撰写的话术库 `{"msgs": {"<job_id>": {"text": "…"}}}` |
| `contacted.json` | 已触达岗位 id（断点续跑依据） |
| `send-log.json` | 每条投递的完整流水（含核验结果） |
| `skipped.json` | 跳过池（英语岗/错配岗，不再重复访问） |
| `daily-cap.json` | 当日封顶判定（跨天自动失效） |
| `logs/` | 守护与发送日志 |

## 4. 典型工作流

```bash
# 首次
python3 scripts/setup_wizard.py --interactive
python3 scripts/doctor.py

# 日常循环（AI 配合时）
python3 scripts/refresh_pool.py                 # ① 双线刷池
python3 scripts/fetch_jd.py --limit 20          # ② 抓候选 JD
#   ③ AI 读 jd.json，按 ai_message_rules 逐条写话术 → messages.json
python3 scripts/run_pipeline.py                 # ④ 流水线：边收边投（推荐）
# 或
python3 scripts/daemonize.py python3 scripts/run_forever.py   # ④' 后台守护持续投
```

先 `--dry-run` 预览会投给谁，再实投。
