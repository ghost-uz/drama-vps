# Deploy (CD) — zero-downtime, migratsiya, rollback [P13-T2]

Prod: **gunicorn + nginx** (Passenger OLIB TASHLANDI), Docker Compose, GHCR
registry image. CI (`ci.yml`) yashil bo'lgach `deploy.yml` image'ni build+push
qiladi va serverga SSH orqali `scripts/deploy.sh` ni ishga tushiradi.

## Arxitektura

```
Cloudflare --https(Origin CA)--> nginx:443 -> gunicorn(web:8000, 3 worker)
                                    |            +-- celery-worker, celery-beat
                                    +-- /static /media (volume)
                                  db(postgres16)  redis7

nginx:80 -> 301 https (istisno: /healthz — lokal diagnostika uchun ochiq)
```

- TLS origin'da tugaydi: Cloudflare Origin CA sertifikati (`nginx/ssl.conf`).
  Sertifikatlar serverda `/opt/drama/nginx/certs/` (gitignore'da). Batafsil:
  [`docs/ops/ssl.md`](ssl.md).

- Image: `ghcr.io/<owner>/drama-web:<tag>` (tag = commit SHA yoki `vX.Y.Z`).
- `docker-compose.yml` + `docker-compose.prod.yml` (registry image + ajratilgan
  migratsiya).

## Zero-downtime tamoyili

1. **Migratsiya web'dan AJRATILGAN**: `migrate` bir martalik servisi (profiles:
   tools) migratsiya + collectstatic'ni bajaradi — **eski web hali ishlab
   turgan holda**. Shu sabab migratsiyalar **expand/contract** (orqaga mos)
   bo'lishi SHART (pastga qarang).
2. **Web cutover health-gated**: yangi web `/healthz` sog'lom bo'lgunча
   kutiladi; nginx `proxy_next_upstream` qisqa uzilishni qayta uradi —
   foydalanuvchi sezmaydi (near-zero-downtime).
3. **Nosozlikda avtomatik rollback**: web sog'lom bo'lmasa deploy skripti
   oldingi tegga qaytaradi.

> **Qat'iy zero-downtime** (0 ms) uchun 2+ web replika + rolling update kerak
> (kelajak). Joriy yechim bitta hostda amaliy: migratsiya uzilishsiz, web
> cutover nginx-retry bilan sezilmas.

## Expand / contract migratsiya (MAJBURIY intizom)

Rollback KODni qaytaradi, **sxemani EMAS**. Shu sabab har migratsiya ikki
deploy'ga bo'linadi:

- **Expand** (deploy 1): faqat QO'SHISH — yangi ustun `null=True`/default bilan,
  yangi jadval. Eski kod ham, yangi kod ham ishlaydi.
- **Contract** (deploy 2, expand barqaror bo'lgach): eski ustunni olib tashlash,
  `NOT NULL` qilish. Faqat expand tarqalgani TASDIQLANGACH.

Buzuvchi (drop/rename/not-null) migratsiyani expand bilan BIR deploy'da
qo'shmang — aks holda rollback qilingan eski kod singan sxemaga uriladi.

## Birinchi marta server sozlash

```sh
git clone <repo> /opt/drama && cd /opt/drama
cp .env.example .env && nano .env      # sirlarni to'ldiring (DB_PASSWORD, ...)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d db redis
./scripts/deploy.sh latest             # birinchi deploy
```

## CD orqali deploy (odatiy)

1. `main`'ga push -> `ci.yml` yashil.
2. **Actions -> Deploy -> Run workflow** (yoki `vX.Y.Z` teg push).
3. `deploy.yml`: image build+push (GHCR) -> SSH -> `scripts/deploy.sh <SHA>`.

Kerakli sirlar (Settings -> Secrets -> Actions): `SSH_HOST`, `SSH_USER`,
`SSH_KEY`, `DEPLOY_PATH`.

## Qo'lda deploy (serverda)

```sh
export IMAGE_NAME=ghcr.io/<owner>/drama-web
./scripts/deploy.sh <tag>      # pull -> migrate -> web -> healthz -> (rollback?)
```

## Rollback

```sh
./scripts/rollback.sh              # oldingi muvaffaqiyatli tegga (.deploy/previous_tag)
./scripts/rollback.sh <tag>       # aniq tegga
```

Deploy nosoz bo'lsa `deploy.sh` buni AVTOMATIK bajaradi. Migratsiya buzuvchi
bo'lgan holdagina (contract erta qo'llangan) avval DB backup'dan tiklang
(P13-T3).
