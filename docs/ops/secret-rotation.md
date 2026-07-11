# Sirlarni rotatsiya qilish va git tarixini tozalash (P0-T2)

> ⚠️ **Holat:** Quyidagi sirlar git TARIXIDA topildi (origin: GitHub). Repo ommaviy yoki
> baham ko'rilgan bo'lsa, ularning HAMMASI kompromatsiyalangan deb hisoblanadi va
> ROTATSIYA qilinishi shart. Faqat `.gitignore` ga qo'shish YETARLI EMAS — qiymat tarixda qoladi.

## 1. Kompromatsiyalangan sirlar (git audit natijasi)

| Sir | Tarqalgan commitlar | Amal |
|-----|---------------------|------|
| GCS service-account kaliti (`drama-key-v2.json`) | `225c47d`, `545ea7d` (fayl) | GCP'da kalitni o'chir + yangi yarat |
| Django `SECRET_KEY` | `d2aa386`, `cee09be` (settings.py hardcoded) | Yangi generatsiya, `.env` ga qo'y |
| DB paroli (`DB_PASSWORD`) | `225c47d`, `cee09be` | PostgreSQL'da parolni almashtir |
| Bunny Stream API kaliti | `2783bac` | Bunny dashboard'da API key qayta yarat |
| Telegram bot tokeni | `225c47d`, `8ef0106`, `cee09be` | @BotFather'da token revoke + yangi |
| `.pyc` bytecode (settings) | tarixda | filter-repo bilan tozalanadi |

`.env` fayli HECH QACHON commit qilinmagan (yaxshi) — lekin qiymatlar yuqoridagi
hardcoded nusxalar orqali baribir tarqagan.

## 2. Rotatsiya bosqichlari (SIZ bajarasiz — men qila olmayman)

### 2.1 GCS service-account kaliti
1. GCP Console → IAM & Admin → Service Accounts → akkaunt → "Keys".
2. Eski kalitni (drama-key-v2) **DELETE**.
3. "Add Key" → JSON → yuklab ol. Faylni **repo TASHQARISIDA** saqla
   (masalan serverda `/etc/drama/gcs.json`).
4. `.env` ga: `GS_CREDENTIALS_FILE=/etc/drama/gcs.json` (prod.py shu env'ni o'qiydi).

### 2.2 Django SECRET_KEY
`.env` ga (chatda berilgan yangi qiymatni qo'ying):
```
SECRET_KEY=<yangi-qiymat>
```
Qayta generatsiya buyrug'i:
```
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```
⚠️ SECRET_KEY o'zgarsa barcha sessiya va parol-reset tokenlari bekor bo'ladi (hamma qayta login qiladi).

### 2.3 DB paroli, Bunny API, Telegram token
- PostgreSQL: `ALTER USER drama_user WITH PASSWORD '<yangi>';` → `.env` `DB_PASSWORD`.
  - ⚠️ **Lokal Docker stack'da ham**: `drama_pgdata` volume ESKI parol bilan qoladi (`POSTGRES_PASSWORD` faqat volume birinchi init'ida amal qiladi) → parolni konteyner ichida yangilang: `docker exec drama-db-1 psql -U drama_user -d drama_db -c "ALTER USER drama_user WITH PASSWORD '<yangi>';"` — aks holda web `password authentication failed` bilan restart-loop'da qoladi.
- Bunny: dashboard → Account → API Key → Regenerate → `.env` `BUNNY_STREAM_API_KEY`.
- Telegram: @BotFather → `/revoke` → yangi token → `.env` `TELEGRAM_BOT_TOKEN`.

## 3. Hozirgi kalit faylini untrack qilish
```
git rm --cached drama-key-v2.json
git commit -m "chore(security): stop tracking GCS key file"
```
(Fayl lokalda qoladi, faqat git indeksidan chiqadi.)

## 4. Git tarixidan butunlay tozalash (BUZUVCHI — avval ZAXIRA ol)
`git-filter-repo` (tavsiya):
```
pip install git-filter-repo
git filter-repo --invert-paths \
  --path drama-key-v2.json \
  --path config/__pycache__/settings.cpython-312.pyc
```
settings.py tarixidagi hardcoded matn-sirlarni `--replace-text` bilan `***REMOVED***` ga almashtir.

## 5. Force-push va jamoa
```
git push origin --force --all
git push origin --force --tags
```
⚠️ Barcha hamkorlar repo'ni qaytadan klon qilishi shart. GitHub eski commit/fork'larni
keshlashi mumkin — zarur bo'lsa GitHub Support (sensitive data removal) ga murojaat.

## 6. Tekshiruv
```
git log --all --oneline -- drama-key-v2.json    # BO'SH bo'lishi kerak
git log --all -S "SECRET_KEY = '" -- "*.py"      # BO'SH bo'lishi kerak
```
