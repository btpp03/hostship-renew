#!/usr/bin/env python3
"""
host-ship.com 免费服务器自动续期（Jexactyl 面板 client API，纯 HTTP，零依赖、不过盾）

机制（从面板前端 bundle 里读出来的）:
  POST /api/client/servers/{uuid}/renew      -> 204，无 body
  每次续期 = 加 max(0, min(10, 30 - 当前天数)) 天，总量封顶 30 天；两次续期之间冷却 60 秒。
  所以「一次性顶到 30 天」= 连点 3 轮（每轮等 65s）。

行为:
  - 剩余天数 > HS_MIN_DAYS  -> 静默跳过（只打印，不发 TG）
  - 否则连续到 30 天（最多 HS_MAX_ROUNDS 轮）
  - 成功发 1 条精简 TG；出错发告警并以 exit 1 结束（Actions 变红）
环境变量: HS_API_KEY HS_UUID [HS_BASE] [HS_MIN_DAYS] [HS_TOPUP_DAYS] [HS_MAX_ROUNDS]
          [TG_BOT_TOKEN] [TG_CHAT_ID] [TG_THREAD_ID]
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

BASE = os.environ.get("HS_BASE", "https://panel.host-ship.com").rstrip("/")
KEY = os.environ.get("HS_API_KEY", "")
UUID = os.environ.get("HS_UUID", "")
MIN_DAYS = int(os.environ.get("HS_MIN_DAYS", "10"))
TOPUP_DAYS = int(os.environ.get("HS_TOPUP_DAYS", "30"))
MAX_ROUNDS = int(os.environ.get("HS_MAX_ROUNDS", "3"))
COOLDOWN = int(os.environ.get("HS_COOLDOWN", "65"))
REPO = os.environ.get("GITHUB_REPOSITORY", "btpp03/hostship-renew")
TG_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT = os.environ.get("TG_CHAT_ID", "")
TG_THREAD = os.environ.get("TG_THREAD_ID", "")


def log(*a):
    print(*a, flush=True)


def api(method, path, data=None):
    url = BASE + path
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Authorization", "Bearer " + KEY)
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=45) as r:
            return r.status, r.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "ignore")
    except Exception as e:  # 网络层
        return 0, "NET-ERR %s" % e


def info():
    s, t = api("GET", "/api/client/servers/%s" % UUID)
    if s != 200:
        raise RuntimeError("GET server failed: HTTP %s %s" % (s, t[:300]))
    a = json.loads(t)["attributes"]
    return {
        "days": a.get("renewal"),
        "renewable": a.get("renewable"),
        "locked": bool(a.get("renewal_locked")),
        "cooldown": a.get("renewal_cooldown") or 0,
        "suspended": bool(a.get("is_suspended")),
        "installing": bool(a.get("is_installing")),
        "name": a.get("name"),
        "name_id": a.get("identifier"),
        "delete_at": ((a.get("billing") or {}).get("delete_at")),
    }


def renew_once():
    return api("POST", "/api/client/servers/%s/renew" % UUID)


def tg(text):
    if not TG_TOKEN or not TG_CHAT:
        log("[tg] 未配置 TG_BOT_TOKEN/TG_CHAT_ID，跳过通知")
        return
    import urllib.parse
    for extra in ([{"message_thread_id": TG_THREAD}] if TG_THREAD else []) + [{}]:
        data = {"chat_id": TG_CHAT, "text": text, "disable_web_page_preview": "true"}
        data.update(extra)
        try:
            req = urllib.request.Request(
                "https://api.telegram.org/bot%s/sendMessage" % TG_TOKEN,
                data=urllib.parse.urlencode(data).encode())
            with urllib.request.urlopen(req, timeout=20) as r:
                j = json.loads(r.read().decode())
            if j.get("ok"):
                log("[tg] sent (thread=%s)" % extra.get("message_thread_id"))
                return
            log("[tg] api error: %s" % j)
        except Exception as e:
            log("[tg] send failed: %s" % e)
    log("[tg] 全部尝试失败")


def main():
    if not KEY or not UUID:
        log("!! 缺少 HS_API_KEY / HS_UUID")
        return 2
    st = info()
    log("server   : %s #%s" % (st["name"], st["name_id"]))
    log("状态     : 剩余 %s 天 | renewable=%s locked=%s cooldown=%ss suspended=%s"
        % (st["days"], st["renewable"], st["locked"], st["cooldown"], st["suspended"]))

    if st["suspended"]:
        tg("❌ host-ship 服务器已被停用（%s #%s），需要手动登录面板处理\n%s" % (st["name"], st["name_id"], BASE))
        return 1
    if st["locked"]:
        tg("⚠️ host-ship 服务器是固定到期日（不可自助续期）：%s\n%s" % (st["delete_at"], BASE))
        return 1
    if not st["renewable"]:
        log("non-renewable（付费计划？）→ 跳过")
        return 0
    if st["days"] is None:
        log("!! 面板没返回 renewal 字段，放弃")
        return 1
    if st["days"] > MIN_DAYS:
        log("剩余 %s 天 > %s 天 → 静默跳过" % (st["days"], MIN_DAYS))
        return 0

    before = st["days"]
    cur = before
    rounds = 0
    for i in range(MAX_ROUNDS):
        if cur >= TOPUP_DAYS or cur >= 30:
            break
        s, t = renew_once()
        log("第 %d 轮 POST /renew -> HTTP %s %s" % (i + 1, s, t[:200]))
        if s not in (200, 204):
            if s == 0:
                log("网络错误，稍后重试")
                time.sleep(20)
                continue
            tg("❌ host-ship 续期失败：HTTP %s %s\n%s" % (s, t[:200], BASE))
            return 1
        rounds += 1
        time.sleep(COOLDOWN)          # 面板冷却 60s
        try:
            cur = info()["days"]
        except Exception as e:
            log("读状态失败：%s" % e)
        log("   → 现在剩余 %s 天" % cur)

    gained = (cur - before) if isinstance(cur, int) and isinstance(before, int) else None
    if rounds and gained and gained > 0:
        tg("✅ host-ship 续期成功：%s 天 → %s 天（%s 轮）\n📦 %s/%s" % (before, cur, rounds, "https://github.com", REPO))
        log("OK 续期成功 %s -> %s" % (before, cur))
        return 0
    tg("⚠️ host-ship 续期没生效：续了 %s 轮，天数 %s -> %s\n%s/server/%s" % (rounds, before, cur, BASE, st["name_id"]))
    log("!! 续期未生效")
    return 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        log("FATAL %s" % e)
        tg("❌ host-ship 续期脚本异常：%s" % e)
        sys.exit(1)
