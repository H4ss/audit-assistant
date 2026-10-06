"""Import Markdown par profil déclaré.

Profils pris en charge (chacun validé sur un exemple, aucun support universel) :

* `heading-kv-v1` : une section `## <ID> · <titre>` par finding, des puces
  `- **Clé**: valeur`, des sous-sections `###` (Description, Evidence...).
* `table-v1` : un ou plusieurs tableaux Markdown, une ligne par finding.

Chaque enregistrement conserve son emplacement (lignes et offsets). Tout
contenu non reconnu est signalé : l'import n'est alors pas présenté comme
complet. Le contenu est une donnée non fiable, jamais une instruction.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from paladin.importers.mapping import guess_key
from paladin.importers.records import RawRecord, SourceRead, UnrecognizedPart

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
_KV_BULLET_RE = re.compile(r"^\s*[-*]\s+(?:\*\*|__)?(?P<key>[^:*_]+?)(?:\*\*|__)?\s*:\s*(?P<value>.*?)\s*$")
_INLINE_KV_RE = re.compile(r"(?P<key>[A-Za-zÀ-ÿ][\w À-ÿ]{0,30}?)\s*:\s*(?P<value>[^·|]+)")
_DEFAULT_ID_PATTERN = r"^(?P<id>[A-Za-z][A-Za-z0-9]*[-_]\d+)\s*[·\-—:|]\s*(?P<title>.+)$"

PROFILES = ("heading-kv-v1", "table-v1")


@dataclass
class _Line:
    no: int  # 1-based
    offset: int
    text: str


@dataclass
class _Section:
    level: int
    title: str
    start: _Line
    lines: list[_Line] = field(default_factory=list)

    @property
    def end_no(self) -> int:
        return self.lines[-1].no if self.lines else self.start.no

    def body(self) -> str:
        return "\n".join(ln.text for ln in self.lines).strip()


class MarkdownProfileError(ValueError):
    pass


def _lines(text: str) -> list[_Line]:
    out, offset = [], 0
    for i, raw in enumerate(text.splitlines(keepends=True), start=1):
        out.append(_Line(i, offset, raw.rstrip("\r\n")))
        offset += len(raw)
    return out


def _strip_html_comments(lines: list[_Line]) -> list[_Line]:
    out, in_comment = [], False
    for ln in lines:
        t = ln.text
        if in_comment:
            if "-->" in t:
                in_comment = False
            continue
        if t.strip().startswith("<!--"):
            in_comment = "-->" not in t
            continue
        out.append(ln)
    return out


def _sections(lines: list[_Line]) -> tuple[list[_Line], list[_Section]]:
    """Découpe en sections par titre, en ignorant les titres dans les blocs de code."""
    preamble: list[_Line] = []
    sections: list[_Section] = []
    in_fence = False
    for ln in lines:
        if ln.text.lstrip().startswith(("```", "~~~")):
            in_fence = not in_fence
        m = None if in_fence else _HEADING_RE.match(ln.text)
        if m:
            sections.append(_Section(len(m.group(1)), m.group(2).strip(), ln))
        elif sections:
            sections[-1].lines.append(ln)
        else:
            preamble.append(ln)
    return preamble, sections


def _kv_bullets(lines: list[_Line]) -> dict[str, str]:
    out: dict[str, str] = {}
    for ln in lines:
        m = _KV_BULLET_RE.match(ln.text)
        if m:
            out[m.group("key").strip()] = m.group("value").strip().strip("`")
    return out


def _document_defaults(kv: dict[str, str]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in kv.items():
        key = guess_key(k)
        if key in ("application_name", "version_name") and v:
            out[key] = v
    return out


def _locator(path: Path, start: _Line, end_no: int, end_offset: int) -> str:
    return f"{path.name}#L{start.no}-L{end_no}@{start.offset}-{end_offset}"


def _end_offset(lines: list[_Line], end_no: int) -> int:
    ln = lines[end_no - 1]
    return ln.offset + len(ln.text)


def read_markdown(path: Path, profile: str, options: dict[str, Any] | None = None) -> SourceRead:
    options = options or {}
    text = path.read_text(encoding="utf-8-sig")
    if profile == "heading-kv-v1":
        return _read_heading_kv(path, text, options)
    if profile == "table-v1":
        return _read_table(path, text, options)
    raise MarkdownProfileError(f"Profil MD inconnu : {profile!r}. Profils disponibles : {', '.join(PROFILES)}")


def _ignored(title: str, options: dict[str, Any]) -> bool:
    return title.strip().lower() in {s.lower() for s in options.get("ignore_sections", [])}


def _read_heading_kv(path: Path, text: str, options: dict[str, Any]) -> SourceRead:
    all_lines = _lines(text)
    preamble, sections = _sections(_strip_html_comments(all_lines))
    finding_level = int(options.get("finding_heading_level", 2))
    id_re = re.compile(options.get("id_pattern", _DEFAULT_ID_PATTERN))
    doc_kv: dict[str, str] = _kv_bullets(preamble)
    for s in sections:
        if s.level < finding_level:
            doc_kv.update(_kv_bullets(s.lines))
    defaults = _document_defaults(doc_kv)

    records: list[RawRecord] = []
    unrecognized: list[UnrecognizedPart] = []
    ignored: list[UnrecognizedPart] = []
    field_names: list[str] = ["ID", "Title"]
    current: dict[str, Any] | None = None

    def close() -> None:
        nonlocal current
        if current is None:
            return
        sec: _Section = current["section"]
        end_no = current["end_no"]
        loc = _locator(path, sec.start, end_no, _end_offset(all_lines, end_no))
        kv = current["kv"]
        if not kv:
            unrecognized.append(UnrecognizedPart(loc, "section de finding sans champs clé/valeur", sec.title[:200]))
        else:
            fields = {"ID": current["id"], "Title": current["title"], **kv}
            for k in kv:
                if k not in field_names:
                    field_names.append(k)
            records.append(RawRecord(fields=fields, locator=loc, defaults=dict(defaults), sections=current["subs"]))
        current = None

    for s in sections:
        if s.level < finding_level:
            close()
            leftover = [ln for ln in s.lines if ln.text.strip() and not _KV_BULLET_RE.match(ln.text)]
            if s.level > 1 and leftover:
                unrecognized.append(UnrecognizedPart(_locator(path, s.start, s.end_no, _end_offset(all_lines, s.end_no)), "section hors profil", s.title))
            continue
        if s.level == finding_level:
            close()
            m = id_re.match(s.title)
            loc = _locator(path, s.start, s.end_no, _end_offset(all_lines, s.end_no))
            if m:
                current = {"section": s, "id": m.group("id"), "title": m.group("title").strip(),
                           "kv": _kv_bullets(s.lines), "subs": {}, "end_no": s.end_no}
            elif _ignored(s.title, options):
                ignored.append(UnrecognizedPart(loc, "section ignorée par le profil", s.title))
            else:
                unrecognized.append(UnrecognizedPart(loc, "titre sans identifiant de finding", s.title))
            continue
        # Sous-section d'un finding.
        if current is not None:
            current["subs"][s.title] = s.body()
            current["end_no"] = s.end_no
        else:
            unrecognized.append(UnrecognizedPart(_locator(path, s.start, s.end_no, _end_offset(all_lines, s.end_no)), "sous-section orpheline", s.title))
    close()
    read = SourceRead(kind="md", records=records, field_names=field_names, unrecognized=unrecognized, ignored=ignored)
    read.scope.update(defaults)
    read.finalize_completeness()
    return read


def _split_row(line: str) -> list[str]:
    inner = line.strip()
    if inner.startswith("|"):
        inner = inner[1:]
    if inner.endswith("|") and not inner.endswith("\\|"):
        inner = inner[:-1]
    cells = re.split(r"(?<!\\)\|", inner)
    return [c.strip().replace("\\|", "|") for c in cells]


_SEP_RE = re.compile(r"^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$")


def _read_table(path: Path, text: str, options: dict[str, Any]) -> SourceRead:
    all_lines = _lines(text)
    lines = _strip_html_comments(all_lines)
    records: list[RawRecord] = []
    unrecognized: list[UnrecognizedPart] = []
    ignored: list[UnrecognizedPart] = []
    field_names: list[str] = []
    defaults: dict[str, Any] = {}
    current_heading = ""
    section_has_table = False
    section_text: list[_Line] = []
    section_start: _Line | None = None
    i = 0

    def flush_section() -> None:
        meaningful = [ln for ln in section_text if ln.text.strip()]
        if section_start is not None and not section_has_table and meaningful:
            loc = _locator(path, section_start, meaningful[-1].no, _end_offset(all_lines, meaningful[-1].no))
            part = UnrecognizedPart(loc, "section sans tableau de findings", current_heading)
            (ignored if _ignored(current_heading, options) else unrecognized).append(part)

    while i < len(lines):
        ln = lines[i]
        m = _HEADING_RE.match(ln.text)
        if m:
            if len(m.group(1)) > 1:
                flush_section()
                current_heading, section_has_table, section_text, section_start = m.group(2).strip(), False, [], ln
            i += 1
            continue
        is_table = ln.text.strip().startswith("|") and i + 1 < len(lines) and _SEP_RE.match(lines[i + 1].text)
        if is_table:
            section_has_table = True
            headers = _split_row(ln.text)
            for h in headers:
                if h and h not in field_names:
                    field_names.append(h)
            j = i + 2
            while j < len(lines) and lines[j].text.strip().startswith("|"):
                row = lines[j]
                cells = _split_row(row.text)
                loc = _locator(path, row, row.no, _end_offset(all_lines, row.no))
                if len(cells) != len(headers):
                    unrecognized.append(UnrecognizedPart(loc, f"ligne de tableau mal formée ({len(cells)} cellules pour {len(headers)} colonnes)", row.text[:200]))
                else:
                    fields = {h: (c if c else None) for h, c in zip(headers, cells, strict=True) if h}
                    records.append(RawRecord(fields=fields, locator=loc, defaults=dict(defaults)))
                j += 1
            i = j
            continue
        if section_start is None:
            # Préambule : métadonnées de document du type « Project: X · Branch: Y ».
            for km in _INLINE_KV_RE.finditer(ln.text):
                key = guess_key(km.group("key"))
                if key in ("application_name", "version_name"):
                    defaults[key] = km.group("value").strip()
        else:
            section_text.append(ln)
        i += 1
    flush_section()
    for r in records:
        r.defaults = {**defaults, **r.defaults}
    read = SourceRead(kind="md", records=records, field_names=field_names, unrecognized=unrecognized, ignored=ignored)
    read.scope.update(defaults)
    read.finalize_completeness()
    return read
