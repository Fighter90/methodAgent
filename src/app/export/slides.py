"""Слайды лекций (.pptx) в фирменном стиле МетодАгента: тёмный фон, зелёные акценты, Manrope (SPEC-EXPORT-15).

Заголовок и тезисы остаются в штатных плейсхолдерах макетов python-pptx: их читают LMS, проверки автопрогона
и тесты; оформление — фон слайда, цвет и шрифт текста и фигуры позади плейсхолдеров.
"""

from __future__ import annotations

import io
from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

from app.kb.registry import org_profile
from app.programs.schemas import Lecture, ProgramDoc

FONT = 'Manrope'
BG = RGBColor(0x0E, 0x13, 0x17)
CARD = RGBColor(0x13, 0x1A, 0x1F)
LINE = RGBColor(0x26, 0x30, 0x36)
ACCENT = RGBColor(0x21, 0xA0, 0x38)
ACCENT_LIGHT = RGBColor(0x5D, 0xD8, 0x79)
INK = RGBColor(0xF2, 0xF4, 0xF7)
MUTED = RGBColor(0x9A, 0xA3, 0xAE)
W, H = Inches(13.333), Inches(7.5)
ASSETS = Path(__file__).with_name('assets')


def _font(run, size: float, color: RGBColor, bold: bool = False) -> None:
    run.font.name, run.font.size, run.font.bold = FONT, Pt(size), bold
    run.font.color.rgb = color


def _send_back(slide, shape, layer: int = 1) -> None:
    """Фигура уходит под плейсхолдеры: текст остаётся поверх оформления. Слой 0 — фон, 1 — карточки над фоном."""
    tree = slide.shapes._spTree
    tree.remove(shape._element)
    tree.insert(2 + layer, shape._element)


def _background(slide, image: str) -> None:
    """Фон — та же картинка, что в презентации защиты: тёмная сетка с зелёным свечением слева сверху."""
    fill = slide.background.fill
    fill.solid()
    fill.fore_color.rgb = BG
    _send_back(slide, slide.shapes.add_picture(str(ASSETS / image), 0, 0, W, H), layer=0)


def _box(slide, x, y, w, h, fill: RGBColor, line: RGBColor | None = None, shape=MSO_SHAPE.ROUNDED_RECTANGLE):
    s = slide.shapes.add_shape(shape, x, y, w, h)
    if shape == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = 0.06
    s.fill.solid()
    s.fill.fore_color.rgb = fill
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb, s.line.width = line, Pt(1)
    s.shadow.inherit = False
    return s


def _text(slide, x, y, w, h, text: str, size: float, color: RGBColor, bold: bool = False, spacing: int = 0, align=PP_ALIGN.LEFT):
    tb = slide.shapes.add_textbox(x, y, w, h)
    tf = tb.text_frame
    tf.word_wrap = True
    tf.margin_left = tf.margin_right = 0
    p = tf.paragraphs[0]
    p.alignment = align
    run = p.add_run()
    run.text = text
    _font(run, size, color, bold)
    if spacing:
        run.font._element.set('spc', str(spacing))
    return tb


def _logo(slide, x, y, size: float) -> None:
    mark = _box(slide, x, y, Inches(size), Inches(size), ACCENT)
    tf = mark.text_frame
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    tf.vertical_anchor = MSO_ANCHOR.MIDDLE
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = 'M'
    _font(run, size * 30, INK, bold=True)


def _footer(slide, program: str, number: int) -> None:
    _logo(slide, Inches(0.6), Inches(6.98), 0.22)
    _text(slide, Inches(0.92), Inches(6.95), Inches(10.5), Inches(0.3), f'МетодАгент · {program}', 9.5, MUTED)
    _text(slide, Inches(12.0), Inches(6.95), Inches(0.73), Inches(0.3), str(number), 9.5, MUTED, align=PP_ALIGN.RIGHT)


def _bullets(tf, items: list[str], size: float) -> None:
    """Тезисы с зелёным маркером «●»; текст остаётся в штатном плейсхолдере."""
    tf.clear()
    tf.word_wrap = True
    for i, b in enumerate(items or ['']):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        pPr = para._p.get_or_add_pPr()
        pPr.set('marL', str(Emu(Inches(0.34))))
        pPr.set('indent', str(-Emu(Inches(0.34))))
        clr = pPr.makeelement(qn('a:buClr'), {})
        clr.append(clr.makeelement(qn('a:srgbClr'), {'val': str(ACCENT_LIGHT)}))
        pPr.append(clr)
        pPr.append(pPr.makeelement(qn('a:buChar'), {'char': '●'}))
        para.space_after = Pt(12)
        run = para.add_run()
        run.text = b
        _font(run, size, INK)


def _place_title(shape, x, y, w, h, size: float) -> None:
    shape.left, shape.top, shape.width, shape.height = x, y, w, h
    tf = shape.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = MSO_ANCHOR.TOP
    for p in tf.paragraphs:
        p.alignment = PP_ALIGN.LEFT
        for r in p.runs:
            _font(r, size, INK, bold=True)


