# Backup, tiklash mashqi va staging [P13-T3]

## Nima himoyalangan

| Ma'lumot | Mexanizm | Joy |
|----------|----------|-----|
| PostgreSQL | kunlik `pg_dump` (custom format) — `db-backup` sidecar | `dbbackups` volume (lokal) |
| PostgreSQL off-site | kunlik GCS sinxron — `core.tasks.offsite_db_backup_task` [R0-T4] | GCS bucket (`GCS_BACKUP_BUCKET`, private) |
| Media (yuklamalar) | GCS **Object Versioning** | GCS bucket `cdn.drama.uz` |
| Kod | git + GHCR image teglari | GitHub / registry |

## DB backup (avtomatik)

`db-backup` sidecar (postgres:16-alpine, busybox crond) **har kun 03:00 UTC**
(= 08:00 Tashkent) da `scripts/backup.sh` ni ishga tushiradi:
- `pg_dump --format=custom` -> `dbbackups:/backups/drama-<ts>.dump`
- saqlash siyosati: `BACKUP_RETENTION_DAYS` (default 14) kundan eski o'chiriladi
- pg_dump yiqilsa chala/bo'sh fayl DARHOL o'chiriladi (`if ! pg_dump` qalqoni —
  `set -e` ga topshirilsa 0 baytli "dump" ro'yxatda haqiqiydek qolardi)

Prod stack (`docker-compose.prod.yml`) `up -d` bilan sidecar avtomatik ishlaydi;
`scripts/deploy.sh` ham uni har deploy'da `up -d` qiladi.

> ⚠️ **2026-09-15 gacha bunday EMAS edi:** `deploy.sh` faqat
> web/worker/beat/nginx'ni ko'tarardi, birinchi o'rnatish esa `up -d db redis`
> qilgan — sidecar hech qachon ishga tushmagan va prod'da birorta ham avtomatik
> backup bo'lmagan. Tekshirish: `docker volume ls | grep dbbackups` (volume
> bo'lmasa — backup ham yo'q).

Qo'lda backup:
```sh
docker compose -f docker-compose.yml -f docker-compose.prod.yml exec db-backup sh /scripts/backup.sh
```

## Off-site nusxa (GCS) [R0-T4]

2026 sentyabr-noyabr saboqlari: lokal dump **o'sha serverning o'zida** yotadi —
server yo'qolsa (to'lov, halokat) dumplar ham birga yo'qoladi; yagona boshqa
nusxa noutbukdagi qo'lda to'plam edi. Endi kunlik avtomatik off-site bor:

- **Mexanizm:** `core.tasks.offsite_db_backup_task` (beat, har kuni **08:30
  Tashkent** = 03:30 UTC — sidecar dumpidan 30 daqiqa keyin) `/backups` dagi
  `drama-*.dump` fayllardan GCS'da YO'Qlarini `gs://$GCS_BACKUP_BUCKET/db/` ga
  yuklaydi. Sinxron **idempotent**: worker o'lik yotgan kunlarning dumplari
  keyingi o'tishda to'ldiriladi.
- **Nega celery (gsutil emas):** sidecar postgres-alpine'da gsutil YO'Q (eski
  `backup.sh` dagi `command -v gsutil` sharti shu bois jim o'tib ketardi va
  hech qachon yuklamagan); web image'ida esa `google-cloud-storage` + SA kalit
  allaqachon bor, celery esa dead-man heartbeat kuzatuvida [R0-T3].
- **Jimlik yo'q:** 3 retry (10 daqiqa oraliq) tugasa ham xato bo'lsa — admin
  Telegram'ga 🚨 alert; `/backups` bo'sh bo'lsa yoki 0 baytli dump ko'rinsa —
  ⚠️ alert.
- **Saqlash:** lokalda 14 kun (`BACKUP_RETENTION_DAYS`), GCS'da bucket
  lifecycle qoidasi (default **60 kun**, `--create-bucket` o'rnatadi).

### Birinchi sozlash (bir martalik)

1. `.env` ga bucket nomi: `GCS_BACKUP_BUCKET=my-drama-uz-db-backups`
   (ALOHIDA, private bucket — `cdn.drama.uz` EMAS: u ommaviy o'qiladi!).
2. Stack'ni yangilang (celery-worker'ga `dbbackups` ro-mount tushishi uchun):
   `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d`
3. Bucket'ni tayyorlash + birinchi sinxron (idempotent):
   ```sh
   docker compose -f docker-compose.yml -f docker-compose.prod.yml \
       exec celery-worker python manage.py sync_db_backups --create-bucket
   ```
   SA'da `storage.buckets.create` bo'lmasa buyruq aniq yo'riqnoma bilan
   yiqiladi (egasi konsolda yaratadi + SA'ga `roles/storage.objectAdmin`).
4. Isbot: chiqishda `+ yuklandi: gs://.../db/drama-<ts>.dump`; ertasi kuni
   03:30 UTC dan keyin yana `sync_db_backups` ishga tushirilsa yangi dump
   "allaqachon GCS'da" bo'lishi kerak (beat o'zi yuklagan).

### GCS'dan tiklash (server butunlay yo'qolganda)

```sh
# Lokal kompyuterda (SA kaliti bilan):
gcloud storage ls gs://$GCS_BACKUP_BUCKET/db/          # yoki GCP Console
gcloud storage cp gs://$GCS_BACKUP_BUCKET/db/drama-<ts>.dump .
# Keyin odatdagi restore: docs/ops/server-migration.md runbook'i
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

### Choraklik ritual [R4-T3]

Mashq RITUAL sifatida **har chorakda** o'tkaziladi (~30 daqiqa): egasi
kalendariga takrorlanuvchi eslatma qo'yiladi. Retsept (noutbukdan):

1. `scripts/pull_server_backup.sh` — serverdan eng yangi dump olinadi
   (yoki GCS'dan: `gcloud storage cp gs://<bucket>/db/<oxirgi>.dump .`).
2. Lokal toza postgres'ga tiklash (`restore.sh` yoki docker-run postgres:16).
3. `row_counts` diff: jadval-qator sanoqlari server bilan MOS kelishi
   (server-migration.md da tayyor so'rov bor).
4. Natijani quyidagi jurnalga yozish.

**Mashq jurnali:**

| Sana | Turi | Natija |
|---|---|---|
| 2026-07-06 | lokal drill | ✅ tsikl to'liq o'tdi |
| 2026-11-13 | **JANG** (server o'limi) | ✅ yangi server LATEST dumpdan tiklandi, row_counts 67/67 mos, ~45 daq (server-migration.md) |
| ~2027-02 (keyingi) | choraklik drill | — |

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
