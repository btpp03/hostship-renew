# host-ship 自动续期

[host-ship.com](https://panel.host-ship.com) 免费服务器（Jexactyl 面板）的自动续期。
**纯 HTTP 调面板 client API，不用浏览器、不过 Cloudflare 盾、零第三方依赖。**

## 续期机制（从面板前端 bundle 里逆出来的）

- `POST /api/client/servers/{uuid}/renew` → `204`，无 body，认证 `Authorization: Bearer <client API key>`
- 每次续期 = 加 `max(0, min(10, 30 - 当前剩余天数))` 天，**总量封顶 30 天**
- 两次续期之间**冷却 60 秒**
- 剩余 ≥ 30 天时前端显示 "Renew Limit Reached"（不用管，本来就满）
- 服务器**被停用后不续会被永久删除**

所以「顶满」= 连点 3 轮（每轮等 65s）：`6 天 → 16 → 26 → 30`。

## 脚本行为

| 情况 | 动作 |
|---|---|
| 剩余 > `HS_MIN_DAYS`（默认 10） | 静默跳过，不打 TG |
| 剩余 ≤ 10 | 连续续期到 30 天（最多 3 轮） |
| 成功 | 打 1 条 TG：`before → after`、轮数、仓库地址 |
| 失败 / 被停用 / 固定到期日 | 打 TG 告警 + `exit 1`（Actions 变红） |

## 部署 / 配置

1. 面板 → Account → API → 建一枚 client API key（`ptlc_...`，只显示一次）
2. 仓库 Secrets（Settings → Secrets and variables → Actions）：

| Secret | 说明 |
|---|---|
| `HS_API_KEY` | 面板 client API key（`ptlc_...`） |
| `HS_UUID` | 服务器 UUID（面板 URL `/server/<short>` → 详情里取完整 UUID） |
| `HS_BASE` | `https://panel.host-ship.com` |
| `TG_BOT_TOKEN` | Telegram bot token |
| `TG_CHAT_ID` | 通知目标 chat id |
| `TG_THREAD_ID` | （可选）话题线程 id，DM 话题里必须带，否则你看不到消息 |

3. 手动试跑：`Actions → 自动续期 → Run workflow`
4. **定时靠 cron-job.org 外部触发**（GitHub 原生 schedule 经常丢 tick）：
   - URL: `https://api.github.com/repos/<owner>/<repo>/actions/workflows/renew.yml/dispatches`
   - Method: `POST`，Header `Authorization: Bearer <fine-grained PAT，actions:write>` + `Content-Type: application/json`
   - Body: `{"ref":"main"}` → `204` 即触发成功
   - 频率：每天 06:45 / 18:45 UTC（脚本自己守门，多余的点会静默跳过）

## 本地自测

```bash
HS_API_KEY=ptlc_xxx HS_UUID=xxxx-... python3 renew.py
```
（不带 TG_* 时只在 stdout 打印，不发通知）
