"""Sof-Python gettext katalog vositalari (.po parse/yozish, .mo kompilyatsiya) [V2G-T1].

NEGA MAVJUD
-----------
Django'ning `makemessages`/`compilemessages` buyruqlari GNU gettext BINARLARIGA
tayanadi (`xgettext`, `msguniq`, `msgmerge`, `msgfmt`). Bu loyihaning dev-muhiti
Windows — u yerda gettext yo'q va uni o'rnatish har bir ishlab chiquvchi uchun
qo'lda qadam bo'lardi. Prod image (`python:3.12-slim`) ham gettext'siz.

Shuning uchun katalog zanjiri stdlib bilan qayta quriladi:
  * ekstrakt — Django'ning O'Z `templatize()` funksiyasi shablonni xgettext
    tushunadigan psevdo-Python'ga aylantiradi; uni `tokenize` bilan o'qiymiz.
    Ya'ni `{% trans %}` / `{% blocktrans %}` semantikasi Django bilan 1:1 —
    biz uni qayta ixtiro qilmaymiz.
  * .py fayllar — `ast` bilan (gettext chaqiruvlari, faqat literal argumentlar).
  * .mo — GNU MO binar formati (`struct`), msgfmt bilan bir xil qoidalar:
    tarjimasiz va `fuzzy` yozuvlar TASHLANADI (aks holda bo'sh satr qaytib,
    msgid'ga fallback ishlamay qolardi).

Bu modul Django'ga deyarli bog'liq emas (faqat `templatize`) va toza testlanadi.
"""

from __future__ import annotations

import ast
import io
import re
import struct
import tokenize
from dataclasses import dataclass, field
from pathlib import Path

# gettext oilasidagi chaqiruvlar:
#   nom -> (msgid arg indeksi, msgid_plural indeksi yoki None, msgctxt indeksi yoki None)
_PY_FUNCS: dict[str, tuple[int, int | None, int | None]] = {
    "gettext": (0, None, None),
    "gettext_lazy": (0, None, None),
    "gettext_noop": (0, None, None),
    "_": (0, None, None),
    "ngettext": (0, 1, None),
    "ngettext_lazy": (0, 1, None),
    "pgettext": (1, None, 0),
    "pgettext_lazy": (1, None, 0),
    "npgettext": (1, 2, 0),
    "npgettext_lazy": (1, 2, 0),
}

# templatize() chiqarishidagi chaqiruvlar (Django faqat shu 4 tasini yozadi)
_TPL_FUNCS = {"gettext", "ngettext", "pgettext", "npgettext"}

_ESCAPES = {
    "n": "\n",
    "t": "\t",
    "r": "\r",
    "a": "\a",
    "b": "\b",
    "f": "\f",
    "v": "\v",
    '"': '"',
    "\\": "\\",
    "'": "'",
}


@dataclass
class Entry:
    """Bitta katalog yozuvi (PO `msgid`/`msgstr` bloki)."""

    msgid: str
    msgstr: list[str] = field(default_factory=lambda: [""])
    msgid_plural: str | None = None
    msgctxt: str | None = None
    comments: list[str] = field(default_factory=list)  # `#.` ekstrakt izohlari
    references: list[str] = field(default_factory=list)  # `#:` manba havolalari
    flags: list[str] = field(default_factory=list)  # `#,` bayroqlar (fuzzy, python-format)
    obsolete: bool = False

    @property
    def key(self) -> tuple[str | None, str]:
        """Katalogdagi yagona kalit — kontekst + msgid."""
        return (self.msgctxt, self.msgid)

    @property
    def translated(self) -> bool:
        """Tarjima qilinganmi (kamida bitta bo'sh bo'lmagan msgstr)."""
        return any(s for s in self.msgstr)


