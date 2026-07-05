# CI (GitHub Actions) [P13-T1]

`.github/workflows/ci.yml` — har push (main) va har PR'da 4 parallel job.

| Job | Nima qiladi | Lokal ekvivalent |
|-----|-------------|------------------|
| `lint` | pre-commit barcha fayllarda (ruff lint+format, mypy core, gigiyena) | `pre-commit run --all-files` |
| `test` | pytest (sqlite :memory:) + **coverage gate** (pyproject `fail_under=73`) + OpenAPI sxema validatsiyasi | `pytest --cov` |
| `migrations-postgres` | Barcha migratsiyalar **real postgres:16**da nol'dan qo'llanadi + `makemigrations --check` drift | Docker db bilan `manage.py migrate` |
| `docker-build` | Production image quriladi (registry'ga push YO'Q — bu P13-T2) | `docker build .` |

Nega ikkita DB: testlar sqlite'da (tez, 8s); migratsiya job'i esa sqlite
ushlamaydigan postgres-xatolarni (SQL sintaksis, constraint, index) topadi.

## Merge'ni bloklash (bir martalik, GitHub UI — repo egasi)

1. GitHub → repo → **Settings → Branches → Add branch protection rule**
2. Branch name pattern: `main`
3. ✅ *Require status checks to pass before merging* → qidiruvdan belgilang:
   `lint`, `test`, `migrations-postgres`, `docker-build`
4. (tavsiya) ✅ *Require branches to be up to date before merging*

Shu qadamsiz workflow ishlaydi-yu, lekin qizil bo'lsa ham merge qilib
yuborish mumkin bo'ladi — acceptance'ning "yashil bo'lmasa merge bloklanadi"
sharti aynan shu sozlama.

## Sirlar

CI hech qanday secret talab qilmaydi: barcha `config()` chaqiruvlari
default'li (tekshirilgan), test settings sqlite/locmem ishlatadi, Docker
build faqa quradi. P13-T2 (CD/deploy)da registry/SSH sirlar qo'shiladi.

## CI yiqilsa

- `lint` — lokal `pre-commit run --all-files` bilan takrorlang (hook'lar
  avto-tuzatgan bo'lsa `git add` + qayta commit).
- `test` — `pytest --cov`; coverage 73% dan tushib ketgan bo'lsa test yozing
  (gate'ni pasaytirish TAQIQLANGAN — pyproject'dagi izoh).
- `migrations-postgres` — odatda postgres-spesifik SQL yoki drift:
  `makemigrations --check` lokal ham ishlaydi.
