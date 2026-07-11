# Monitoring va alerting (P12-T2)

Uch qatlam: **pull** (uptime-provider healthz'ni tekshiradi), **push**
(dead-man heartbeat — stack o'zi ping yuboradi), **ichki alert** (beat task
biznes-holatlarni tekshirib Telegram'ga yozadi). Xato-kuzatuv Sentry'da (P12-T1).

## 1. Uptime (pull) — tashqi provider

UptimeRobot / BetterStack / Pingdom'da HTTP monitor oching:

| Monitor | URL | Kutiladi |
|---|---|---|
| Liveness | `https://drama.uz/healthz` | 200, `{"status": "ok"}` |
| Readiness | `https://drama.uz/readyz` | 200 (DB/Redis/migratsiya OK); 503 = alert |

Tavsiya: interval 1–5 daqiqa, alert kanali Telegram/email.

## 2. Dead-man heartbeat (push)

Pull-monitor faqat web'ni ko'radi. Beat/worker o'lsa sayt ochilaveradi, lekin
fon ishlar (publish, bildirishnoma, topup tozalash) jimgina to'xtaydi. Buning
uchun: [healthchecks.io](https://healthchecks.io) da check oching (period 5 min,
grace 5 min) va ping-URL'ni `.env` dagi `HEARTBEAT_URL` ga qo'ying.
`core.tasks.heartbeat_task` har 5 daqiqada ping yuboradi — kelmay qolsa
provider alert beradi. Bu bilan beat + worker + redis + tarmoq birga kuzatiladi.

## 3. Ichki alertlar (Telegram)

`core.tasks.monitoring_alerts_task` (har 10 daqiqa) `core/monitoring.py ::
collect_problems()` shartlarini tekshiradi:

| Kalit | Shart | Standart chegara |
|---|---|---|
| `queue` | Celery navbati backlog | `MONITORING_QUEUE_ALERT_THRESHOLD` (100) |
| `stale_topup` | pending topup 24+ soat | 1 ta ham bo'lsa |
| `stale_report` | pending izoh-shikoyat 48+ soat | 1 ta ham bo'lsa |
| `cache` | Redis kesh javob bermayapti | — |

Har kalit uchun **1 soat cooldown** (kesh) — shovqin yo'q. Xabarlar admin
Telegram kanaliga (`TELEGRAM_BOT_TOKEN` / `TELEGRAM_ADMIN_CHAT_ID`, P3-T3) boradi.

## 4. /metrics (Prometheus)

`GET /metrics` — text-format biznes-gauge'lar (foydalanuvchi/kino/pending
topup/shikoyat/navbat uzunligi/db/kesh holati). Himoya: `METRICS_TOKEN`.

Prometheus scrape misoli:

```yaml
scrape_configs:
  - job_name: drama
    metrics_path: /metrics
    scheme: https
    authorization:
      credentials: <METRICS_TOKEN qiymati>
    static_configs:
      - targets: ["drama.uz"]
```

Dizayn eslatmasi: per-request counter'lar ATAYIN yo'q — gunicorn ko'p-worker
rejimida har worker o'z xotirasida alohida sanaydi (jami noto'g'ri);
request-rate'ni nginx/Cloudflare log'lari beradi. django-prometheus
(multiproc-dir) keyin kerak bo'lsa — ADR bilan.

## 5. Sentry alert qoidalari (bir martalik, dashboard)

Sentry -> Alerts -> New Alert: "error count > 10 / 5min" -> Telegram/email
kanal. Release-tracking allaqachon sozlangan (docs/ops/sentry.md).