# ---------------------------------------------------------------------------
# PO o'qish / yozish
# ---------------------------------------------------------------------------
def po_unescape(raw: str) -> str:
    """C-uslubidagi PO qochish ketma-ketliklarini yechadi (\\n, \\", \\\\, oktal, \\xHH)."""
    out: list[str] = []
    i = 0
    while i < len(raw):
        ch = raw[i]
        if ch != "\\":
            out.append(ch)
            i += 1
            continue
        i += 1
        if i >= len(raw):
            out.append("\\")
            break
        nxt = raw[i]
        if nxt in _ESCAPES:
            out.append(_ESCAPES[nxt])
            i += 1
        elif nxt == "x":
            m = re.match(r"x([0-9a-fA-F]{1,2})", raw[i:])
            if m:
                out.append(chr(int(m.group(1), 16)))
                i += len(m.group(0))
            else:
                out.append(nxt)
                i += 1
        elif nxt.isdigit():
            m = re.match(r"([0-7]{1,3})", raw[i:])
            if m:
                out.append(chr(int(m.group(1), 8)))
                i += len(m.group(1))
            else:
                out.append(nxt)
                i += 1
        else:
            out.append(nxt)
            i += 1
    return "".join(out)


def po_escape(value: str) -> str:
    """Satrni PO qo'shtirnoqli literali ichiga mos holga keltiradi."""
    out = value.replace("\\", "\\\\").replace('"', '\\"')
    out = out.replace("\t", "\\t").replace("\r", "\\r")
    return out.replace("\n", "\\n")


def _po_string(prefix: str, value: str) -> list[str]:
    """`msgid "..."` satrini chiqaradi; ko'p qatorli matnni gettext uslubida bo'ladi."""
    if "\n" not in value:
        return [f'{prefix} "{po_escape(value)}"']
    parts = value.split("\n")
    lines = [f'{prefix} ""']
    for idx, part in enumerate(parts):
        if idx < len(parts) - 1:
            lines.append(f'"{po_escape(part)}\\n"')
        elif part:
            lines.append(f'"{po_escape(part)}"')
    return lines


def parse_po(text: str) -> list[Entry]:
    """PO matnini `Entry` ro'yxatiga aylantiradi (metadata `msgid ""` ham kiradi)."""
    entries: list[Entry] = []
    comments: list[str] = []
    references: list[str] = []
    flags: list[str] = []
    fields: dict[str, str] = {}
    msgstrs: dict[int, str] = {}
    obsolete = False
    target: str | None = None
    plural_index = 0

    def flush() -> None:
        nonlocal comments, references, flags, fields, msgstrs, obsolete, target, plural_index
        if "msgid" in fields:
            top = max(msgstrs) if msgstrs else 0
            entries.append(
                Entry(
                    msgid=fields["msgid"],
                    msgstr=[msgstrs.get(i, "") for i in range(top + 1)],
                    msgid_plural=fields.get("msgid_plural"),
                    msgctxt=fields.get("msgctxt"),
                    comments=comments,
                    references=references,
                    flags=flags,
                    obsolete=obsolete,
                )
            )
        comments, references, flags = [], [], []
        fields, msgstrs = {}, {}
        obsolete = False
        target = None
        plural_index = 0

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            flush()
            continue
        if line.startswith("#~"):
            obsolete = True
            line = line[2:].strip()
            if not line:
                continue
        if line.startswith("#."):
            comments.append(line[2:].strip())
            continue
        if line.startswith("#:"):
            references.extend(line[2:].split())
            continue
        if line.startswith("#,"):
            flags.extend(f.strip() for f in line[2:].split(",") if f.strip())
            continue
        if line.startswith("#"):
            continue

        m = re.match(r'^(msgctxt|msgid_plural|msgid|msgstr(?:\[(\d+)\])?)\s+"(.*)"$', line)
        if m:
            keyword, idx, value = m.group(1), m.group(2), po_unescape(m.group(3))
            if keyword.startswith("msgstr"):
                plural_index = int(idx) if idx is not None else 0
                msgstrs[plural_index] = value
                target = "msgstr"
            else:
                fields[keyword] = value
                target = keyword
            continue

        if line.startswith('"') and line.endswith('"') and target:
            value = po_unescape(line[1:-1])
            if target == "msgstr":
                msgstrs[plural_index] = msgstrs.get(plural_index, "") + value
            else:
                fields[target] = fields.get(target, "") + value

    flush()
    return entries


