"""Выгрузка комплекта: DOCX по шаблону АЦР, PPTX, GIFT, Moodle XML, JSON, проект приказа.

Реквизиты (ФИО, номер приказа, подписи) остаются пустыми полями — их заполняет человек (V-16).
"""

from __future__ import annotations

import io
import json
import re
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor
from pptx import Presentation
from pptx.dml.color import RGBColor as PptxRGB
from pptx.util import Inches
from pptx.util import Pt as PptxPt

from app.agent.sections import BLANK, build_sections
from app.core.errors import BadRequest
from app.programs.schemas import ProgramDoc
from app.programs.schemas import ProgramType
from app.validation.rules import SECTION_GROUPS, sections_for

DOCX = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
PPTX = 'application/vnd.openxmlformats-officedocument.presentationml.presentation'
FORMATS = ('docx', 'pptx', 'gift', 'moodle_xml', 'json', 'order_draft', 'lectures_docx')
ACCENT = RGBColor(0x21, 0xA0, 0x38)


def _slug(doc: ProgramDoc) -> str:
    s = re.sub(r'[^\w\-]+', '_', doc.title or doc.id, flags=re.UNICODE).strip('_')
    return (s or doc.id)[:60]


def _base_document() -> Document:
    d = Document()
    st = d.styles['Normal']
    st.font.name = 'Times New Roman'
    st.font.size = Pt(12)
    return d


def _heading(d: Document, text: str, level: int = 1) -> None:
    h = d.add_heading(text, level=level)
    for r in h.runs:
        r.font.color.rgb = ACCENT if level == 1 else RGBColor(0x1F, 0x1F, 0x1F)


def _table(d: Document, header: list[str], rows: list[list[object]]) -> None:
    t = d.add_table(rows=1, cols=len(header))
    t.style = 'Table Grid'
    for i, h in enumerate(header):
        cell = t.rows[0].cells[i]
        cell.text = h
        for r in cell.paragraphs[0].runs:
            r.bold = True
    for row in rows:
        cells = t.add_row().cells
        for i, v in enumerate(row):
            cells[i].text = str(v)


def _curriculum(d: Document, doc: ProgramDoc, with_topics: bool) -> None:
    header = ['№', 'Наименование', 'Всего', 'ЛК', 'ПР', 'ЛБ', 'СРС', 'Форма контроля']
    rows: list[list[object]] = []
    for m in doc.modules:
        h = m.hours
        rows.append([m.n, m.title, h.total, h.lk, h.pr, h.lb, h.srs, m.control])
        if with_topics:
            for t in m.topics:
                th = t.hours
                rows.append([t.n, t.title, th.total, th.lk, th.pr, th.lb, th.srs, ''])
    fa = doc.final_assessment
    z = 0 if doc.type == ProgramType.DPP_PK_INTERNSHIP else ''
    rows.append(['', f'Итоговая аттестация ({fa.form})', fa.hours, z, z, z, '', fa.form])
    tot = doc.totals()
    rows.append(['', 'Итого', tot.total + fa.hours, tot.lk, tot.pr, tot.lb, tot.srs, ''])
    _table(d, header, rows)


def _calendar(d: Document, doc: ProgramDoc) -> None:
    rows = [[w.week, w.days, w.hours, '; '.join(w.items[:6])] for w in doc.calendar.schedule]
    if rows:
        _table(d, ['Неделя', 'Учебных дней', 'Часов', 'Содержание'], rows)


