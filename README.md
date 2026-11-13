# host-ship 自动续期

[host-ship.com](https://panel.host-ship.com) 免费服务器（Jexactyl 面板）的自动续期。
**纯 HTTP 调面板 client API，不用浏览器、不过 Cloudflare 盾、零第三方依赖。**

## 续期机制（面板前端 bundle + 面板 400 文案实测）

- `POST /api/client/servers/{uuid}/renew` → `204`，无 body，认证 `Authorization: Bearer <client API key>`
- 一次续期直接顶到面板的**续期封顶**；两次续期之间**冷却 60 秒**
- **封顶天数由平台定、会变**：2026-10 实测为 30 天，2026-11 实测为 **14 天**
- 已到封顶再点 → `400 {"detail":"You cannot add more than N days of renewal time."}` —— 这是**正常状态，不是故障**
- 服务器**被停用后不续会被永久删除**

> 2026-11 平台把封顶从 30 天改成 14 天，旧脚本写死「封顶 30 天」且只认 `"more than 30 days"` 文案，
> 导致续满后第 2 轮撞 400 被当成失败、发了误报告警。现已改为 **按语义识别 `cannot add more than ... days`**，
> 不写死天数，平台以后再改也不会误报。

## 脚本行为

| 情况 | 动作 |
|---|---|
| 剩余 > `HS_MIN_DAYS`（默认 10） | 静默跳过，不打 TG |
| 剩余 ≤ 10 | 续期到封顶（最多 `HS_MAX_ROUNDS`，默认 2 轮） |
| 成功（天数真的涨了） | 打 1 条 TG：`before → after`、轮数、仓库地址 |
| 已到封顶 / 本来就达标 | **静默结束**，不告警（旧版会误报） |
| 真失败 / 被停用 / 固定到期日 | 打 TG 告警 + `exit 1`（Actions 变红） |

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
| `TG_THREAD_ID` | （可选）话题线程 id；DM 无话题时留空即可 |

环境变量（workflow 里已设，本地可调）：`HS_MIN_DAYS=10`（守门阈值）、`HS_TOPUP_DAYS=14`（目标天数）、`HS_MAX_ROUNDS=2`、`HS_COOLDOWN=65`。

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

只验证「能打到 /renew、不改天数」：`HS_SMOKE=1 python3 renew.py`
只验证通知链路、不碰面板：`HS_NOTIFY_TEST=1 python3 renew.py`