def format_po(entries: list[Entry], header: str) -> str:
    """`Entry` ro'yxatidan to'liq PO fayl matnini quradi."""
    out: list[str] = [header.rstrip("\n"), ""]
    for e in entries:
        for c in e.comments:
            out.append(f"#. {c}")
        line = "#:"
        for ref in e.references:
            if line != "#:" and len(line) + len(ref) + 1 > 78:
                out.append(line)
                line = "#:"
            line += f" {ref}"
        if line != "#:":
            out.append(line)
        if e.flags:
            out.append("#, " + ", ".join(e.flags))
        if e.msgctxt is not None:
            out.extend(_po_string("msgctxt", e.msgctxt))
        out.extend(_po_string("msgid", e.msgid))
        if e.msgid_plural is not None:
            out.extend(_po_string("msgid_plural", e.msgid_plural))
            for i, s in enumerate(e.msgstr):
                out.extend(_po_string(f"msgstr[{i}]", s))
        else:
            out.extend(_po_string("msgstr", e.msgstr[0] if e.msgstr else ""))
        out.append("")
    return "\n".join(out) + "\n"


# ---------------------------------------------------------------------------
# MO kompilyatsiya
# ---------------------------------------------------------------------------
MO_MAGIC = 0x950412DE


def compile_mo(entries: list[Entry]) -> bytes:
    """Katalogni GNU MO binar formatiga o'giradi (msgfmt bilan bir xil qoidalar).

    TASHLANADI: eskirgan (`#~`), `fuzzy` bayroqli va tarjimasiz yozuvlar.
    Oxirgisi MUHIM — bo'sh `msgstr` MO'ga tushsa, gettext uni haqiqiy tarjima
    deb qabul qilib BO'SH SATR qaytaradi va msgid'ga fallback yo'qoladi.
    """
    items: dict[bytes, bytes] = {}
    for e in entries:
        if e.obsolete or "fuzzy" in e.flags:
            continue
        if e.msgid == "":  # metadata bloki — har doim kiradi
            items[b""] = (e.msgstr[0] if e.msgstr else "").encode("utf-8")
            continue
        if not e.translated:
            continue
        key = e.msgid
        if e.msgctxt is not None:
            key = f"{e.msgctxt}\x04{key}"
        if e.msgid_plural is not None:
            key = f"{key}\x00{e.msgid_plural}"
            value = "\x00".join(e.msgstr)
        else:
            value = e.msgstr[0]
        items[key.encode("utf-8")] = value.encode("utf-8")

    keys = sorted(items)  # MO spetsifikatsiyasi: kalitlar bayt bo'yicha saralangan
    n = len(keys)
    orig_table_offset = 7 * 4  # 7 ta uint32 sarlavha
    trans_table_offset = orig_table_offset + n * 8
    data_offset = trans_table_offset + n * 8

    orig_table: list[tuple[int, int]] = []
    trans_table: list[tuple[int, int]] = []
    blob = bytearray()
    for k in keys:
        orig_table.append((len(k), data_offset + len(blob)))
        blob += k + b"\x00"
    for k in keys:
        v = items[k]
        trans_table.append((len(v), data_offset + len(blob)))
        blob += v + b"\x00"

    out = bytearray()
    # hash-jadval o'lchami 0 -> gettext binar qidiruvga tushadi (to'liq qonuniy)
    out += struct.pack(
        "<7I",
        MO_MAGIC,
        0,
        n,
        orig_table_offset,
        trans_table_offset,
        0,
        data_offset + len(blob),
    )
    for length, offset in orig_table:
        out += struct.pack("<2I", length, offset)
    for length, offset in trans_table:
        out += struct.pack("<2I", length, offset)
    out += blob
    return bytes(out)


