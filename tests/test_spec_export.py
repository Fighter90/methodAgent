"""Спецификация specs/export.md: выгрузки комплекта (FR-52 – FR-57, FR-62)."""

from __future__ import annotations

import io
import json
import os
import re
import xml.etree.ElementTree as ET
from urllib.parse import unquote

import pytest

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')

from app.agent.sections import BLANK  # noqa: E402
from app.export import service as export  # noqa: E402
from app.programs.schemas import (  # noqa: E402
    Assessment,
    Hours,
    Lecture,
    Module,
    ProgramDoc,
    ProgramType,
    Question_,
    Slide,
)

REQ = ('Нужна программа повышения квалификации на 72 часа «Анализ данных на Python» для сотрудников банков, '
       'очно-заочно, 4 недели. Темы: pandas, визуализация, SQL, статистика. Итоговая аттестация — защита проекта.')
FILLED = [re.compile(r'приказ\w*\s*№\s*\d', re.I), re.compile(r'от\s*«\d{1,2}»', re.I)]


@pytest.fixture(scope='module')
def client(tmp_path_factory):
    os.environ['DATA_DIR'] = str(tmp_path_factory.mktemp('data'))
    from fastapi.testclient import TestClient

    from app.core.config import get_settings

    get_settings.cache_clear()
    from app.kb.registry import registry

    registry.cache_clear()
    from app.main import create_app

    with TestClient(create_app()) as c:
        yield c


def _h(client, user: str) -> dict[str, str]:
    tok = client.post('/api/v1/auth/login', json={'user_id': user, 'password': 'demo'}).json()['access_token']
    return {'Authorization': f'Bearer {tok}'}


@pytest.fixture(scope='module')
def run(client) -> dict:
    r = client.post('/api/v1/programs?mode=auto', json={'request': REQ}, headers=_h(client, 'u-madina'))
    assert r.status_code == 200, r.text
    return r.json()


def _docx_text(data: bytes) -> str:
    from docx import Document

    d = Document(io.BytesIO(data))
    parts = [p.text for p in d.paragraphs]
    parts += [c.text for t in d.tables for row in t.rows for c in row.cells]
    return '\n'.join(parts)


def _doc() -> ProgramDoc:
    return ProgramDoc(
        id='prg-x', request='x', title='Python: анализ/данных {2026}!', type=ProgramType.DPP_PK, template='ДПП ПК', volume_h=16,
        modules=[Module(id='m1', n=1, title='Основы', hours=Hours(total=14, lk=4, pr=10))],
        kit={'assessments': [Assessment(id='test-m1', module_id='m1', kind='test', title='Тест: модуль 1')],
             'questions': [Question_(id='q1', assessment_id='test-m1', stem='Что вернёт {1: 2}[1] = ?', options=['2', '~1', '#x'], key=0, lo_ids=[]),
                           Question_(id='q2', assessment_id='test-m1', stem='Выберите <b>', options=['a', 'b', 'c'], key=2)]},
    )


def test_formats_and_unknown(client, run) -> None:
    """SPEC-EXPORT-01: выгружаются docx, pptx, gift, moodle_xml, json, order_draft, lectures_docx; неизвестный формат — 400 со списком."""
    assert export.FORMATS == ('docx', 'pptx', 'gift', 'moodle_xml', 'json', 'order_draft', 'lectures_docx')
    h = _h(client, 'u-madina')
    for fmt in export.FORMATS:
        r = client.get(f'/api/v1/programs/{run["program_id"]}/export/{fmt}', headers=h)
        assert r.status_code == 200 and r.content, fmt
    r = client.get(f'/api/v1/programs/{run["program_id"]}/export/pdf', headers=h)
    assert r.status_code == 400
    assert all(fmt in r.text for fmt in export.FORMATS)


def test_human_fields_left_blank(client, run) -> None:
    """SPEC-EXPORT-03: номер и дата приказа, ФИО преподавателей и подписи остаются полями «________________» во всех выгрузках."""
    h = _h(client, 'u-madina')
    pid = run['program_id']
    texts = {
        'docx': _docx_text(client.get(f'/api/v1/programs/{pid}/export/docx', headers=h).content),
        'order_draft': _docx_text(client.get(f'/api/v1/programs/{pid}/export/order_draft', headers=h).content),
        'json': client.get(f'/api/v1/programs/{pid}/export/json', headers=h).text,
    }
    for name, text in texts.items():
        assert BLANK in text, name
        assert not any(rx.search(text) for rx in FILLED), name
    assert f'Состав преподавателей (ФИО, должность, модули): {BLANK}' in texts['docx']
    assert 'Приказом № ____' in texts['docx']


