"""`compilemessages` o'rnini bosuvchi sof-Python kompilyator (.po -> .mo) [V2G-T1].

`compilemessages` GNU `msgfmt` binariga tayanadi — Windows dev-muhitida ham,
`python:3.12-slim` prod image'ida ham u YO'Q. Bu buyruq MO binar formatini
`struct` bilan yozadi (qarang: core/i18n_catalog.compile_mo).

    python manage.py pocompile
    python manage.py pocompile --locale en

.mo fayllar repo'ga COMMIT QILINADI: build bosqichida gettext bo'lmagani uchun
ularni image ichida qayta qurish imkoni yo'q. Drift'ni `core/test_i18n.py`
ushlaydi — u .po dan qayta kompilyatsiya qilib, diskdagi .mo bilan solishtiradi.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.i18n_catalog import compile_mo, parse_po


class Command(BaseCommand):
    help = "locale/*/LC_MESSAGES/django.po fayllarini .mo ga kompilyatsiya qiladi."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--locale",
            "-l",
            action="append",
            dest="locales",
            help="Til kodi (bir necha marta berilishi mumkin). Standart: barchasi.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Yozmaydi — diskdagi .mo .po bilan mos emasligini 1 kod bilan bildiradi.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        locale_root = Path(settings.LOCALE_PATHS[0])
        if not locale_root.is_dir():
            raise CommandError(f"Katalog papkasi yo'q: {locale_root}")

        locales: list[str] = options.get("locales") or sorted(
            p.name for p in locale_root.iterdir() if (p / "LC_MESSAGES").is_dir()
        )
        if not locales:
            raise CommandError(f"{locale_root} ichida hech qanday til topilmadi.")

        drifted = False
        for locale in locales:
            po_path = locale_root / locale / "LC_MESSAGES" / "django.po"
            mo_path = po_path.with_suffix(".mo")
            if not po_path.exists():
                raise CommandError(f"Topilmadi: {po_path}")

            entries = parse_po(po_path.read_text(encoding="utf-8"))
            blob = compile_mo(entries)
            translated = sum(1 for e in entries if e.msgid and e.translated)

            if options["check"]:
                current = mo_path.read_bytes() if mo_path.exists() else b""
                if current != blob:
                    drifted = True
                    self.stderr.write(
                        self.style.ERROR(
                            f"{locale}: .mo .po bilan mos EMAS (qayta kompilyatsiya kerak)"
                        )
                    )
                else:
                    self.stdout.write(self.style.SUCCESS(f"{locale}: .mo yangi"))
                continue

            mo_path.write_bytes(blob)
            self.stdout.write(
                self.style.SUCCESS(f"{mo_path.name} <- {translated} ta tarjima ({len(blob)} bayt)")
            )

        if drifted:
            raise CommandError("Eskirgan .mo — `manage.py pocompile` ni ishlating.")