# ---------------------------------------------------------------------------
# Ekstrakt
# ---------------------------------------------------------------------------
def extract_template(source: str, origin: str) -> list[Entry]:
    """Django shablonidan tarjima yozuvlarini oladi.

    Django `templatize()` shablonni xgettext uchun psevdo-Python'ga aylantiradi
    (tarjima qilinmaydigan qismlar bir xil uzunlikdagi to'ldirgichga almashadi —
    shuning uchun QATOR RAQAMLARI saqlanadi). Biz o'sha chiqishni tokenlaymiz.
    """
    from django.utils.translation.template import templatize

    return _extract_pseudo_python(templatize(source), origin)


def _extract_pseudo_python(code: str, origin: str) -> list[Entry]:
    entries: list[Entry] = []
    # ⚠️ templatize() chiqishi HAQIQIY Python emas: u faqat qator/ustun
    # o'rinlarini saqlaydigan to'ldirgich matn. `tokenize` esa (xgettext'ning C
    # lekserlaridan farqli) INDENTATSIYA izchilligini talab qiladi va real
    # shablonlarda IndentationError beradi. Psevdo-kodda blok tuzilmasi yo'q
    # (`if:`/`def:` chiqmaydi), shuning uchun har qatorning old bo'shlig'ini
    # olib tashlaymiz — QATOR RAQAMLARI o'zgarmaydi, faqat ustun siljiydi
    # (biz ustunni ishlatmaymiz).
    flat = "\n".join(line.lstrip() for line in code.splitlines())
    tokens = list(tokenize.generate_tokens(io.StringIO(flat).readline))
    pending_comments: list[str] = []

    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.type == tokenize.COMMENT:
            text = tok.string.lstrip("#").strip()
            if text.lower().startswith("translators:"):
                pending_comments.append(text)
            i += 1
            continue
        if tok.type == tokenize.NAME and tok.string in _TPL_FUNCS:
            nxt = tokens[i + 1] if i + 1 < len(tokens) else None
            if nxt is not None and nxt.type == tokenize.OP and nxt.string == "(":
                args, i = _read_string_args(tokens, i + 2)
                entry = _entry_from_args(tok.string, args, f"{origin}:{tok.start[0]}")
                if entry is not None:
                    entry.comments = list(pending_comments)
                    entries.append(entry)
                pending_comments = []
                continue
        if tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT):
            pending_comments = []
        i += 1
    return entries


def _read_string_args(tokens: list[tokenize.TokenInfo], start: int) -> tuple[list[str | None], int]:
    """`(` dan keyingi argumentlarni o'qiydi; literal bo'lmaganini None qiladi."""
    args: list[str | None] = []
    depth = 1
    current: list[str] = []
    literal = True
    i = start
    while i < len(tokens) and depth > 0:
        tok = tokens[i]
        if tok.type == tokenize.OP:
            if tok.string in "([{":
                depth += 1
            elif tok.string in ")]}":
                depth -= 1
                if depth == 0:
                    args.append("".join(current) if literal and current else None)
                    i += 1
                    break
            elif tok.string == "," and depth == 1:
                args.append("".join(current) if literal and current else None)
                current, literal = [], True
                i += 1
                continue
        if tok.type == tokenize.STRING:
            try:
                current.append(str(ast.literal_eval(tok.string)))
            except (ValueError, SyntaxError):  # pragma: no cover
                literal = False
        elif tok.type not in (tokenize.NL, tokenize.NEWLINE, tokenize.COMMENT):
            literal = False
        i += 1
    return args, i


