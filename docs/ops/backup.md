# Backup, tiklash mashqi va staging [P13-T3]

## Nima himoyalangan

| Ma'lumot | Mexanizm | Joy |
|----------|----------|-----|
| PostgreSQL | kunlik `pg_dump` (custom format) — `db-backup` sidecar | `dbbackups` volume (+ ixtiyoriy GCS) |
| Media (yuklamalar) | GCS **Object Versioning** | GCS bucket `cdn.drama.uz` |
| Kod | git + GHCR image teglari | GitHub / registry |

## DB backup (avtomatik)

`db-backup` sidecar (postgres:16-alpine, busybox crond) **har kun 03:00** da
`scripts/backup.sh` ni ishga tushiradi:
- `pg_dump --format=custom` -> `dbbackups:/backups/drama-<ts>.dump`
- saqlash siyosati: `BACKUP_RETENTION_DAYS` (default 14) kundan eski o'chiriladi
- `GCS_BACKUP_BUCKET` berilsa dump off-site (GCS) ga ham nusxalanadi

Prod stack (`docker-compose.prod.yml`) `up -d` bilan sidecar avtomatik ishlaydi.

Qo'lda backup:
```sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec db-backup sh /scripts/backup.sh
```

## Media backup (GCS Object Versioning)

Media GCS'da saqlanadi (prod). Bir marta yoqing (o'chirilgan/ustiga-yozilgan
obyektlarni tiklash imkonini beradi):
```sh
gsutil versioning set on gs://cdn.drama.uz
# eski versiyalarni tozalash siyosati (masalan 30 kun):
gsutil lifecycle set gcs-lifecycle.json gs://cdn.drama.uz
```

## Tiklash (restore)

```sh
# Mavjud dump'lar:
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec db-backup ls -lh /backups
# Tiklash (JORIY DB ustiga — avval ehtiyot backup oling!):
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec db-backup \
    sh /scripts/restore.sh /backups/drama-<ts>.dump
```

## Tiklash mashqi (drill) — TASDIQLANGAN

Backup faqat tiklash sinovidan o'tgandagina ishonchli. Bu tsikl **lokal Docker
postgres'da sinab ko'rilgan** (2026-07-06) va muntazam takrorlanishi kerak
(masalan har chorakda, staging'da):

1. Ma'lum ma'lumot yozing (masalan test kino/foydalanuvchi).
2. `backup.sh` -> `.dump` yarating; o'lchami > 0 ekanini tekshiring.
3. Ma'lumotni **buzing** (jadvalni o'chiring / qatorni yo'qoting).
4. `restore.sh <dump>` bilan tiklang.
5. 1-qadamdagi ma'lumot QAYTGANINI tasdiqlang.

Natija hujjatlansin (sana, dump o'lchami, tiklash vaqti, muvaffaqiyat).

## Staging muhiti

Prod'ga o'xshash, izolyatsiyalangan (`name: drama-staging`, alohida volume/port):
```sh
cp .env .env.staging          # staging DB nomi/parolini o'zgartiring
docker compose --env-file .env.staging \
  -f docker-compose.yml -f docker-compose.prod.yml -f docker-compose.staging.yml up -d
# Staging: http://localhost:8080 — yangi image'ni prod'ga chiqarishdan oldin sinang.
```

Deploy zanjiri: **staging'da sinash -> prod deploy (P13-T2)** -> nosozlikda
avtomatik rollback.