def render_docx(doc: ProgramDoc) -> bytes:
    d = _base_document()
    p = d.add_paragraph('УТВЕРЖДАЮ\nРуководитель ' + BLANK + '\n«__» ________ 20__ г.')
    p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
    t = d.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    r = t.add_run((doc.template or 'Программа').upper() + f'\n«{doc.title}»\n{doc.volume_h} ак. ч')
    r.bold = True
    r.font.size = Pt(14)
    sections = doc.kit.sections or build_sections(doc)
    kind = 'doop' if doc.type == ProgramType.DOOP else 'dpp'
    group = ''
    for key, title in sections_for(doc):
        g = title.split('.', 1)[0] if title[:1].isdigit() else ''
        if g and g != group:
            group = g
            _heading(d, SECTION_GROUPS[g][kind], 1)
        _heading(d, title, 2 if g else 1)
        text = sections.get(key, '')
        if key == 'curriculum':
            d.add_paragraph(text)
            _curriculum(d, doc, with_topics=False)
            continue
        if key == 'utp':
            d.add_paragraph(text)
            _curriculum(d, doc, with_topics=True)
            continue
        if key == 'calendar':
            d.add_paragraph('Календарный учебный график по неделям:')
            _calendar(d, doc)
            continue
        if key == 'content':
            for m in doc.modules:
                _heading(d, f'Модуль {m.n}. {m.title} ({m.hours.total} ч)', 3)
                mp = next((x for x in doc.kit.module_programs if x.module_id == m.id), None)
                if mp and mp.annotation:
                    d.add_paragraph(mp.annotation)
                content = {c.get('topic_id'): c.get('text', '') for c in (mp.content if mp else [])}
                for tp in m.topics:
                    para = d.add_paragraph()
                    para.add_run(f'Тема {tp.n}. {tp.title}. ').bold = True
                    para.add_run(content.get(tp.id) or tp.description)
                if mp and mp.control_questions:
                    d.add_paragraph('Вопросы для самоконтроля: ' + '; '.join(mp.control_questions))
            continue
        if key == 'assessment':
            d.add_paragraph(text)
            _assessment(d, doc)
            continue
        if key == 'form' and sections.get('regime'):
            text = f"{text}\n{sections['regime']}"
        if key == 'conditions_it' and doc.norm_base:
            d.add_paragraph().add_run('Нормативные правовые акты').bold = True
            for src in doc.norm_base:
                d.add_paragraph(f'— {src.bibl}')
            d.add_paragraph().add_run('Основная и дополнительная литература, интернет-ресурсы').bold = True
        for line in (text or '').split('\n'):
            d.add_paragraph(line)
    interview = doc.kit.final_assessment.get('interview_questions') if doc.kit.final_assessment else None
    if interview or doc.type == ProgramType.DPP_PK_INTERNSHIP:
        _heading(d, 'Приложение 1. Вопросы для собеседования с руководителем стажировки', 1)
        if isinstance(interview, dict):
            for section, qs in interview.items():
                p = d.add_paragraph()
                p.add_run(f'Раздел «{section}»').bold = True
                for i, q in enumerate(qs, 1):
                    d.add_paragraph(f'{i}. {q}')
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _assessment(d: Document, doc: ProgramDoc) -> None:
    for a in doc.kit.assessments:
        qs = [q for q in doc.kit.questions if q.assessment_id == a.id]
        ts = [t for t in doc.kit.tasks if t.assessment_id == a.id]
        if not qs and not ts:
            continue
        _heading(d, a.title, 3)
        for i, q in enumerate(qs, 1):
            d.add_paragraph(f'{i}. {q.stem}')
            for j, opt in enumerate(q.options):
                d.add_paragraph(f'   {"абвгде"[j]}) {opt}')
        if qs:
            d.add_paragraph('Ключ: ' + ', '.join(f'{i}-{"абвгде"[q.key]}' for i, q in enumerate(qs, 1)))
        for t in ts:
            para = d.add_paragraph()
            para.add_run(t.title + '. ').bold = True
            para.add_run(t.statement)
            if t.expected_result:
                d.add_paragraph('Ожидаемый результат: ' + t.expected_result)
            if t.criteria:
                d.add_paragraph('Критерии: ' + '; '.join(f'{c.text} — {c.points} б.' for c in t.criteria))
    if doc.kit.report_requirements:
        _heading(d, 'Требования к отчёту', 3)
        for r in doc.kit.report_requirements:
            d.add_paragraph(f'— {r}')
    fa = doc.kit.final_assessment
    if fa:
        _heading(d, 'Материалы итоговой аттестации', 3)
        for k, v in fa.items():
            if k == 'interview_questions':
                continue
            if isinstance(v, list):
                d.add_paragraph(f'{k}:')
                for x in v:
                    d.add_paragraph(f'— {x if isinstance(x, str) else json.dumps(x, ensure_ascii=False)}')
            elif v:
                d.add_paragraph(f'{k}: {v}')


