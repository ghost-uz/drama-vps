"""`makemessages` o'rnini bosuvchi sof-Python ekstraktor [V2G-T1].

Django'ning `makemessages` buyrug'i `xgettext`/`msguniq`/`msgmerge` binarlarini
talab qiladi — ular bu loyihaning Windows dev-muhitida ham, `python:3.12-slim`
prod image'ida ham YO'Q. Bu buyruq o'sha zanjirni stdlib bilan bajaradi
(qarang: core/i18n_catalog.py).

    python manage.py pomessages              # settings.LANGUAGES (manba tildan tashqari)
    python manage.py pomessages --locale en
    python manage.py pomessages --check      # CI: katalog manbadan orqada qolganmi?

`--check` HECH NARSA YOZMAYDI: yangi/yo'qolgan string topilsa 1 kod bilan
chiqadi. Shu bilan "yangi shablon qo'shildi, tarjima unutildi" holati sezilmay
qolmaydi.
"""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from core.i18n_catalog import (
    Entry,
    apply_existing,
    extract_python,
    extract_template,
    format_po,
    iter_source_files,
    merge_extracted,
    parse_po,
)

# Ekstrakt qamrovi. `env/`, `node_modules/`, `staticfiles/` ATAYLAB yo'q.
TEMPLATE_DIRS = ["templates"]
PYTHON_DIRS = ["core", "drama", "users", "billing", "funding", "config"]

_HEADER = """# drama.uz tarjima katalogi — {locale}
#
# BU FAYL `manage.py pomessages` TOMONIDAN YANGILANADI (gettext binarlari
# shart emas). Faqat `msgstr` qatorlarini tahrirlang; `msgid` manba kodidan
# keladi. Tarjimadan keyin `manage.py pocompile` bilan .mo quring.
#
msgid ""
msgstr ""
"Project-Id-Version: drama.uz\\n"
"Report-Msgid-Bugs-To: \\n"
"POT-Creation-Date: {created}\\n"
"Language: {locale}\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Plural-Forms: nplurals=2; plural=(n != 1);\\n"
"""


class Command(BaseCommand):
    help = "Shablon/Python manbalaridan tarjima stringlarini .po fayllarga chiqaradi."

    def add_arguments(self, parser: Any) -> None:
        parser.add_argument(
            "--locale",
            "-l",
            action="append",
            dest="locales",
            help="Til kodi (bir necha marta berilishi mumkin). Standart: LANGUAGES.",
        )
        parser.add_argument(
            "--check",
            action="store_true",
            help="Yozmaydi — katalog manbadan orqada qolgan bo'lsa 1 kod bilan chiqadi.",
        )

    def handle(self, *args: Any, **options: Any) -> None:
        base = Path(settings.BASE_DIR)
        locale_root = Path(settings.LOCALE_PATHS[0])
        locales: list[str] = options.get("locales") or [
            code for code, _ in settings.LANGUAGES if code != settings.LANGUAGE_CODE
        ]
        if not locales:
            raise CommandError("Ekstrakt uchun til yo'q (LANGUAGES ni tekshiring).")

        fresh_template = self._extract(base)
        self.stdout.write(f"Ekstrakt: {len(fresh_template)} ta noyob string")

        stale = False
        for locale in locales:
            po_path = locale_root / locale / "LC_MESSAGES" / "django.po"
            # Har til uchun yangi nusxa — apply_existing yozuvlarni O'ZGARTIRADI
            fresh = [self._clone(e) for e in fresh_template]
            existing = parse_po(po_path.read_text(encoding="utf-8")) if po_path.exists() else []
            entries, obsolete = apply_existing(fresh, [e for e in existing if e.msgid])

            if options["check"]:
                added = [e for e in entries if not e.translated]
                if added or obsolete:
                    stale = True
                    self.stderr.write(
                        self.style.ERROR(
                            f"{locale}: {len(added)} ta tarjimasiz, "
                            f"{len(obsolete)} ta eskirgan string"
                        )
                    )
                    for e in added[:20]:
                        self.stderr.write(f"    + {e.msgid[:70]!r}")
                else:
                    self.stdout.write(self.style.SUCCESS(f"{locale}: katalog to'liq"))
                continue

            header = _HEADER.format(
                locale=locale,
                created=dt.datetime.now(dt.UTC).strftime("%Y-%m-%d %H:%M+0000"),
            )
            po_path.parent.mkdir(parents=True, exist_ok=True)
            po_path.write_text(format_po(entries + obsolete, header), encoding="utf-8")
            done = sum(1 for e in entries if e.translated)
            self.stdout.write(
                self.style.SUCCESS(
                    f"{po_path.relative_to(base)}: {done}/{len(entries)} tarjima qilingan"
                    + (f", {len(obsolete)} eskirgan" if obsolete else "")
                )
            )

        if stale:
            raise CommandError("Katalog manbadan orqada — `manage.py pomessages` ni ishlating.")

    def _extract(self, base: Path) -> list[Entry]:
        found = iter_source_files(
            [base / d for d in TEMPLATE_DIRS],
            [base / d for d in PYTHON_DIRS],
        )
        collected: list[Entry] = []
        for path, kind in found:
            source = path.read_text(encoding="utf-8")
            origin = path.relative_to(base).as_posix()
            if kind == "template":
                collected += extract_template(source, origin)
            else:
                collected += extract_python(source, origin)
        return merge_extracted(collected)

    @staticmethod
    def _clone(e: Entry) -> Entry:
        return Entry(
            msgid=e.msgid,
            msgstr=list(e.msgstr),
            msgid_plural=e.msgid_plural,
            msgctxt=e.msgctxt,
            comments=list(e.comments),
            references=list(e.references),
            flags=list(e.flags),
        )
