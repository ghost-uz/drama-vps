"""Bunny CDN xavfsizlik sozlamalarini JONLI tekshirish [P4-T2].

Token auth va referer/hotlink cheklovi Bunny PANELida yoqiladi (kodda emas) —
bu buyruq sozlama haqiqatan kuchga kirganini CDN'ga real so'rovlar bilan
tasdiqlaydi:

    python manage.py check_bunny_security <video_guid>
    python manage.py check_bunny_security <video_guid> --strict  # CI/cron: muammoda exit 1

Tekshiruvlar: (1) imzosiz URL ruxsat etilgan referer bilan ham rad etiladimi
(token auth), (2) imzolangan URL ishlaydimi va master ichidagi NISBIY
sifat-playlist ham ochiladimi (pleyer yo'li), (3) yot referer bloklanadimi
(hotlink), (4) referersiz so'rov holati (mobil/native pleyer ta'siri —
axborot). docs/ops/bunny.md ga qarang.

Har qatlam ALOHIDA o'lchanadi: (1) referersiz yuborilsa, "Block Direct URL File
Access" (referer bloki) ham 403 beradi va token auth o'chiqligini yashiradi —
2026-11-18 prod'da aynan shunday bo'ldi (token auth o'chiq, buyruq "toza" dedi).
"""

from urllib.parse import urljoin

import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from drama import bunny_stream

TIMEOUT = 10
EVIL_REFERER = "https://evil.example/"


class Command(BaseCommand):
    help = "Bunny CDN xavfsizlik sozlamalarini jonli tekshiradi (token auth + referer)."

    def add_arguments(self, parser):
        parser.add_argument("video_id", help="Mavjud Bunny video GUID (jonli tekshiruv shu bilan)")
        parser.add_argument(
            "--referer",
            default="https://dramauz.com/",
            help="Ruxsat etilgan referer (default: https://dramauz.com/)",
        )
        parser.add_argument(
            "--strict", action="store_true", help="Muammo topilsa exit 1 (CI/cron uchun)"
        )

    def handle(self, *args, **options):
        if not bunny_stream.is_configured():
            raise CommandError("BUNNY_STREAM_CDN_HOSTNAME/LIBRARY_ID sozlanmagan.")
        video_id = options["video_id"]
        problems: list[str] = []

        unsigned = f"https://{settings.BUNNY_STREAM_CDN_HOSTNAME}/{video_id}/playlist.m3u8"
        signed = bunny_stream.hls_url(video_id)

        # 1) Token auth: imzosiz URL rad etilishi SHART — RUXSAT ETILGAN referer
        #    bilan, aks holda referer-blok 403'i token auth o'rniga o'lchanadi
        status = self._status(unsigned, referer=options["referer"])
        if status == 200:
            problems.append(
                "Imzosiz URL ruxsat etilgan referer bilan 200 qaytardi — panelda 'CDN token "
                "authentication' YOQILMAGAN (GUID'ni bilgan har kim Referer'ni soxtalab "
                "videoni muddatsiz ko'radi/yuklab oladi)."
            )
        else:
            self._ok(f"imzosiz URL rad etildi ({status})")

        # 2) Imzolangan URL ishlashi kerak
        if not settings.BUNNY_STREAM_TOKEN_KEY:
            problems.append("BUNNY_STREAM_TOKEN_KEY .env'da yo'q — URL'lar imzolanmayapti.")
        else:
            status = self._status(signed, referer=options["referer"])
            if status == 200:
                self._ok("imzolangan URL ishlaydi (200)")
                self._check_variant(signed, options["referer"], problems)
            else:
                problems.append(
                    f"Imzolangan URL {status} qaytardi — kalit panel kaliti bilan mos emas "
                    "yoki video mavjud emas."
                )

        # 3) Hotlink: token to'g'ri bo'lsa ham yot referer bloklanishi kerak
        status = self._status(signed, referer=EVIL_REFERER)
        if status == 200:
            problems.append(
                "Yot referer bilan 200 — panelda 'Allowed Referrers' cheklanmagan "
                "(boshqa sayt videoni embed qila oladi)."
            )
        else:
            self._ok(f"yot referer bloklandi ({status})")

        # 4) Referersiz (mobil/native pleyer) — axborot, muammo emas
        status = self._status(signed)
        if status == 200:
            self._ok("referersiz so'rov ishlaydi (mobil/native pleyer OK)")
        else:
            self.stdout.write(
                self.style.WARNING(
                    f"  ! referersiz so'rov {status} — 'Block Direct URL File Access' (pull "
                    "zone'da 'Block no-referrer requests') yoqilganga o'xshaydi; mobil "
                    "ilova/native pleyer video ololmaydi. O'chirishdan OLDIN token auth "
                    "yoqilganini tasdiqlang (docs/ops/bunny.md)."
                )
            )

        if problems:
            self.stdout.write(self.style.ERROR("MUAMMOLAR:"))
            for problem in problems:
                self.stdout.write(self.style.ERROR(f"  - {problem}"))
            if options["strict"]:
                raise CommandError(f"{len(problems)} ta xavfsizlik muammosi topildi.")
        else:
            self.stdout.write(self.style.SUCCESS("Barcha tekshiruvlar toza."))

    def _check_variant(self, master_url: str, referer: str, problems: list[str]) -> None:
        """Pleyer yo'li: master ichidagi NISBIY sifat-playlist ham imzo bilan ochilishi SHART.

        2026-11-19: master 200 edi, buyruq "toza" dedi, lekin pleyer 720p/video.m3u8'ni
        query'siz qurib 403 oldi (token query'da edi). Pleyer kabi urljoin qilamiz.
        """
        try:
            with requests.get(master_url, headers={"Referer": referer}, timeout=TIMEOUT) as resp:
                body = resp.text
        except requests.RequestException as exc:
            raise CommandError(f"CDN'ga ulanib bo'lmadi: {exc}") from exc
        variant = next(
            (ln.strip() for ln in body.splitlines() if ln.strip() and not ln.startswith("#")),
            None,
        )
        if variant is None:
            self.stdout.write(self.style.WARNING("  ! master'da sifat-playlist topilmadi"))
            return
        status = self._status(urljoin(master_url, variant), referer=referer)
        if status == 200:
            self._ok(f"pleyer yo'li: nisbiy sifat-playlist ({variant}) ham ochiladi (200)")
        else:
            problems.append(
                f"Master ochildi, lekin ichidagi sifat-playlist ({variant}) {status} qaytardi — "
                "pleyer video ko'rsatmaydi (token nisbiy URL'larga o'tmayapti)."
            )

    def _status(self, url: str, referer: str | None = None) -> int:
        headers = {"Referer": referer} if referer else {}
        try:
            with requests.get(url, headers=headers, timeout=TIMEOUT, stream=True) as resp:
                return resp.status_code
        except requests.RequestException as exc:
            raise CommandError(f"CDN'ga ulanib bo'lmadi: {exc}") from exc

    def _ok(self, message: str) -> None:
        self.stdout.write(self.style.SUCCESS(f"  + {message}"))
