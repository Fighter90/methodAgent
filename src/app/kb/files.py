"""Разбор референсов .docx и .pdf: текст, структура разделов и пересчёт таблиц часов (FR-02, FR-05).

Текст DOCX собирается из абзацев и таблиц тела в исходном порядке (таблицы нужны intake и актуализации,
темы и компетенции учебных программ часто лежат в них). Ошибки в таблицах часов референса показываются
методисту и не переносятся в каркас; защищённый паролем или нечитаемый PDF даёт 400, а не 500.
"""

from __future__ import annotations

import codecs
import io
import logging
import re
from dataclasses import dataclass, field

from app.core.errors import BadRequest
from app.core.uploads import check_type

logger = logging.getLogger(__name__)

_KIND_HEADERS = {'lk': ('лк', 'лекц'), 'pr': ('пр', 'практ'), 'lb': ('лб', 'лаб'), 'srs': ('срс', 'самост')}
_W_NS = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'  # префикс тегов DOCX в Clark-нотации


@dataclass
class ParsedReference:
    name: str
    text: str
    structure: list[str] = field(default_factory=list)
    hours_issues: list[str] = field(default_factory=list)


def detect_format(content: bytes) -> str | None:
    """Тип файла по сигнатуре, а не по расширению."""
    if content.startswith(b'%PDF'):
        return 'pdf'
    if content.startswith(b'PK\x03\x04'):
        return 'docx'
    try:
        # инкрементальный декодер не считает ошибкой букву, разрезанную границей 2000 байт
        codecs.getincrementaldecoder('utf-8')().decode(content[:2000], final=False)
        return 'txt'
    except UnicodeDecodeError:
        return None


def parse_reference(name: str, content: bytes, max_unpacked_mb: int = 100) -> ParsedReference:
    fmt = detect_format(content)
    check_type(name, content, fmt)  # белый список расширений и совпадение расширения с сигнатурой (415)
    if fmt == 'docx':
        return _parse_docx(name, content, max_unpacked_mb)
    if fmt == 'pdf':
        return _parse_pdf(name, content)
    if fmt == 'txt':
        text = content.decode('utf-8', 'ignore')
        return ParsedReference(name=name, text=text, structure=_structure(text.splitlines()))
    raise BadRequest(f'Неподдерживаемый формат файла «{name}»: принимаются .docx, .pdf и текст')


def _parse_docx(name: str, content: bytes, max_unpacked_mb: int) -> ParsedReference:
    import zipfile

    from docx import Document

    try:
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            unpacked = sum(i.file_size for i in zf.infolist())
            if unpacked > max_unpacked_mb * 1024 * 1024:
                raise BadRequest(f'Файл «{name}» после распаковки больше {max_unpacked_mb} МБ')
            if any(i.filename.endswith('vbaProject.bin') for i in zf.infolist()):
                logger.info('В файле %s есть макросы — они не исполняются', name)
        doc = Document(io.BytesIO(content))
        lines = _body_lines(doc)
        tables = doc.tables
    except BadRequest:
        raise
    except Exception as exc:  # noqa: BLE001 — битый файл должен давать понятный 400, а не 500
        raise BadRequest(f'Файл «{name}» повреждён или не является DOCX ({type(exc).__name__})') from exc
    issues: list[str] = []
    for ti, table in enumerate(tables, start=1):
        rows = [[c.text.strip() for c in r.cells] for r in table.rows]
        issues.extend(check_hours_table(rows, ti))
    return ParsedReference(name=name, text='\n'.join(lines), structure=_structure(lines), hours_issues=issues)


def _p_text(p_elm) -> str:
    """Текст абзаца из XML: все w:t-фрагменты подряд (без создания объектов python-docx)."""
    return ''.join(t.text or '' for t in p_elm.iter(_W_NS + 't')).strip()


def _table_lines(tbl_elm) -> list[str]:
    """Строки таблицы: ячейки одной строки через «|»; вложенные таблицы (глубже одного уровня) — отдельными строками."""
    lines: list[str] = []
    for tr in tbl_elm.iterchildren(_W_NS + 'tr'):
        cells: list[str] = []
        nested: list[str] = []
        for tc in tr.iterchildren(_W_NS + 'tc'):
            parts: list[str] = []
            for child in tc.iterchildren():
                if child.tag == _W_NS + 'p':
                    t = _p_text(child)
                    if t:
                        parts.append(t)
                elif child.tag == _W_NS + 'tbl':
                    nested.extend(_table_lines(child))
            if parts:
                cells.append(' '.join(parts))
        if cells:
            lines.append(' | '.join(cells))
        lines.extend(nested)
    return lines


def _body_lines(doc) -> list[str]:
    """Абзацы и таблицы тела документа в исходном порядке (SPEC-KB-22): содержимое таблиц тоже попадает в текст."""
    lines: list[str] = []
    for child in doc.element.body.iterchildren():
        if child.tag == _W_NS + 'p':
            t = _p_text(child)
            if t:
                lines.append(t)
        elif child.tag == _W_NS + 'tbl':
            lines.extend(_table_lines(child))
    return lines