def test_gift_and_moodle_xml() -> None:
    """SPEC-EXPORT-05: GIFT экранирует служебные символы; Moodle XML — вопросы multichoice с одним верным ответом fraction="100"."""
    gift = export.render_gift(_doc()).decode()
    assert r'Что вернёт \{1\: 2\}[1] \= ?' in gift
    assert r'{ =2 ~\~1 ~\#x }' in gift
    assert r'$CATEGORY: $course$/Python\: анализ/данных \{2026\}!/Тест\: модуль 1' in gift
    root = ET.fromstring(export.render_moodle_xml(_doc()))
    qs = root.findall("question[@type='multichoice']")
    assert len(qs) == 2
    for q, key in zip(qs, (0, 2), strict=True):
        assert q.findtext('single') == 'true'
        fr = [a.get('fraction') for a in q.findall('answer')]
        assert fr.count('100') == 1 and fr.index('100') == key and set(fr) == {'0', '100'}
    assert qs[1].find('questiontext/text').text == 'Выберите <b>'


def test_moodle_xml_cdata_roundtrip() -> None:
    """SPEC-EXPORT-14: `]]>` внутри CDATA разрывается; собранный Moodle XML парсится, тексты с `]]>`, `<`, `&`, кавычками и переносами строк читаются обратно без потерь."""
    doc = _doc()
    stem = 'Вопрос с ]]> внутри <тега> и & "кавычками"\nвторая строка'
    options = [']]><&\'"', 'a & b < c > d', ']][[ — не конец секции', 'вариант\nс переносом']
    doc.kit.questions[0].stem = stem
    doc.kit.questions[0].options = options
    doc.kit.questions[0].key = 3
    data = export.render_moodle_xml(doc)
    root = ET.fromstring(data)  # битый XML упал бы с ParseError
    q = root.findall("question[@type='multichoice']")[0]
    assert q.findtext('questiontext/text') == stem
    answers = q.findall('answer')
    assert [a.findtext('text') for a in answers] == options
    assert [a.get('fraction') for a in answers].index('100') == 3


def test_pptx_16x9_and_fallback() -> None:
    """SPEC-EXPORT-06: pptx 16:9 со слайдами лекций; без слайдов — слайд «Структура программы»."""
    from pptx import Presentation

    doc = _doc()
    prs = Presentation(io.BytesIO(export.render_pptx(doc)))
    assert round(prs.slide_width / prs.slide_height, 2) == round(16 / 9, 2)
    titles = [s.shapes.title.text for s in prs.slides]
    assert titles == ['Python: анализ/данных {2026}!', 'Структура программы']
    assert 'Модуль 1. Основы — 14 ч' in prs.slides[1].placeholders[1].text_frame.text
    doc.kit.lectures = [Lecture(id='l1', topic_id='t1', module_id='m1', title='Циклы', slides=[
        Slide(id='s1', n=1, title='Цикл for', bullets=['перебор', 'range'], notes='заметка'),
        Slide(id='s2', n=2, title='Цикл while', bullets=['условие'])])]
    prs = Presentation(io.BytesIO(export.render_pptx(doc)))
    assert [s.shapes.title.text for s in prs.slides][1:] == ['Цикл for', 'Цикл while']
    assert prs.slides[1].notes_slide.notes_text_frame.text == 'заметка'


