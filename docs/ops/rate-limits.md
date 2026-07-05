# Rate limiting (ops eslatma) [P10-T2]

Ikki qatlam, ikkalasi ham default cache'ga yozadi (dev/prod = **Redis**):

## 1. Web/HTML view'lar — django-ratelimit

Tezliklar BITTA joyda: `config/settings/base.py` → `RATELIMIT_RATES`.
Kalitlar Cloudflare-aware (`core/http.py client_ip`: CF-Connecting-IP →
X-Forwarded-For → REMOTE_ADDR) — aks holda CF edge-IP hammani bitta
chelakka solardi. Limit oshsa: **429** + `Retry-After: 60` + JSON `detail`
(`RatelimitTo429Middleware` — default 403 o'rniga).

| Group | Tezlik | Endpoint | Kalit |
|-------|--------|----------|-------|
| login | 10/m | users:login (POST) | IP |
| register | 5/h | users:register (POST) | IP |
| review | 10/h | drama AddReview (POST) | user/IP |
| gift | 20/h | send_gift_to_actor | user/IP |
| premium | 10/h | buy_premium | user/IP |
| topup | 10/h | topup + kripto (BITTA chelak) | user/IP |
| funding | 20/h | process_funding | user/IP |
| live_search | 30/m | live-search (GET) | IP |
| watch_progress | 30/m | pleyer progress POST (~6/min normal) | user/IP |

## 2. REST API — DRF throttle

`REST_FRAMEWORK["DEFAULT_THROTTLE_RATES"]`: anon 100/soat, user 1000/soat,
review 10/soat, search 30/daqiqa, playback 60/daqiqa (ADR 0002 jadvali).

## O'zgartirish

Faqat settings'dagi dict/rates — view kodiga tegilmaydi (rate callable
`core/ratelimit.py` settings'dan o'qiydi). Yangi web-endpoint cheklash:

    from django_ratelimit.decorators import ratelimit
    from core.ratelimit import rate, user_or_ip_key  # yoki ip_key

    @ratelimit(key=user_or_ip_key, rate=rate, group="yangi_group", method="POST", block=True)

va `RATELIMIT_RATES` ga "yangi_group" qo'shiladi (yo'q bo'lsa cheklanmaydi).
