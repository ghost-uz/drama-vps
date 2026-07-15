# SSL / TLS — Cloudflare Origin CA

Foydalanuvchi bilan Cloudflare orasidagi TLS'ni Cloudflare beradi (universal
sertifikat). Bu hujjat **Cloudflare ↔ origin server** oralig'i haqida.

```
Brauzer --https(CF universal cert)--> Cloudflare --https(Origin CA cert)--> nginx:443
```

## Nega Origin CA (Let's Encrypt emas)?

| | Origin CA | Let's Encrypt |
|---|---|---|
| Kim ishonadi | **Faqat Cloudflare** | Hamma brauzer |
| Muddat | 15 yil | 90 kun |
| Renewal | **Kerak emas** | Avtomatlashtirish shart (certbot) |
| 80-port ochiq bo'lishi | Kerak emas | ACME uchun kerak (http-01) |

Origin sertifikat brauzerga **hech qachon ko'rinmaydi** — foydalanuvchi
Cloudflare'ning universal sertifikatini ko'radi. Shu sabab uning ommaviy
ishonchli emasligi muammo emas.

> **Diqqat:** `https://207.154.194.231` (to'g'ridan IP) ga kirilsa brauzer
> ogohlantiradi — bu **kutilgan** holat, xato emas.

## Fayllar

| Fayl | Vazifa |
|---|---|
| `nginx/ssl.conf` | Prod: TLS (443) + 80→301. `docker-compose.prod.yml` mount qiladi |
| `nginx/default.conf` | Dev (`--profile proxy`): faqat HTTP, sertifikatsiz |
| `nginx/snippets/app.conf` | Ikkalasi `include` qiladigan umumiy tana (location'lar, gzip) |
| `nginx/certs/origin.{pem,key}` | **Serverda qo'lda**, gitignore'da — repo'da YO'Q |

Sertifikatlar `/opt/drama/nginx/certs/` da, chunki repo serverda `/opt/drama`
da — ya'ni ular git ish daraxtining ichida. `.gitignore` (`nginx/certs/`,
`*.pem`, `*.key`, `*.crt`) va `.dockerignore` ularni bloklaydi.

## O'rnatish (serverda)

```sh
# 1) Sertifikatlar joyida va huquqlari to'g'rimi?
cd /opt/drama
ls -l nginx/certs/                     # origin.pem, origin.key
chmod 600 nginx/certs/origin.key       # private kalit — faqat egasiga
chmod 644 nginx/certs/origin.pem
chown root:root nginx/certs/origin.*

# 2) Kalit va sertifikat JUFTMI? (ikki hash BIR XIL bo'lishi shart)
openssl x509 -noout -modulus -in nginx/certs/origin.pem | openssl md5
openssl rsa  -noout -modulus -in nginx/certs/origin.key | openssl md5

# 3) Sertifikat qaysi domenlarni qamraydi + muddati
openssl x509 -in nginx/certs/origin.pem -noout -dates -ext subjectAltName

# 4) Konfiguratsiyani ISHGA TUSHIRMASDAN tekshirish
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  run --rm --no-deps nginx nginx -t

# 5) Qo'llash (faqat nginx qayta yaratiladi — web/db tegilmaydi)
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
  up -d --force-recreate nginx

# 6) Origin'ni to'g'ridan sinash (Cloudflare'ni chetlab)
curl -kI https://localhost/healthz          # 200 kutiladi
curl -I  http://localhost/                  # 301 -> https kutiladi
curl -I  http://localhost/healthz           # 200 (301 EMAS — ataylab)
```

Agar 4-qadam xato bersa nginx qayta ishga tushmaydi va **sayt tushmaydi** —
avval `nginx -t`, keyin `up -d`.

## Cloudflare dashboard sozlamalari

**Tartib muhim** — avval server 443'da ishlayotganiga ishonch hosil qiling
(yuqoridagi 6-qadam), keyin rejimni o'zgartiring. Aks holda sayt tushadi.

1. **SSL/TLS → Overview → `Full (strict)`**
   - `Flexible` = CF↔origin **shifrlanmagan** (+ Django `SECURE_SSL_REDIRECT`
     bilan cheksiz redirect-loop beradi). ISHLATMANG.
   - `Full` = shifrlangan, lekin sertifikat **tekshirilmaydi** (MITM'ga ochiq).
   - `Full (strict)` = shifrlangan **va** tekshiriladi. ← kerakli holat.
2. **SSL/TLS → Edge Certificates → Always Use HTTPS: ON**
   (yo'naltirish edge'da bo'ladi — origin'gacha yetib kelmaydi).
3. **Minimum TLS Version: TLS 1.2** (`ssl.conf` ham 1.2+ ni qo'llaydi).
4. **DNS → A yozuvi `drama.uz` → 207.154.194.231, Proxied (to'q sariq bulut)**
   — kulrang bulut bo'lsa trafik CF'ni chetlab o'tadi va origin sertifikati
   brauzerda ogohlantirish beradi.

Tekshirish:

```sh
curl -sI https://drama.uz/ | grep -i "^HTTP\|^cf-ray"   # 200 + cf-ray => CF orqali
```

## Keyingi qadam (tavsiya): origin'ni qulflash

Hozir origin IP ma'lum bo'lsa Cloudflare'ni **chetlab** to'g'ridan urish mumkin
(rate-limit, WAF, bot-himoya hammasi chetlab o'tiladi). Ikki himoya:

1. **Firewall** — 80/443 ni faqat [Cloudflare IP oralig'iga](https://www.cloudflare.com/ips/)
   ochish (`ufw`).
2. **Authenticated Origin Pulls (mTLS)** — nginx faqat Cloudflare'ning mijoz
   sertifikatini ko'rsatgan ulanishni qabul qiladi
   (`ssl_client_certificate` + `ssl_verify_client on`).

Bularsiz TLS ishlaydi, lekin origin ochiq qoladi.
