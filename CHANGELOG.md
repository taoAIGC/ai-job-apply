# Changelog

## 2.0.0 (2026-10-17)

首次开源发布。

- 采集：搜索页滚动收池（多城市×关键词）、频道标签双线刷池
- 筛选：画像驱动（关键词/排除词/薪资口径/公司黑名单/英语过滤）
- 话术：AI 逐条读 JD 现场撰写（messages.json），无话术不发送
- 发送：拟人化节奏、三态额度弹窗处理、风控熔断、回执核验
- 运维：run_forever 守护 + daemonize 后台化 + doctor 环境体检
- 测试：核心解析/过滤/风控词表单测；GitHub Actions CI
- 桥接：webbridge 地址与二进制支持环境变量覆盖（BOSS_BRIDGE_ADDR/BOSS_BRIDGE_BIN）
