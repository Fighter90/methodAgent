"""Выгрузка комплекта: DOCX по шаблону АЦР, PPTX, GIFT, Moodle XML, JSON, проект приказа.

Реквизиты (ФИО, номер приказа, подписи) остаются пустыми полями — их заполняет человек (V-16).
"""

from __future__ import annotations

import io
import json
import re
import xml.etree.ElementTree as ET
from typing import Any
from xml.sax.saxutils import escape

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.shared import Pt, RGBColor

from app.agent.sections import BLANK, build_sections
from app.core.errors import BadRequest
from app.export.slides import render_lecture_slides
from app.kb.registry import org_profile
from app.programs.schemas import ProgramDoc, ProgramType
from app.validation.rules import sections_for

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
    fa = doc.final_assessment
    tot = doc.totals()
    rows: list[list[object]] = []
    if doc.type == ProgramType.DOOP and not with_topics:
        # Шапка образца ДООП: общая трудоёмкость, аудиторные часы, теория и практика, самостоятельная работа
        for m in doc.modules:
            h = m.hours
            rows.append([m.n, m.title, h.total, h.contact, h.lk, h.pr + h.lb, h.srs, m.control])
        rows.append(['', 'Итоговая аттестация', fa.hours, '—', '—', '—', '—', fa.form])
        rows.append(['', 'Итого часов', tot.total + fa.hours, tot.contact, tot.lk, tot.pr + tot.lb, tot.srs, ''])
        _table(d, ['№ п/п', 'Наименование разделов/дисциплин/модулей', 'Общая трудоемкость', 'Всего аудиторных часов', 'Лекции/теория', 'Практические занятия', 'Самостоятельная работа', 'Форма контроля'], rows)
        return
    for m in doc.modules:
        h = m.hours
        rows.append([f'{m.n}.', m.title, h.total, h.lk, h.pr, h.lb, h.srs, m.control])
        if with_topics:
            for t in m.topics:
                th = t.hours
                rows.append([t.n, t.title, th.total, th.lk, th.pr, th.lb, th.srs, ''])
    z = 0 if doc.type == ProgramType.DPP_PK_INTERNSHIP else ''
    rows.append(['', 'Итоговая аттестация', fa.hours, z, z, z, '', fa.form])
    rows.append(['', 'Итого (час.)', tot.total + fa.hours, tot.lk, tot.pr, tot.lb, tot.srs, ''])
    # Шапки образца ДПП ПК: в УП — «разделы» и «Форма аттестации», в УТП — «разделы, темы» и «Форма контроля»
    name_col = 'Наименование разделов, тем программы' if with_topics else 'Наименование разделов программы'
    form_col = 'Форма контроля' if with_topics else 'Форма аттестации'
    _table(d, ['№ п/п', name_col, 'Трудоёмкость, всего (час.)', 'ЛК', 'ПР', 'ЛБ', 'СРС (час.)', form_col], rows)


def _calendar(d: Document, doc: ProgramDoc) -> None:
    rows = [[w.week, w.days, w.hours, w.lk, w.pr, w.lb, w.srs, w.ia, '; '.join(w.items[:6])] for w in doc.calendar.schedule]
    if rows:
        _table(d, ['Неделя', 'Учебных дней', 'Всего, ч', 'ЛК', 'ПР', 'ЛБ', 'СРС', 'ИА', 'Содержание'], rows)


TITLES = {
    ProgramType.DPP_PK: 'ДОПОЛНИТЕЛЬНАЯ ПРОФЕССИОНАЛЬНАЯ ПРОГРАММА\nПОВЫШЕНИЯ КВАЛИФИКАЦИИ',
    ProgramType.DPP_PK_INTERNSHIP: 'ДОПОЛНИТЕЛЬНАЯ ПРОФЕССИОНАЛЬНАЯ ПРОГРАММА\nПОВЫШЕНИЯ КВАЛИФИКАЦИИ В ФОРМЕ СТАЖИРОВКИ',
    ProgramType.DOOP: 'ДОПОЛНИТЕЛЬНАЯ ОБЩЕОБРАЗОВАТЕЛЬНАЯ\nОБЩЕРАЗВИВАЮЩАЯ ПРОГРАММА',
}


def _para(d: Document, text: str, *, bold: bool = False, align=None, size: int | None = None):
    p = d.add_paragraph()
    r = p.add_run(text)
    r.bold = bold
    if size:
        r.font.size = Pt(size)
    if align is not None:
        p.alignment = align
    return p


def _text(d: Document, text: str) -> None:
    """Абзацы; строки «— …» — маркированный список."""
    for line in (text or '').split('\n'):
        if not line.strip():
            continue
        if line.startswith('— '):
            d.add_paragraph(line[2:], style='List Bullet')
        else:
            d.add_paragraph(line)


