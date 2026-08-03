"""GCS bucket CORS allowlist'ini JONLI tekshirish [domen ko'chishi qo'riqchisi].

`cdn.drama.uz` sayt domenidan BOSHQA origin (ataylab — docs/ops/domain-migration.md
§2). Shu bois `@font-face` shriftlar va `fetch()` uchun bucket CORS allowlist'i
sayt domenini o'z ichiga OLISHI shart. Ro'yxatda bo'lmasa nosozlik **jim**
keladi: CSS ham, JS ham yuklanadi (ular CORS talab qilmaydi), lekin Unfold
admin ikonkalari ligatura MATNI bo'lib qoladi (`menu`, `search`, ...).

    python manage.py check_gcs_cors
    python manage.py check_gcs_cors --strict   # CI/cron: muammoda exit 1
    python manage.py check_gcs_cors --apply    # config/cors.json ni bucket'ga yozish

UCH QATLAM tekshiriladi, chunki har biri BOSHQA nosozlikni ushlaydi va
biri ikkinchisini ko'ra olmaydi:

  1. repo `config/cors.json`  <->  JONLI bucket
     Fayl bilan haqiqat farqini ushlaydi. 2026-07-31 da aynan shu yuz berdi:
     faylda `["*"]` turgan, bucket'da esa faqat eski domen — ya'ni fayl hech
     qachon qo'llanmagan.

  2. CDN edge javobi (har bir origin uchun)
     Bucket to'g'ri bo'lsa ham edge buzuq javobni keshlab turgan bo'lishi
     mumkin: GCS `Vary: Origin` yuboradi -> Cloudflare HAR origin uchun
     alohida nusxa saqlaydi, statik obyektlar esa `immutable, max-age=1yil`.
     Bucket'ni tuzatish bu keshni TOZALAMAYDI (Purge kerak). 1-qatlam buni
     printsipial ko'ra olmaydi.

  3. ro'yxatda YO'Q origin rad etiladimi
     Allowlist tasodifan `["*"]` ga aylanib qolmaganini tasdiqlaydi.

2-qatlam kalit TALAB QILMAYDI (oddiy HTTP) — laptopdan ham, CI'dan ham
ishlaydi. 1-qatlam `settings.GS_CREDENTIALS` bo'lmasa (dev) o'tkazib yuboriladi.
"""

import json
from pathlib import Path
from typing import Any

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

TIMEOUT = 10
FONT_SUFFIXES = (".woff", ".woff2", ".ttf", ".otf")

# Allowlist'da BO'LMASLIGI kerak bo'lgan origin (salbiy nazorat).
UNLISTED_ORIGIN = "https://unlisted-origin.invalid"