def render_lectures(doc: ProgramDoc) -> bytes:
    d = _base_document()
    _heading(d, f'Лекционные материалы: {doc.title}', 1)
    for lec in doc.kit.lectures:
        _heading(d, lec.title, 2)
        d.add_paragraph(f'Длительность: {lec.duration_min} мин')
        for step in lec.plan:
            d.add_paragraph(f'{step.get("min", "")} мин — {step.get("text", "")}')
        for code in lec.code_examples:
            para = d.add_paragraph()
            run = para.add_run(code)
            run.font.name = 'Courier New'
            run.font.size = Pt(10)
        for s in lec.slides:
            d.add_paragraph(f'Слайд {s.n}. {s.title}: ' + '; '.join(s.bullets))
    if not doc.kit.lectures:
        d.add_paragraph('Лекции ещё не сгенерированы.')
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def render_order(doc: ProgramDoc) -> bytes:
    d = _base_document()
    t = d.add_paragraph()
    t.alignment = WD_ALIGN_PARAGRAPH.CENTER
    t.add_run(f'ПРИКАЗ № {BLANK}\nот «__» ________ 20__ г.').bold = True
    d.add_paragraph(f'Об утверждении {doc.template.lower() if doc.template else "программы"} «{doc.title}»')
    d.add_paragraph('ПРИКАЗЫВАЮ:')
    d.add_paragraph(f'1. Утвердить {doc.template.lower() if doc.template else "программу"} «{doc.title}» объёмом {doc.volume_h} ак. ч.')
    d.add_paragraph(f'2. Назначить ответственным за реализацию программы {BLANK}.')
    d.add_paragraph(f'3. Контроль за исполнением приказа возложить на {BLANK}.')
    d.add_paragraph(f'Руководитель {BLANK} / {BLANK}')
    d.add_paragraph('Проект сформирован автоматически; реквизиты заполняет ответственный сотрудник.')
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def render_pptx(doc: ProgramDoc) -> bytes:
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    title_layout, body_layout = prs.slide_layouts[0], prs.slide_layouts[1]
    s = prs.slides.add_slide(title_layout)
    s.shapes.title.text = doc.title
    s.placeholders[1].text = f'{doc.template} · {doc.volume_h} ак. ч'
    lectures = [lec for lec in doc.kit.lectures if lec.slides]
    for lec in lectures:
        for sl in lec.slides:
            slide = prs.slides.add_slide(body_layout)
            slide.shapes.title.text = sl.title
            tf = slide.placeholders[1].text_frame
            tf.clear()
            for i, b in enumerate(sl.bullets or ['']):
                para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
                para.text = b
                para.font.size = PptxPt(22)
            if sl.notes:
                slide.notes_slide.notes_text_frame.text = sl.notes
            bar = slide.shapes.add_shape(1, 0, 0, prs.slide_width, Inches(0.12))
            bar.fill.solid()
            bar.fill.fore_color.rgb = PptxRGB(0x21, 0xA0, 0x38)
            bar.line.fill.background()
    if not lectures:
        slide = prs.slides.add_slide(body_layout)
        slide.shapes.title.text = 'Структура программы'
        tf = slide.placeholders[1].text_frame
        tf.text = '\n'.join(f'Модуль {m.n}. {m.title} — {m.hours.total} ч' for m in doc.modules)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()


def _gift_escape(s: str) -> str:
    return re.sub(r'([~=#{}:\\])', r'\\\1', s)


def render_gift(doc: ProgramDoc) -> bytes:
    out: list[str] = []
    for a in doc.kit.assessments:
        qs = [q for q in doc.kit.questions if q.assessment_id == a.id]
        if not qs:
            continue
        out.append(f'$CATEGORY: $course$/{_gift_escape(doc.title)}/{_gift_escape(a.title)}\n')
        for i, q in enumerate(qs, 1):
            opts = ' '.join(('=' if j == q.key else '~') + _gift_escape(o) for j, o in enumerate(q.options))
            out.append(f'::{a.id}-{i}:: {_gift_escape(q.stem)} {{ {opts} }}\n')
    return '\n'.join(out).encode('utf-8')


def render_moodle_xml(doc: ProgramDoc) -> bytes:
    parts = ['<?xml version="1.0" encoding="UTF-8"?>', '<quiz>']
    for a in doc.kit.assessments:
        qs = [q for q in doc.kit.questions if q.assessment_id == a.id]
        if not qs:
            continue
        parts.append(f'<question type="category"><category><text>$course$/{escape(doc.title)}/{escape(a.title)}</text></category></question>')
        for i, q in enumerate(qs, 1):
            parts.append('<question type="multichoice">')
            parts.append(f'<name><text>{escape(a.id)}-{i}</text></name>')
            parts.append(f'<questiontext format="html"><text><![CDATA[{q.stem}]]></text></questiontext>')
            parts.append('<single>true</single><shuffleanswers>true</shuffleanswers>')
            for j, o in enumerate(q.options):
                parts.append(f'<answer fraction="{100 if j == q.key else 0}"><text><![CDATA[{o}]]></text></answer>')
            parts.append('</question>')
    parts.append('</quiz>')
    return '\n'.join(parts).encode('utf-8')


def render(doc: ProgramDoc, fmt: str) -> tuple[bytes, str, str]:
    name = _slug(doc)
    if fmt == 'docx':
        return render_docx(doc), DOCX, f'{name}.docx'
    if fmt == 'lectures_docx':
        return render_lectures(doc), DOCX, f'{name}_lectures.docx'
    if fmt == 'order_draft':
        return render_order(doc), DOCX, f'{name}_order_draft.docx'
    if fmt == 'pptx':
        return render_pptx(doc), PPTX, f'{name}.pptx'
    if fmt == 'gift':
        return render_gift(doc), 'text/plain; charset=utf-8', f'{name}.gift.txt'
    if fmt == 'moodle_xml':
        return render_moodle_xml(doc), 'application/xml', f'{name}_moodle.xml'
    if fmt == 'json':
        return doc.model_dump_json(indent=2).encode('utf-8'), 'application/json', f'{name}.json'
    raise BadRequest(f'Неизвестный формат «{fmt}». Доступны: {", ".join(FORMATS)}')