def _title_page(d: Document, doc: ProgramDoc, sections: dict[str, str]) -> None:
    org = org_profile()
    for line in org.get('header', []):
        _para(d, line, bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
    _para(d, '___________________________________________', align=WD_ALIGN_PARAGRAPH.CENTER)
    for line in (org.get('requisites', ''), org.get('address', '')):
        if line:
            _para(d, line, align=WD_ALIGN_PARAGRAPH.CENTER, size=10)
    d.add_paragraph()
    for line in sections.get('approval', '').split('\n'):
        _para(d, line, bold=line.startswith('УТВ'), align=WD_ALIGN_PARAGRAPH.RIGHT)
    for _ in range(4):
        d.add_paragraph()
    _para(d, TITLES.get(doc.type, (doc.template or 'Программа').upper()), bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, size=14)
    _para(d, f'«{doc.title}»', bold=True, align=WD_ALIGN_PARAGRAPH.CENTER, size=14)
    for _ in range(6):
        d.add_paragraph()
    year = (doc.created_at or '2026')[:4]
    _para(d, f'{org.get("city", "")}\n{year}', align=WD_ALIGN_PARAGRAPH.CENTER)
    d.add_page_break()


def _results_table(d: Document, doc: ProgramDoc) -> None:
    tf_titles = {t.code: re.sub(r'\s*\(код ТФ[^)]*\)', '', t.title) for t in (doc.profstandard.tf if doc.profstandard else [])}
    rows = []
    for c in doc.competencies:
        activity = '; '.join(tf_titles.get(code, code) for code in c.tf_codes) or (doc.params.direction or doc.title)
        by = {k: '; '.join(lo.text for i in c.indicators if i.kind == k for lo in i.outcomes) for k in ('own', 'can', 'know')}
        rows.append([activity, f'{c.code}. {c.title}', by['own'], by['can'], by['know']])
    _table(d, ['Виды деятельности', 'Профессиональные компетенции', 'Практический опыт', 'Умения', 'Знания'], rows)


def _work_program(d: Document, doc: ProgramDoc) -> None:
    """2.4: компоненты программы, содержание и часы — как в образце."""
    rows: list[list[object]] = []
    for m in doc.modules:
        mp = next((x for x in doc.kit.module_programs if x.module_id == m.id), None)
        rows.append([f'Раздел {m.n}. {m.title}', (mp.annotation if mp else ''), m.hours.total])
        content = {c.get('topic_id'): c.get('text', '') for c in (mp.content if mp else [])}
        for t in m.topics:
            kinds = ', '.join(f'{lbl} – {v} ч' for lbl, v in (('лекции', t.hours.lk), ('практические занятия', t.hours.pr), ('лабораторные работы', t.hours.lb), ('СРС', t.hours.srs)) if v)
            rows.append([f'Тема {t.n}. {t.title}', f'{content.get(t.id) or t.description} ({kinds})'.strip(), t.hours.total])
        rows.append(['Текущий контроль', m.control, ''])
    fa = doc.final_assessment
    rows.append(['Итоговая аттестация', fa.form, fa.hours])
    rows.append(['Итого', '', doc.totals().total + fa.hours])
    _table(d, ['Наименование компонентов программы', 'Содержание учебного материала и формы организации деятельности слушателей', 'Всего (час.)'], rows)


def _doop_utp(d: Document, doc: ProgramDoc) -> None:
    rows: list[list[object]] = []
    for m in doc.modules:
        mp = next((x for x in doc.kit.module_programs if x.module_id == m.id), None)
        content = {c.get('topic_id'): c.get('text', '') for c in (mp.content if mp else [])}
        rows.append([f'Модуль {m.n}. {m.title}', '', '', m.hours.total])
        for t in m.topics:
            kinds = '; '.join(f'{lbl} – {v} ч' for lbl, v in (('Теоретическое занятие', t.hours.lk), ('Практическое занятие', t.hours.pr + t.hours.lb), ('Самостоятельная работа', t.hours.srs)) if v)
            rows.append([f'Тема {t.n}. {t.title}', kinds, content.get(t.id) or t.description, t.hours.total])
    rows.append(['Итоговая аттестация', doc.final_assessment.form, doc.final_assessment.description, doc.final_assessment.hours])
    _table(d, ['Тема', 'Виды учебных занятий', 'Содержание', 'Часы'], rows)


def _doop_stages(d: Document, doc: ProgramDoc) -> None:
    rows = []
    for a in doc.kit.assessments:
        if a.kind == 'final':
            continue
        m = doc.module_by_id(a.module_id) if a.module_id else None
        what = {'test': 'Тест с ключом', 'seminar': 'Практическое задание', 'project': 'Проект', 'interview': 'Собеседование'}[a.kind]
        n_q = sum(1 for q in doc.kit.questions if q.assessment_id == a.id)
        stage = f'Контрольная точка по модулю {m.n} (текущий контроль)' if m else 'Итоговый тест'
        rows.append([stage, f'{what}' + (f' из {n_q} вопросов' if a.kind == 'test' and n_q else '') + (f' по модулю «{m.title}»' if m else ''), 'Педагог по ключу и критериям; обратная связь обучающемуся'])
    rows.append(['Итоговая аттестация', doc.final_assessment.form, 'Комиссия по критериям; результат — зачтено / не зачтено'])
    _table(d, ['Этап', 'Артефакт', 'Кто и как оценивает'], rows)


def _doop_staff(d: Document, doc: ProgramDoc) -> None:
    """3.4 ДООП: таблица образца по модулям УП; ФИО, степень и должность заполняют люди (V-11)."""
    rows: list[list[object]] = [[m.n, f'Модуль {m.n}. {m.title}', '', '', ''] for m in doc.modules]
    rows.append([len(doc.modules) + 1, f'Итоговая аттестация ({doc.final_assessment.form})', '', '', ''])
    _table(d, ['№', 'Модуль/Дисциплина в соответствии с УП', 'ФИО преподавателя', 'Уч. степень/Звание', 'Должность'], rows)


def _interview(doc: ProgramDoc) -> dict[str, list[str]]:
    iq = doc.kit.final_assessment.get('interview_questions') if doc.kit.final_assessment else None
    return iq if isinstance(iq, dict) else {}


def _app_current(d: Document, doc: ProgramDoc) -> None:
    iq = _interview(doc)
    if iq:
        d.add_paragraph().add_run('Примерные вопросы для собеседования:').bold = True
        n = 0
        for qs in iq.values():
            for q in qs:
                n += 1
                d.add_paragraph(f'{n}. {q}')
    _assessment(d, doc, final=False)


def _app_final(d: Document, doc: ProgramDoc) -> None:
    fa = doc.kit.final_assessment or {}
    d.add_paragraph().add_run('Методические указания к подготовке итоговой аттестации').bold = True
    d.add_paragraph(f'{doc.final_assessment.form}. {fa.get("statement") or doc.final_assessment.description}')
    if doc.kit.report_requirements:
        d.add_paragraph().add_run('Требования к работе:').bold = True
        for r in doc.kit.report_requirements:
            d.add_paragraph(r, style='List Bullet')
    crit = fa.get('criteria') or []
    if crit:
        total = sum(int(c.get('points', 0)) for c in crit)
        d.add_paragraph().add_run('Детализированные критерии оценки').bold = True
        d.add_paragraph(f'Максимальный итоговый балл: {total}. Для получения результата «зачтено» необходимо набрать не менее {round(total * 0.7)} баллов (70 %).')
        for i, c in enumerate(crit, 1):
            d.add_paragraph(f'Критерий {i}: {c.get("text")} (до {c.get("points")} б.)')
    d.add_paragraph().add_run('Процедура').bold = True
    d.add_paragraph('Выступление слушателя (5–7 минут) и ответы на вопросы комиссии (5–7 минут). Итоговое решение выносится на основании суммы баллов по всем критериям.')


def render_docx(doc: ProgramDoc) -> bytes:
    d = _base_document()
    sections = doc.kit.sections or build_sections(doc)
    _title_page(d, doc, sections)
    doop = doc.type == ProgramType.DOOP
    for key, title, level in sections_for(doc):
        if key.startswith('app'):
            d.add_page_break()
            _heading(d, title, 1)
            _para(d, sections.get(key, ''), bold=True, align=WD_ALIGN_PARAGRAPH.CENTER)
            (_app_final if key == 'app2' else _app_current)(d, doc)
            continue
        _heading(d, title, level)
        text = sections.get(key, '')
        if key == 'results' and not doop:
            d.add_paragraph(text.split('\n', 1)[0])
            _results_table(d, doc)
        elif key == 'curriculum':
            _text(d, text)
            _curriculum(d, doc, with_topics=False)
        elif key == 'utp':
            _text(d, text)
            _doop_utp(d, doc) if doop else _curriculum(d, doc, with_topics=True)
        elif key == 'calendar':
            _text(d, text)
            _calendar(d, doc)
        elif key == 'content':
            _work_program(d, doc)
        elif key == 'assessment' and doop:
            _text(d, text)
            _doop_stages(d, doc)
        elif key == 'conditions_org' and doop:
            _text(d, text)
            _doop_staff(d, doc)
        else:
            _text(d, text)
    buf = io.BytesIO()
    d.save(buf)
    return buf.getvalue()


def _assessment(d: Document, doc: ProgramDoc, final: bool = True) -> None:
    for a in doc.kit.assessments:
        if a.kind == 'final' and not final:
            continue
        qs = [q for q in doc.kit.questions if q.assessment_id == a.id]
        ts = [t for t in doc.kit.tasks if t.assessment_id == a.id]
        if not qs and not ts:
            continue
        m = doc.module_by_id(a.module_id) if a.module_id else None
        names = {'test': 'Тест', 'seminar': 'Практическое задание', 'project': 'Проект', 'interview': 'Задания стажировки', 'final': 'Итоговая аттестация'}
        _heading(d, f'{names[a.kind]} по разделу {m.n} «{m.title}»' if m else (a.title if a.kind != 'test' else 'Итоговый тест'), 3)
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
    """Слайды лекций в фирменном стиле (SPEC-EXPORT-06, SPEC-EXPORT-15)."""
    return render_lecture_slides(doc)


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


def _cdata(s: str) -> str:
    """Текст для CDATA-секции Moodle XML: `]]>` внутри текста разрывается на две секции (SPEC-EXPORT-14)."""
    return f'<![CDATA[{(s or "").replace("]]>", "]]]]><![CDATA[>")}]]>'


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
            parts.append(f'<questiontext format="html"><text>{_cdata(q.stem)}</text></questiontext>')
            parts.append('<single>true</single><shuffleanswers>true</shuffleanswers>')
            for j, o in enumerate(q.options):
                parts.append(f'<answer fraction="{100 if j == q.key else 0}"><text>{_cdata(o)}</text></answer>')
            parts.append('</question>')
    parts.append('</quiz>')
    data = '\n'.join(parts).encode('utf-8')
    try:
        ET.fromstring(data)  # SPEC-EXPORT-14: собранный XML валидируется парсером, битый файл не отдаётся
    except ET.ParseError as e:
        raise BadRequest(f'Moodle XML не прошёл проверку парсером: {e}') from e
    return data


def kit_json(doc: ProgramDoc) -> dict[str, Any]:
    """Комплект в JSON по схеме подраздела 4.8: граф «компетенция → индикатор → РО → тема → материалы».

    Служебные поля состояния (параметры распознавания, расход токенов, прогресс) в выгрузку не входят.
    """
    k = doc.kit
    hours = lambda h: h.model_dump()  # noqa: E731
    return {
        'program': {
            'id': doc.id, 'org_id': doc.org_id, 'type': doc.type.value if doc.type else None, 'template': doc.template,
            'issued_document': doc.issued_document, 'title': doc.title, 'volume_h': doc.volume_h,
            'audience': doc.params.audience, 'entry_level': doc.params.entry_level, 'form': doc.params.form,
            'duration': {'weeks': doc.calendar.weeks or doc.params.duration_weeks, 'work_days': doc.calendar.work_days},
            'calendar': doc.calendar.model_dump(mode='json'), 'status': doc.status.value, 'version': doc.version, 'goal': doc.goal,
            'final_assessment': doc.final_assessment.model_dump(mode='json'),
            'profstandard': doc.profstandard.model_dump(mode='json') if doc.profstandard else None,
            'competencies': [c.model_dump(mode='json') for c in doc.competencies],
            'modules': [
                {'id': m.id, 'n': m.n, 'title': m.title, 'hours': hours(m.hours), 'control': m.control, 'expert_id': m.expert_id,
                 'review_status': m.review_status,
                 'topics': [{'id': t.id, 'n': t.n, 'title': t.title, 'hours': hours(t.hours), 'weight': t.weight,
                             'prerequisites': t.prerequisites, 'lo_ids': t.lo_ids} for t in m.topics]}
                for m in doc.modules
            ],
            'assessments': [a.model_dump(mode='json') for a in k.assessments],
            'questions': [q.model_dump(mode='json') for q in k.questions],
            'tasks': [t.model_dump(mode='json') for t in k.tasks],
            'lectures': [lec.model_dump(mode='json') for lec in k.lectures],
            'module_programs': [mp.model_dump(mode='json') for mp in k.module_programs],
            'final_assessment_materials': k.final_assessment,
            'sources': [s.model_dump(mode='json') for s in [*doc.norm_base, *doc.sources]],
            'sections': k.sections,
            'assumptions': [a.model_dump(mode='json') for a in doc.assumptions],
            'approvals': [a.model_dump(mode='json') for a in doc.approvals],
        }
    }


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
        return json.dumps(kit_json(doc), ensure_ascii=False, indent=2).encode('utf-8'), 'application/json', f'{name}.json'
    raise BadRequest(f'Неизвестный формат «{fmt}». Доступны: {", ".join(FORMATS)}')