class Command(BaseCommand):
    help = "GCS bucket CORS allowlist'ini jonli tekshiradi (bucket + CDN edge)."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--strict", action="store_true", help="Muammo topilsa exit 1 (CI/cron uchun)"
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="config/cors.json ni bucket'ga YOZISH (kalit kerak)",
        )
        parser.add_argument(
            "--force",
            action="store_true",
            help="--apply origin O'CHIRSA ham davom etish (xavfli)",
        )

    # -- yordamchi chiqish --------------------------------------------------

    def _ok(self, message: str) -> None:
        self.stdout.write(self.style.SUCCESS(f"  + {message}"))

    def _warn(self, message: str) -> None:
        self.stdout.write(self.style.WARNING(f"  ! {message}"))

    # -- ma'lumot manbalari -------------------------------------------------

    @property
    def cors_file(self) -> Path:
        return Path(settings.BASE_DIR) / "config" / "cors.json"

    def _repo_cors(self) -> list[dict[str, Any]]:
        try:
            data = json.loads(self.cors_file.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise CommandError(f"{self.cors_file} topilmadi.") from exc
        except json.JSONDecodeError as exc:
            raise CommandError(f"{self.cors_file} yaroqsiz JSON: {exc}") from exc
        if not isinstance(data, list) or not data:
            raise CommandError(f"{self.cors_file} bo'sh yoki ro'yxat emas.")
        return data

    def _bucket(self) -> Any:
        """Kalit bo'lsa bucket obyekti, bo'lmasa None (dev'da tekshiruv skip)."""
        credentials = getattr(settings, "GS_CREDENTIALS", None)
        if credentials is None:
            return None
        from google.cloud import storage  # noqa: PLC0415 — faqat prod yo'lida kerak

        client = storage.Client(credentials=credentials, project=credentials.project_id)
        return client.get_bucket(settings.GS_BUCKET_NAME)

    def _font_urls(self) -> list[str]:
        """Manifestdan shrift URL'lari. Edge keshi HAR URL uchun alohida —
        shuning uchun bitta emas, HAMMA shriftni tekshirish kerak."""
        base = f"https://{settings.GS_CUSTOM_DOMAIN}/static/"
        try:
            resp = requests.get(f"{base}staticfiles.json", timeout=TIMEOUT)
            resp.raise_for_status()
            paths = resp.json()["paths"]
        except (requests.RequestException, ValueError, KeyError) as exc:
            raise CommandError(f"Manifest o'qilmadi ({base}staticfiles.json): {exc}") from exc
        return [base + v for k, v in sorted(paths.items()) if k.endswith(FONT_SUFFIXES)]

    def _probe(self, url: str, origin: str) -> tuple[str | None, str, str]:
        """(ACAO qiymati|None, cf-cache-status, age) qaytaradi."""
        try:
            resp = requests.head(url, headers={"Origin": origin}, timeout=TIMEOUT)
        except requests.RequestException as exc:
            raise CommandError(f"CDN'ga ulanib bo'lmadi ({url}): {exc}") from exc
        headers = resp.headers
        return (
            headers.get("Access-Control-Allow-Origin"),
            headers.get("cf-cache-status", "?"),
            headers.get("age", "0"),
        )

    # -- qatlam 1: repo <-> bucket -----------------------------------------

    @staticmethod
    def _origins(cors: list[dict[str, Any]]) -> set[str]:
        return {o for rule in cors for o in rule.get("origin", [])}

    @staticmethod
    def _origins_ordered(cors: list[dict[str, Any]]) -> list[str]:
        """Origin'lar FAYLDAGI tartibda (takrorlarsiz).

        Tartib MUHIM: birinchi origin "asosiy sayt domeni" deb qabul qilinadi va
        chuqur (har-shrift) edge tekshiruvi AYNAN shunga qarshi bajariladi. Saralab
        yuborilsa alifbo bo'yicha eski domen birinchi bo'lib qoladi — holbuki edge
        zaharlanishi foydalanuvchilar YURADIGAN domenda yuz beradi, ya'ni eng kuchli
        tekshiruv eng xavfsiz nishonga qaratilgan bo'lardi.
        Shu bois `config/cors.json` da asosiy domen BIRINCHI turishi kerak.
        """
        seen: dict[str, None] = {}
        for rule in cors:
            for origin in rule.get("origin", []):
                seen.setdefault(origin, None)
        return list(seen)

    def _classify_drift(
        self, repo: list[dict[str, Any]], live: list[dict[str, Any]]
    ) -> tuple[list[str], list[str]]:
        """Repo <-> bucket farqini MUAMMO va OGOHLANTIRISH ga ajratadi.

        SIYOSAT QARORI (o'zgartirsangiz bo'ladi — quyida sabablari):

        * repoda BOR, bucket'da YO'Q  -> MUAMMO.
          E'lon qilingan niyat kuchga kirmagan. Aynan shu 2026-07-31 buzilishi:
          foydalanuvchiga KO'RINADIGAN nosozlik.

        * bucket'da BOR, repoda YO'Q  -> OGOHLANTIRISH, muammo emas.
          Kimdir shoshilinch ravishda panel orqali qo'shgan bo'lishi mumkin
          (jonli tuzatish). Buni MUAMMO deb belgilash CI'ni sindiradi, holbuki
          sayt ishlayapti. Agar sizda "faqat repo hukmron" qoidasi bo'lsa,
          buni problems'ga ko'chiring.

        * origin'lardan tashqari farqlar (method/responseHeader/maxAge)
          -> OGOHLANTIRISH: ular odatda nosozlikka olib kelmaydi, lekin
          drift belgisidir.
        """
        problems: list[str] = []
        warnings: list[str] = []

        repo_origins, live_origins = self._origins(repo), self._origins(live)

        if missing := sorted(repo_origins - live_origins):
            problems.append(
                f"cors.json da bor, lekin bucket'da YO'Q: {', '.join(missing)} "
                "-> shu domendagi shriftlar/fetch sinadi (--apply bilan tuzating)."
            )
        if extra := sorted(live_origins - repo_origins):
            warnings.append(
                f"bucket'da bor, lekin cors.json da YO'Q: {', '.join(extra)} "
                "-> qo'lda qo'shilgan bo'lishi mumkin; repoga kiriting."
            )
        if repo_origins == live_origins and repo != live:
            warnings.append(
                "origin'lar mos, lekin qolgan maydonlar farq qiladi "
                "(method/responseHeader/maxAgeSeconds)."
            )
        return problems, warnings

    # -- qatlam 2 va 3: CDN edge -------------------------------------------

    @staticmethod
    def _is_probeable(origin: str) -> bool:
        """`*` HAQIQIY origin emas — u siyosatdagi joker, `Origin:` sarlavhasining
        qiymati emas (brauzer hech qachon `Origin: *` yubormaydi). Probe'dan
        chiqaramiz, aks holda ma'nosiz "nosozlik" hisobotlari paydo bo'ladi."""
        return origin.startswith(("http://", "https://"))

    def _check_edge(self, origins: list[str], problems: list[str], wildcard: bool) -> None:
        fonts = self._font_urls()
        if not fonts:
            self._warn("manifestda shrift topilmadi — edge tekshiruvi o'tkazib yuborildi.")
            return

        canonical = fonts[-1]
        probeable = [o for o in origins if self._is_probeable(o)]

        if probeable:
            primary = probeable[0]

            # 2a) HAMMA shrift x asosiy origin: edge keshi HAR URL uchun alohida.
            stale = []
            for url in fonts:
                acao, cache, age = self._probe(url, primary)
                if acao is None:
                    stale.append(f"{url.rsplit('/', 1)[1]} (cache={cache}, age={age})")
            if stale:
                problems.append(
                    f"{primary} uchun {len(stale)}/{len(fonts)} shrift ACAO'siz qaytdi: "
                    + "; ".join(stale)
                    + " -> bucket to'g'ri bo'lsa bu KESHLANGAN buzuq javob: "
                    "Cloudflare -> Caching -> Purge Cache (docs/ops/domain-migration.md §2.2)."
                )
            else:
                self._ok(f"{len(fonts)} shrift {primary} uchun to'g'ri ACAO qaytardi")

            # 2b) HAR origin x bitta shrift: allowlist'da domen yetishmayaptimi.
            for origin in probeable:
                acao, cache, age = self._probe(canonical, origin)
                if acao is None:
                    problems.append(
                        f"{origin} uchun ACAO YO'Q (cache={cache}, age={age}) "
                        "-> allowlist yoki edge keshi."
                    )
                else:
                    self._ok(f"{origin} -> {acao}")
        else:
            self._warn(
                "cors.json da haqiqiy origin yo'q (faqat `*`) — shrift bo'yicha "
                "chuqur tekshiruv o'tkazib yuborildi."
            )

        # 3) salbiy nazorat: ro'yxatda yo'q origin rad etilishi SHART.
        # `*` amalda bo'lsa ACAO olish KUTILGAN natija — muammo deb belgilamaymiz,
        # lekin siyosat ochiqligini baribir aytamiz.
        acao, _, _ = self._probe(canonical, UNLISTED_ORIGIN)
        if wildcard:
            self._warn(
                "allowlist `*` — istalgan sayt assetlarni JS orqali o'qiy oladi; "
                "salbiy nazorat o'tkazib yuborildi."
            )
        elif acao is None:
            self._ok("ro'yxatda yo'q origin rad etildi (allowlist kuchda)")
        else:
            problems.append(
                f"ro'yxatda YO'Q origin ACAO oldi ({acao}) "
                "-> allowlist ochiq qolgan, har qanday sayt JS orqali o'qiy oladi."
            )

    # -- --apply ------------------------------------------------------------

    def _apply(self, repo: list[dict[str, Any]], bucket: Any, force: bool) -> None:
        live = list(bucket.cors or [])
        removed = sorted(self._origins(live) - self._origins(repo))
        if removed and not force:
            raise CommandError(
                f"--apply {len(removed)} ta origin'ni O'CHIRADI: {', '.join(removed)}. "
                "Lokal cors.json eskirgan bo'lishi mumkin. Ataylab bo'lsa --force qo'shing."
            )
        self.stdout.write("ESKI (rollback uchun saqlang):")
        self.stdout.write(json.dumps(live, indent=2))
        bucket.cors = repo
        bucket.patch()
        bucket.reload()
        self._ok("bucket CORS yangilandi")
        self._warn(
            "Edge keshi TOZALANMADI: eski javoblar `immutable` bo'lgani uchun "
            "Cloudflare Purge Cache ham qiling (docs/ops/domain-migration.md §2.2)."
        )

    # -- asosiy oqim --------------------------------------------------------

    def handle(self, *args: Any, **options: Any) -> None:
        repo = self._repo_cors()
        problems: list[str] = []
        warnings: list[str] = []

        bucket = self._bucket()
        # AMALDAGI siyosat: kalit bo'lsa bucket'niki, bo'lmasa repo niyati.
        effective = repo

        if bucket is None:
            self._warn(
                "GS_CREDENTIALS yo'q (dev?) — bucket solishtiruvi o'tkazib yuborildi; "
                "edge tekshiruvi baribir bajariladi."
            )
        else:
            if options["apply"]:
                self._apply(repo, bucket, options["force"])
            effective = list(bucket.cors or [])
            drift_problems, drift_warnings = self._classify_drift(repo, effective)
            problems += drift_problems
            warnings += drift_warnings
            if not drift_problems and not drift_warnings:
                self._ok("cors.json bucket bilan to'liq mos")

        self._check_edge(
            self._origins_ordered(repo), problems, wildcard="*" in self._origins(effective)
        )

        for warning in warnings:
            self._warn(warning)

        if problems:
            self.stdout.write(self.style.ERROR("MUAMMOLAR:"))
            for problem in problems:
                self.stdout.write(self.style.ERROR(f"  - {problem}"))
            if options["strict"]:
                raise CommandError(f"{len(problems)} ta CORS muammosi topildi.")
        else:
            self.stdout.write(self.style.SUCCESS("Barcha tekshiruvlar toza."))