def _parse_pdf(name: str, content: bytes) -> ParsedReference:
    import fitz

    parts: list[str] = []
    issues: list[str] = []
    n_table = 0
    try:
        doc = fitz.open(stream=content, filetype='pdf')
    except Exception as exc:  # noqa: BLE001 — битый PDF должен давать понятный 400, а не 500
        raise BadRequest(f'Файл «{name}» повреждён или не является PDF ({type(exc).__name__})') from exc
    if doc.needs_pass or doc.is_encrypted:  # SPEC-KB-23: fitz.open проходит и для защищённого файла
        doc.close()
        raise BadRequest(f'Файл «{name}» защищён паролем — снимите защиту или загрузите доступную копию')
    try:
        with doc:
            for page in doc.pages(0, min(doc.page_count, 200)):
                parts.append(page.get_text())
                # Таблицы часов в PDF пересчитываются так же, как в .docx (FR-05)
                try:
                    tables = page.find_tables().tables
                except Exception as exc:  # noqa: BLE001 — сторонний разборщик PyMuPDF бросает разные типы на нестандартной вёрстке; текст страницы уже взят
                    logger.debug('pdf %s: таблицы страницы не распознаны (%s)', name, type(exc).__name__)
                    tables = []
                for t in tables:
                    n_table += 1
                    rows = [[(c or '').replace('\n', ' ').strip() for c in r] for r in t.extract()]
                    issues.extend(check_hours_table(rows, n_table))
    except BadRequest:
        raise
    except Exception as exc:  # noqa: BLE001 — ожидаемые ошибки парсера (ValueError, RuntimeError, fitz) дают понятный 400, а не 500
        raise BadRequest(f'Файл «{name}» не удалось прочитать как PDF ({type(exc).__name__})') from exc
    text = '\n'.join(parts)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return ParsedReference(name=name, text=text, structure=_structure(lines), hours_issues=list(dict.fromkeys(issues)))


def _structure(lines: list[str]) -> list[str]:
    """Заголовки разделов вида «1.», «1.2.», «Раздел 1», «Модуль 2», набранные с цифры."""
    out = []
    for ln in lines:
        if len(ln) > 140:
            continue
        if re.match(r'^(\d+(\.\d+)*\.?\s+[А-ЯA-Z]|раздел\s+\d|модуль\s+\d|тема\s+\d)', ln, flags=re.IGNORECASE):
            out.append(ln)
    return out[:80]


def _int(text: str) -> int | None:
    m = re.match(r'^\s*(\d+)\s*$', text)
    return int(m.group(1)) if m else None


def check_hours_table(rows: list[list[str]], table_no: int = 1) -> list[str]:
    """Пересчитывает таблицу часов: строки, темы против модуля, модули против итога."""
    if not rows:
        return []
    header = [h.lower() for h in rows[0]]
    col_total = next((i for i, h in enumerate(header) if 'всего' in h or 'трудо' in h), None)
    cols = {k: next((i for i, h in enumerate(header) if any(h.startswith(p) for p in prefs)), None) for k, prefs in _KIND_HEADERS.items()}
    if col_total is None or sum(v is not None for v in cols.values()) < 3:
        return []
    issues = []
    modules: list[tuple[str, dict[str, int]]] = []
    current_topics: list[dict[str, int]] = []
    current_module: tuple[str, dict[str, int]] | None = None

    def _flush() -> None:
        if current_module and current_topics:
            name, mvals = current_module
            for k in ('total', 'lk', 'pr', 'lb', 'srs'):
                s = sum(t.get(k, 0) for t in current_topics)
                if k in mvals and s != mvals[k]:
                    ru = {'total': 'всего', 'lk': 'ЛК', 'pr': 'ПР', 'lb': 'ЛБ', 'srs': 'СРС'}[k]
                    issues.append(f'Таблица {table_no}, {name}: сумма тем {ru} {s} ч, в строке модуля {mvals[k]} ч')

    for row in rows[1:]:
        if len(row) <= max(col_total, *(v for v in cols.values() if v is not None)):
            continue
        label = row[0].strip()
        total = _int(row[col_total])
        if total is None:
            continue
        vals = {'total': total}
        for k, ci in cols.items():
            if ci is not None:
                v = _int(row[ci])
                vals[k] = v if v is not None else 0
        kinds = sum(vals.get(k, 0) for k in ('lk', 'pr', 'lb', 'srs'))
        low = label.lower()
        is_final = 'аттестац' in low
        is_total = low.startswith('итого') or low.startswith('всего')
        name = row[1].strip()[:40] if len(row) > 1 and row[1].strip() else label
        if is_total:
            _flush()
            sums = {k: sum(m[1].get(k, 0) for m in modules) for k in ('lk', 'pr', 'lb', 'srs')}
            ru = {'lk': 'ЛК', 'pr': 'ПР', 'lb': 'ЛБ', 'srs': 'СРС'}
            for k, s in sums.items():
                if vals.get(k, 0) != s:
                    issues.append(f'Таблица {table_no}, итоговая строка: {ru[k]} {vals.get(k, 0)} ч, по модулям {s} ч')
            continue
        if is_final:
            continue
        if kinds and kinds != total or (not kinds and total and any(vals.get(k) is not None for k in cols)):
            if kinds != total:
                issues.append(f'Таблица {table_no}, «{name}»: по видам работы {kinds} ч, всего {total} ч')
        if re.match(r'^\d+\.?$', label):
            _flush()
            current_module = (f'модуль {label.rstrip(".")}', vals)
            current_topics = []
            modules.append(current_module)
        elif re.match(r'^\d+\.\d+', label):
            current_topics.append(vals)
    _flush()
    return list(dict.fromkeys(issues))
