# MvxyUptime API v2 🟢
> Advanced serverless uptime monitor — Python + MongoDB + Vercel  
> By [@Venuboyy](https://t.me/Venuboyy)

---

## ✨ What's New in v2

| Feature | Details |
|---|---|
| ⏱️ **Custom Intervals** | 10s, 30s, 1m, 2m, 5m, 10m, 30m, 1h |
| 📣 **4 Notification Channels** | Telegram, Discord, Slack, Email |
| 🧯 **Incident Management** | Auto open/close/track/resolve |
| 🟡 **Degraded State** | Response time threshold triggers yellow alert |
| 📊 **Multi-window Uptime** | 1h / 24h / 7d / 30d stats |
| 📈 **Latency Stats** | avg / min / max over 24h |
| 🔕 **Alert Cooldown** | Anti-spam per-monitor cooldown |
| 🌐 **Public Status Page** | `/api/status` — no auth needed |
| 🏷️ **Tags / Groups** | Label monitors, filter by tag |
| 🧪 **Test Notification** | Fire a test alert to all channels |
| 📜 **Notification Log** | Full history of every alert sent |
| ✏️ **PATCH Update** | Change interval/channels live without recreating |
| 🔒 **SSL detection** | Flags https-based monitors |

---

## 🚀 Deploy

### 1. Clone & install Vercel CLI
```bash
git clone <your-repo> && cd uptime-api
npm i -g vercel
```

### 2. Set Environment Variables in Vercel Dashboard
| Variable | Required | Purpose |
|---|---|---|
| `MONGO_URI` | ✅ | MongoDB Atlas connection string |
| `API_SECRET` | ✅ | Your secret key for all API calls |
| `TG_BOT_TOKEN` | Optional | Telegram bot token (global default) |
| `TG_CHAT_ID` | Optional | Telegram chat/channel ID (global default) |
| `SMTP_HOST` | Optional | Gmail / any SMTP host |
| `SMTP_PORT` | Optional | Default 587 |
| `SMTP_USER` | Optional | SMTP username |
| `SMTP_PASS` | Optional | SMTP password / app password |

### 3. Deploy
```bash
vercel --prod
```

---

## ⏱️ Supported Check Intervals

| Label | Seconds |
|---|---|
| 10s | 10 |
| 30s | 30 |
| 1m | 60 |
| 2m | 120 |
| 5m | 300 |
| 10m | 600 |
| 30m | 1800 |
| 1h | 3600 |

> Any other value is snapped to the closest valid interval automatically.

---

## 🔁 Cron Setup (Interval-Aware)

The `/api/ping-all` endpoint is **interval-aware** — it skips monitors that aren't due yet.  
Run it every **10 seconds** via [cron-job.org](https://cron-job.org) (free):

```
URL:     https://your-app.vercel.app/api/ping-all
Method:  POST
Header:  X-API-Key: your-secret
Every:   10 seconds (or minimum allowed by your cron provider)
```

This way a monitor set to 10s gets checked every 10s, while a 1h monitor waits its full hour.

---

## 📡 API Reference

All protected endpoints require:
```
X-API-Key: your-secret
```

---

### `GET /api/health`
Public. Returns service info and available intervals.

---

### `POST /api/monitors` — Add monitor
```json
{
  "url": "https://mvxycloud.koyeb.app",
  "name": "MvxyCloud",
  "interval_seconds": 30,
  "timeout_seconds": 10,
  "tags": ["bots", "koyeb"],
  "degraded_threshold_ms": 2000,
  "alert_cooldown_seconds": 300,
  "notifications": {
    "telegram": {
      "bot_token": "optional-override",
      "chat_id": "optional-override"
    },
    "discord_webhook": "https://discord.com/api/webhooks/...",
    "slack_webhook": "https://hooks.slack.com/services/...",
    "email": "you@example.com"
  }
}
```

- `interval_seconds` — how often to check (snapped to valid value)
- `degraded_threshold_ms` — if response time exceeds this, state = `degraded` (yellow alert)
- `alert_cooldown_seconds` — minimum gap between repeat alerts (default 5min)
- `notifications` — all channels are optional; leave out what you don't need

---

### `GET /api/monitors` — List all
Optional query: `?tag=koyeb`

---

### `GET /api/monitors/{id}` — Get one

---

### `PATCH /api/monitors/{id}` — Update live
```json
{
  "interval_seconds": 10,
  "notifications": { "discord_webhook": "https://..." }
}
```

---

### `DELETE /api/monitors/{id}` — Delete + wipe history

---

### `POST /api/monitors/{id}/pause`
```json
{ "paused": true }
```

---

### `POST /api/monitors/{id}/check` — Manual check now

---

### `GET /api/monitors/{id}/history`
```
?limit=100&state=down
```
Returns checks + uptime % for all windows.

---

### `GET /api/monitors/{id}/stats`
Returns full stats: uptime windows, latency, incident summary.

---

### `POST /api/monitors/{id}/test-notify`
Fires a fake "down" alert to all configured channels for this monitor. Great for testing webhooks.

---

### `GET /api/incidents`
```
?monitor_id=abc123&resolved=false
```

---

### `GET /api/incidents/{id}` — Get one incident

---

### `POST /api/incidents/{id}/resolve` — Manually resolve
```json
{ "note": "Fixed by restarting the service" }
```

---

### `GET /api/notifications`
```
?monitor_id=abc123
```
Returns full log of every alert ever sent.

---

### `POST /api/ping-all` — Cron trigger (interval-aware)

---

### `GET /api/status` — Public status page
No auth. Returns sanitized monitor list + overall health. Use for a public status page.

---

### `GET /api/stats` — Global dashboard stats

---

## 🗄️ MongoDB Collections

| Collection | Purpose |
|---|---|
| `monitors` | One doc per URL, stores all settings + latest state |
| `checks` | Every check result (capped at 5000/monitor) |
| `incidents` | Auto-created on down/degraded, auto-resolved on recovery |
| `notifications` | Every alert fired, with channel delivery status |

---

## 📲 Notification Message Example

```
🔴 MvxyUptime — DOWN

Monitor : MvxyCloud
URL     : https://mvxycloud.koyeb.app
Latency : 0ms
Error   : Connection refused
Time    : 2025-01-15 14:32:01 UTC
Incident: #a1b2c3d4
Interval: every 30s
```

Recovery:
```
✅ MvxyUptime — UP

Monitor : MvxyCloud
URL     : https://mvxycloud.koyeb.app
Latency : 184ms
Code    : HTTP 200
Time    : 2025-01-15 14:38:44 UTC
Incident: #a1b2c3d4
Interval: every 30s
```