def _title_slide(prs, doc: ProgramDoc) -> None:
    s = prs.slides.add_slide(prs.slide_layouts[0])
    _background(s, 'slide-hero.jpg')
    _logo(s, Inches(0.6), Inches(0.5), 0.42)
    _text(s, Inches(1.15), Inches(0.53), Inches(4), Inches(0.4), 'МетодАгент', 16, INK, bold=True)
    org = str(org_profile().get('name') or '').strip()
    if org:
        _text(s, Inches(5.5), Inches(0.6), Inches(7.23), Inches(0.35), org, 10.5, MUTED, align=PP_ALIGN.RIGHT)
    _text(s, Inches(0.6), Inches(1.75), Inches(7.2), Inches(0.35), 'СЛАЙДЫ ЛЕКЦИЙ', 10, ACCENT_LIGHT, bold=True, spacing=300)
    s.shapes.title.text = doc.title
    _place_title(s.shapes.title, Inches(0.6), Inches(2.15), Inches(7.2), Inches(2.7), 40 if len(doc.title) < 70 else 30)
    sub = s.placeholders[1]
    sub.text = f'{doc.template} · {doc.volume_h} ак. ч'
    sub.left, sub.top, sub.width, sub.height = Inches(0.6), Inches(3.35 if len(doc.title) <= 30 else 4.25 if len(doc.title) <= 60 else 5.0), Inches(7.2), Inches(0.6)
    for p in sub.text_frame.paragraphs:
        p.alignment = PP_ALIGN.LEFT
        for r in p.runs:
            _font(r, 16, MUTED)
    if doc.modules:
        _send_back(s, _box(s, Inches(8.3), Inches(1.75), Inches(4.43), Inches(4.7), CARD, LINE))
        _text(s, Inches(8.6), Inches(2.0), Inches(3.9), Inches(0.3), 'МОДУЛИ', 9, MUTED, bold=True, spacing=200)
        step = min(0.62, 3.8 / len(doc.modules))
        small = len(doc.modules) > 6
        for i, m in enumerate(doc.modules):
            y = Inches(2.45 + i * step)
            _text(s, Inches(8.6), y, Inches(0.4), Inches(0.35), str(m.n), 10 if small else 13, ACCENT_LIGHT, bold=True)
            _text(s, Inches(9.0), y, Inches(2.95), Inches(step), m.title, 9 if small else 11.5, INK)
            _text(s, Inches(11.95), y, Inches(0.55), Inches(0.35), f'{m.hours.total} ч', 9 if small else 10, MUTED, align=PP_ALIGN.RIGHT)
    _text(s, Inches(0.6), Inches(6.9), Inches(12.1), Inches(0.35),
          'Черновик агента: перед занятием слайды вычитывает преподаватель', 9.5, MUTED)


def _content_slide(prs, eyebrow: str, title: str, bullets: list[str], program: str, number: int):
    s = prs.slides.add_slide(prs.slide_layouts[1])
    _background(s, 'slide-content.jpg')
    _box(s, Inches(0.6), Inches(0.52), Inches(0.06), Inches(0.24), ACCENT, shape=MSO_SHAPE.RECTANGLE)
    _text(s, Inches(0.8), Inches(0.47), Inches(11.5), Inches(0.35), eyebrow.upper(), 10, ACCENT_LIGHT, bold=True, spacing=200)
    s.shapes.title.text = title
    _place_title(s.shapes.title, Inches(0.6), Inches(0.92), Inches(12.13), Inches(1.2), 30 if len(title) < 60 else 24)
    size = 20 if len(bullets) <= 5 else 16
    # карточка по высоте текста: строки оцениваются по длине тезиса, чтобы два тезиса не тонули в пустой рамке
    lines = sum(max(1, -(-len(b) // (95 if size == 20 else 120))) for b in bullets or [''])
    height = min(4.45, max(1.6, 0.6 + lines * size / 72 * 1.25 + len(bullets or ['']) * 0.17))
    _send_back(s, _box(s, Inches(0.6), Inches(2.25), Inches(12.13), Inches(height), CARD, LINE))
    body = s.placeholders[1]
    body.left, body.top, body.width, body.height = Inches(0.95), Inches(2.55), Inches(11.43), Inches(height - 0.5)
    body.text_frame.vertical_anchor = MSO_ANCHOR.TOP
    _bullets(body.text_frame, bullets, size)
    _footer(s, program, number)
    return s


def _eyebrow(doc: ProgramDoc, lec: Lecture) -> str:
    m = doc.module_by_id(lec.module_id)
    topic = next((t for t in (m.topics if m else []) if t.id == lec.topic_id), None)
    parts = [f'Модуль {m.n}' if m else '', f'Тема {topic.n}' if topic else lec.title]
    return ' · '.join(p for p in parts if p) or 'Лекция'


def render_lecture_slides(doc: ProgramDoc) -> bytes:
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    _title_slide(prs, doc)
    lectures = [lec for lec in doc.kit.lectures if lec.slides]
    number = 1
    for lec in lectures:
        eyebrow = _eyebrow(doc, lec)
        for sl in lec.slides:
            number += 1
            slide = _content_slide(prs, eyebrow, sl.title, sl.bullets, doc.title, number)
            if sl.notes:
                slide.notes_slide.notes_text_frame.text = sl.notes
    if not lectures:
        _content_slide(prs, 'Программа', 'Структура программы',
                       [f'Модуль {m.n}. {m.title} — {m.hours.total} ч' for m in doc.modules], doc.title, 2)
    buf = io.BytesIO()
    prs.save(buf)
    return buf.getvalue()