def _entry_from_args(func: str, args: list[str | None], reference: str) -> Entry | None:
    spec = _PY_FUNCS.get(func)
    if spec is None:
        return None
    msgid_idx, plural_idx, ctxt_idx = spec

    def get(idx: int | None) -> str | None:
        if idx is None or idx >= len(args):
            return None
        return args[idx]

    msgid = get(msgid_idx)
    if not msgid:
        return None
    plural = get(plural_idx)
    return Entry(
        msgid=msgid,
        msgid_plural=plural,
        msgctxt=get(ctxt_idx),
        msgstr=["", ""] if plural else [""],
        references=[reference],
    )


def extract_python(source: str, origin: str) -> list[Entry]:
    """Python manbasidan gettext chaqiruvlarini oladi (faqat literal argumentlar)."""
    entries: list[Entry] = []
    try:
        tree = ast.parse(source)
    except SyntaxError:  # pragma: no cover
        return entries
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            name: str | None = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        else:
            name = None
        if name is None or name not in _PY_FUNCS:
            continue
        args: list[str | None] = [
            a.value if isinstance(a, ast.Constant) and isinstance(a.value, str) else None
            for a in node.args
        ]
        entry = _entry_from_args(name, args, f"{origin}:{node.lineno}")
        if entry is not None:
            entries.append(entry)
    return entries


def merge_extracted(extracted: list[Entry]) -> list[Entry]:
    """Bir xil kalitli yozuvlarni birlashtiradi (havolalar/izohlar to'planadi)."""
    merged: dict[tuple[str | None, str], Entry] = {}
    for e in extracted:
        existing = merged.get(e.key)
        if existing is None:
            merged[e.key] = e
            continue
        for ref in e.references:
            if ref not in existing.references:
                existing.references.append(ref)
        for c in e.comments:
            if c not in existing.comments:
                existing.comments.append(c)
        if e.msgid_plural and not existing.msgid_plural:
            existing.msgid_plural = e.msgid_plural
            existing.msgstr = ["", ""]
    return list(merged.values())


def apply_existing(fresh: list[Entry], existing: list[Entry]) -> tuple[list[Entry], list[Entry]]:
    """Mavjud tarjimalarni yangi ekstraktga ko'chiradi.

    Qaytaradi: (yangilangan yozuvlar, endi manbada YO'Q eskirgan yozuvlar).
    Eskirganlar o'chirilmaydi — `#~` bilan saqlanadi, chunki string qaytib
    kelishi mumkin va tarjima mehnati bekorga ketmasin.
    """
    by_key = {e.key: e for e in existing}
    for entry in fresh:
        old = by_key.pop(entry.key, None)
        if old is None or not old.translated:
            continue
        if entry.msgid_plural and len(old.msgstr) >= 2:
            entry.msgstr = list(old.msgstr)
        elif not entry.msgid_plural:
            entry.msgstr = [old.msgstr[0]]
        else:
            entry.msgstr = [old.msgstr[0], old.msgstr[0]]
        entry.flags = [f for f in old.flags if f != "fuzzy"]
    obsolete = [e for e in by_key.values() if e.msgid and e.translated]
    for e in obsolete:
        e.obsolete = True
        e.references = []
    return fresh, obsolete


def iter_source_files(template_dirs: list[Path], python_dirs: list[Path]) -> list[tuple[Path, str]]:
    """Ekstrakt uchun fayllarni to'playdi -> [(yo'l, 'template'|'python')]."""
    found: list[tuple[Path, str]] = []
    for d in template_dirs:
        if not d.is_dir():
            continue
        for pattern in ("*.html", "*.txt"):
            found += [(p, "template") for p in sorted(d.rglob(pattern))]
    for d in python_dirs:
        if not d.is_dir():
            continue
        found += [
            (p, "python")
            for p in sorted(d.rglob("*.py"))
            if "migrations" not in p.parts and not p.name.startswith("test_")
        ]
    return found