def test_lectures_docx() -> None:
    """SPEC-EXPORT-07: лекции — план по минутам, примеры кода моноширинным шрифтом, тезисы слайдов."""
    from docx import Document

    doc = _doc()
    doc.kit.lectures = [Lecture(id='l1', topic_id='t1', module_id='m1', title='Циклы', duration_min=45,
                                plan=[{'min': 15, 'text': 'Введение'}, {'min': 30, 'text': 'Практика'}],
                                code_examples=['for i in range(3):\n    print(i)'],
                                slides=[Slide(id='s1', n=1, title='Цикл for', bullets=['перебор', 'range'])])]
    d = Document(io.BytesIO(export.render_lectures(doc)))
    text = '\n'.join(p.text for p in d.paragraphs)
    assert '15 мин — Введение' in text and '30 мин — Практика' in text
    assert 'Слайд 1. Цикл for: перебор; range' in text
    code_runs = [r for p in d.paragraphs for r in p.runs if 'range(3)' in r.text]
    assert code_runs and code_runs[0].font.name == 'Courier New'


def test_order_draft() -> None:
    """SPEC-EXPORT-08: проект приказа без номера, даты, ответственных и подписи, с пометкой об автоматическом формировании."""
    text = _docx_text(export.render_order(_doc()))
    assert f'ПРИКАЗ № {BLANK}' in text and 'от «__» ________ 20__ г.' in text
    assert f'ответственным за реализацию программы {BLANK}' in text
    assert f'Руководитель {BLANK} / {BLANK}' in text
    assert 'сформирован автоматически' in text
    assert not any(rx.search(text) for rx in FILLED)


def test_filename_and_disposition(client, run) -> None:
    """SPEC-EXPORT-09: имя файла — по названию программы (кроме букв, цифр и дефиса — «_», до 60 символов), Content-Disposition: attachment."""
    _content, _media, name = export.render(_doc(), 'docx')
    assert name == 'Python_анализ_данных_2026.docx'
    long = _doc()
    long.title = 'Очень-длинное ' * 10
    assert len(export.render(long, 'json')[2].removesuffix('.json')) == 60
    r = client.get(f'/api/v1/programs/{run["program_id"]}/export/gift', headers=_h(client, 'u-madina'))
    cd = r.headers['content-disposition']
    assert cd.startswith('attachment;')
    fname = unquote(cd.split("UTF-8''", 1)[1])
    assert fname.endswith('.gift.txt') and re.fullmatch(r'[\w\-]+\.gift\.txt', fname)


def test_auto_run_lists_all_exports(client, run) -> None:
    """SPEC-EXPORT-11: ответ автопрогона содержит ссылки на выгрузку во всех форматах."""
    files = run['files']
    assert set(files) == set(export.FORMATS)
    for fmt, url in files.items():
        assert url.endswith(f'/api/v1/programs/{run["program_id"]}/export/{fmt}')
    j = json.loads(client.get(files['json'].split('testserver', 1)[-1], headers=_h(client, 'u-madina')).text)
    assert j['program']['id'] == run['program_id']


def test_pptx_brand_style() -> None:
    """SPEC-EXPORT-15: слайды лекций в фирменном стиле — тёмный фон-картинка, Manrope, тезисы с зелёным маркером,
    надзаголовок «Модуль N · Тема n.m», номер слайда; заголовок, тезисы и заметки остаются в штатных плейсхолдерах."""
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    from app.programs.schemas import Topic

    doc = _doc()
    doc.modules[0].topics = [Topic(id='t1', n='1.1', title='Циклы')]
    doc.kit.lectures = [Lecture(id='l1', topic_id='t1', module_id='m1', title='Циклы', slides=[
        Slide(id='s1', n=1, title='Цикл for', bullets=['перебор — проход по элементам списка'], notes='заметка')])]
    prs = Presentation(io.BytesIO(export.render_pptx(doc)))
    for s in prs.slides:
        assert s.shapes[0].shape_type == MSO_SHAPE_TYPE.PICTURE  # фон — первая фигура, под текстом
    body = prs.slides[1]
    texts = [sh.text_frame.text for sh in body.shapes if sh.has_text_frame]
    assert 'МОДУЛЬ 1 · ТЕМА 1.1' in texts and '2' in texts
    assert body.shapes.title.text_frame.paragraphs[0].runs[0].font.name == 'Manrope'
    assert str(body.shapes.title.text_frame.paragraphs[0].runs[0].font.color.rgb) == 'F2F4F7'
    para = body.placeholders[1].text_frame.paragraphs[0]
    assert para._p.pPr.find('{http://schemas.openxmlformats.org/drawingml/2006/main}buChar') is not None
    assert body.notes_slide.notes_text_frame.text == 'заметка'
