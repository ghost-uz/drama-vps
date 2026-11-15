# Resurs kuzatuvi va resize-playbook (1 vCPU / 2 GB droplet) [R4-T2]

Yangi server (2026-11-13, DO fra1) eskisidan kichik: **1 vCPU / 2 GB RAM
(+2 GB swap) / 50 GB disk** — $12/oy. Hozircha bemalol yetadi, lekin "qachon
kattalashtirish kerak" trigger'lari oldindan yozilmasa, sekinlashuvni his
qilib yurib falokatgacha boriladi (2026-09 saboqlari uslubida).

## Baseline — 2026-11-15 (solishtirish etaloni)

Tinch holat (load average 0.03–0.21, 8 konteyner):

| Ko'rsatkich | Qiymat |
|---|---|
| RAM | 1.1 GiB ishlatilgan / 1.9 GiB (875 MiB available) |
| Swap | 52 MiB / 2 GiB (deyarli tegilmagan) |
| Disk `/` | 6.9 GB / 48 GB (**15%**) |
| web | ~320 MiB |
| celery-worker | ~192 MiB |
| celery-beat | ~96 MiB |
| db (postgres) | ~31 MiB |
| nginx / redis / pgbouncer / db-backup | ~15 MiB jami |

## Tez tekshiruv retsepti (serverda, ~1 daqiqa)

```bash
free -h && swapon --show                  # RAM/swap
df -h /                                   # disk
uptime                                    # load average (1 vCPU: >1.0 = navbat)
docker stats --no-stream                  # qaysi konteyner yeyapti
# p95 javob vaqti (nginx access logidan oxirgi 10k so'rov):
docker logs drama-nginx-1 --tail 10000 2>/dev/null | awk '{print $NF}' | sort -n | awk '{a[NR]=$1} END {print "p95:", a[int(NR*0.95)]}'
```

## Trigger'lar — qachon harakat qilish

| Belgi | Chegara | Harakat |
|---|---|---|
| Load average (1 daq) | > 1.0 doimiy (soatlab) | CPU yetmayapti → $18 reja (2 vCPU) |
| Swap ishlatilishi | > 500 MiB doimiy | RAM yetmayapti → $24 reja (4 GB) |
| `available` RAM | < 200 MiB doimiy | RAM → $24 reja |
| OOM-kill (dmesg / konteyner restart) | 1 marta ham | darhol RAM reja |
| Disk | > 70% | avval tozalash (`docker system prune -a` ehtiyot bilan, eski loglar), keyin reja |
| p95 javob | > 1.5s doimiy (CDN'siz sahifalar) | profil qilish, keyin CPU reja |

## DO panel alert (egasi, bir martalik — 5 daqiqa)

DO panel → droplet → **Monitoring** → Create Alert Policy:

1. **CPU > 80%, 10 daqiqa davomida** → email.
2. **Memory > 90%, 10 daqiqa** → email.

(DO agenti droplet'da bor-yo'qligini panel ko'rsatadi; yangi DO image'larda
odatda o'rnatilgan. Alert'lar tashqi uptime-monitor [R0-T3] bilan BIRGA
ishlaydi: uptime "o'ldi"ni, bu alert'lar "o'lyapti"ni ushlaydi.)

## Resize-playbook (DO panel, downtime ~1-2 daqiqa)

1. Backup tekshiring: GCS'da bugungi dump bor (R0-T4 avto), xohlasangiz
   qo'shimcha `bash scripts/pull_server_backup.sh`.
2. DO panel → droplet → **Resize**.
3. ⚠️ **FAQAT "CPU and RAM only" turini tanlang. Disk resize QILMANG** —
   disk kattalashtirish ORQAGA QAYTMAYDI (keyin kichikroq rejaga tushib
   bo'lmaydi). 50 GB'ning 15% band — disk muammo emas.
4. Droplet o'chiriladi → reja tanlanadi → yoqiladi. **IP SAQLANADI** —
   DNS/Cloudflare'ga tegilmaydi.
5. Yoqilgach: `docker ps` (8 konteyner Up, compose `restart: unless-stopped`
   o'zi ko'taradi), `curl -s https://dramauz.com/readyz`, healthchecks.io
   drama-beat "up" ga qaytganini tekshiring.
6. Rejalar (2026-11 narxlari): $12 = 1 vCPU/2GB (joriy) → **$18 = 2 vCPU/2GB
   (CPU uchun)** → **$24 = 2 vCPU/4GB (RAM uchun)**.

Resize'dan keyin baseline'ni shu faylda yangilang.
