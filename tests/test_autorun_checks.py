"""Приёмка автопрогона (specs/api.md, SPEC-API-30): структурная проверка выгрузок и ненулевой итог при провале."""

from __future__ import annotations

import importlib.util
import io
import json
import os
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

os.environ.setdefault('LLM_PROVIDERS', 'fixtures')


def _load_autorun() -> Any:
    """Загружает scripts/autorun.py как модуль (он сам добавляет src в sys.path)."""
    spec = importlib.util.spec_from_file_location('autorun_under_test', ROOT / 'scripts' / 'autorun.py')
    mod: Any = importlib.util.module_from_spec(spec)
    sys.modules['autorun_under_test'] = mod
    spec.loader.exec_module(mod)
    return mod


autorun = _load_autorun()


class _Resp:
    """Заглушка HTTP-ответа для run()."""

    def __init__(self, status_code: int = 200, payload: dict | None = None, content: bytes = b''):
        self.status_code = status_code
        self._payload = payload
        self.content = content

    def json(self) -> dict:
        if self._payload is None:
            raise ValueError('тело не JSON')
        return self._payload


def _topic(i: int, hours: int = 8) -> dict[str, Any]:
    return {'id': f't1.{i}', 'n': f'1.{i}', 'title': f'Тема {i}', 'total': hours, 'lk': 4, 'pr': 4, 'lb': 0, 'srs': 0, 'lo_ids': ['ro1']}


def _ok_case1() -> dict[str, Any]:
    """Полный корректный ответ автопрогона кейса 1 (все 11 проверок чек-листа зелёные)."""
    kit = {
        'modules': [{'id': 'm1', 'n': 1, 'title': 'Модуль', 'topics': [_topic(1), _topic(2)]}],
        'assessments': [{'id': 'final-test', 'kind': 'test', 'title': 'Итоговый тест'}],
        'questions': [{'id': f'q{i}', 'assessment_id': 'final-test', 'stem': f'В{i}', 'options': ['а', 'б'], 'key': 0, 'lo_ids': ['ro1']} for i in range(10)],
        'tasks': [],
        'lectures': [
            {'id': 'l1', 'topic_id': 't1.1', 'title': 'Занятие 1', 'slides': [{'n': 1, 'title': 'Слайд', 'bullets': ['тезис']}]},
            {'id': 'l2', 'topic_id': 't1.2', 'title': 'Занятие 2', 'slides': [{'n': 1, 'title': 'Слайд', 'bullets': ['тезис']}]},
        ],
        'final_assessment_materials': {'form': 'Защита проекта'},
    }
    return {
        'program_id': 'prg-1',
        'status': 'done',
        'skeleton': {'type': 'doop', 'ps_code': None, 'issued_document': 'удостоверение', 'final_assessment': {'form': 'Защита проекта'},
                     'calendar': {'sessions': 8, 'weeks': 4, 'hours_per_day': 4},
                     'totals': {'all': 16, 'lk': 8, 'pr': 8, 'lb': 0, 'srs': 0, 'ia': 0},
                     'modules': [{'n': 1, 'title': 'Модуль', 'total': 16, 'lk': 8, 'pr': 8, 'lb': 0, 'srs': 0,
                                  'topics': [{'n': '1.1', 'title': 'Тема 1', 'total': 8, 'lk': 4, 'pr': 4, 'lb': 0, 'srs': 0},
                                             {'n': '1.2', 'title': 'Тема 2', 'total': 8, 'lk': 4, 'pr': 4, 'lb': 0, 'srs': 0}]}]},
        'report': {'blocking_checks': '10/10', 'rules': []},
        'agent_notes': [],
        'questions_asked': [],
        'tokens': {'cost_rub': 0},
        'files': {'docx': '/api/v1/programs/prg-1/export/docx', 'json': '/api/v1/programs/prg-1/export/json'},
        'kit': {'program': kit},
    }


def _case5_payload(interview: dict | None) -> dict[str, Any]:
    kit = {'modules': [], 'assessments': [], 'questions': [], 'tasks': [{'id': 't1'}], 'lectures': [],
           'final_assessment_materials': {} if interview is None else {'interview_questions': interview}}
    return {
        'skeleton': {'type': 'dpp_pk_internship', 'ps_code': None, 'issued_document': 'удостоверение', 'final_assessment': {'form': 'Защита отчёта'},
                     'calendar': {'sessions': 32, 'weeks': 16, 'hours_per_day': 4},
                     'totals': {'all': 256, 'lk': 0, 'pr': 0, 'lb': 0, 'srs': 254, 'ia': 2}, 'modules': []},
        'report': {'blocking_checks': '10/10', 'rules': []},
        'agent_notes': ['Итого в образце не сходится'],
        'questions_asked': [],
        'tokens': {'cost_rub': 0},
        'files': {},
        'kit': {'program': kit},
    }


def _fake_get(bad: dict[str, bytes] | None = None) -> Any:
    """GET для run(): docx и json — настоящие файлы, остальное — байты; bad подменяет содержимое."""
    bad = bad or {}

    def get(path: str) -> _Resp:
        if path in bad:
            return _Resp(200, content=bad[path])
        fmt = path.rsplit('/', 1)[-1]
        if fmt == 'docx':
            from docx import Document

            d = Document()
            d.add_paragraph('Тестовая выгрузка')
            buf = io.BytesIO()
            d.save(buf)
            return _Resp(200, content=buf.getvalue())
        if fmt == 'json':
            program = {k: [] for k in autorun.JSON_REQUIRED} | {'id': 'prg-1', 'title': 'Программа', 'type': 'doop', 'volume_h': 16}
            return _Resp(200, content=json.dumps({'program': program}).encode('utf-8'))
        return _Resp(200, content=b'ok')

    return get


# --------------------------------------------------------------------------- export_problems


def test_export_problems_rejects_broken_files() -> None:
    """SPEC-API-30: пустые и битые выгрузки, XML с разорванным CDATA, pptx без слайдов, json без полей — это провал."""
    assert all(autorun.export_problems(fmt, b'') for fmt in ('docx', 'pptx', 'moodle_xml', 'gift', 'json'))
    assert autorun.export_problems('docx', 'не docx'.encode('utf-8'))
    assert autorun.export_problems('pptx', 'не pptx'.encode('utf-8'))
    # `]]>` без разрыва закрывает CDATA раньше времени и делает XML невалидным — парсер это ловит
    broken_xml = '<quiz><question><text><![CDATA[текст ]]> здесь]]></text></question></quiz>'.encode('utf-8')
    assert autorun.export_problems('moodle_xml', broken_xml)
    assert autorun.export_problems('moodle_xml', b'<quiz></quiz>') == ['moodle_xml без вопросов']
    assert autorun.export_problems('gift', 'текст без вопросов'.encode('utf-8'))
    from pptx import Presentation

    buf = io.BytesIO()
    Presentation().save(buf)  # презентация без слайдов
    assert autorun.export_problems('pptx', buf.getvalue()) == ['pptx без слайдов']
    problems = autorun.export_problems('json', json.dumps({'program': {'id': 'x'}}).encode('utf-8'))
    assert problems and 'title' in problems[0] and 'modules' in problems[0]


def test_real_exports_pass_structural_checks() -> None:
    """SPEC-API-30: все семь форматов выгрузки комплекта проходят структурную проверку."""
    from app.export import service as export
    from tests.test_spec_export import _doc

    doc = _doc()
    for fmt in export.FORMATS:
        data, _media, _name = export.render(doc, fmt)
        assert autorun.export_problems(fmt, data) == [], fmt


# --------------------------------------------------------------------------- run(): код выхода при провале


def test_run_ok_when_all_checks_pass(tmp_path: Path) -> None:
    """SPEC-API-30: кейс done, чеки зелёные, выгрузки скачиваются и разбираются — провалов нет (код выхода 0)."""
    failures = autorun.run(lambda *a, **k: _Resp(200, payload=_ok_case1()), _fake_get(), [{'id': 1, 'request': 'x', 'attachments': [], 'answers': {}}], tmp_path)
    assert failures == []


def test_run_fails_on_http_error(tmp_path: Path) -> None:
    """SPEC-API-30: HTTP 500 вместо 200/202 — провал кейса, run() возвращает непустой список (ненулевой код выхода)."""
    failures = autorun.run(lambda *a, **k: _Resp(500, payload={'detail': 'boom'}), _fake_get(), [{'id': 1, 'request': 'x', 'attachments': [], 'answers': {}}], tmp_path)
    assert failures and 'HTTP 500' in failures[0]


def test_run_polls_202_job(tmp_path: Path) -> None:
    """SPEC-API-30: ответ 202 с job_id — приёмка дожидается задания и принимает его результат."""

    def get(path: str) -> _Resp:
        if path.startswith('/api/v1/jobs/'):
            return _Resp(200, payload={'status': 'done', 'result': _ok_case1()})
        return _fake_get()(path)

    failures = autorun.run(lambda *a, **k: _Resp(202, payload={'job_id': 'job-1'}), get, [{'id': 1, 'request': 'x', 'attachments': [], 'answers': {}}], tmp_path)
    assert failures == []


def test_run_fails_on_status_check_and_broken_export(tmp_path: Path) -> None:
    """SPEC-API-30: статус не done, проваленный чек и битая выгрузка — каждая причина попадает в провалы."""
    payload = _ok_case1()
    payload['status'] = 'done_with_errors'
    payload['report']['blocking_checks'] = '9/10'
    failures = autorun.run(lambda *a, **k: _Resp(200, payload=payload), _fake_get({'/api/v1/programs/prg-1/export/docx': 'мусор'.encode('utf-8')}),
                           [{'id': 1, 'request': 'x', 'attachments': [], 'answers': {}}], tmp_path)
    assert any('done_with_errors' in f for f in failures), failures
    assert any('чек провален — блокирующие проверки 10/10' in f for f in failures), failures
    assert any('выгрузка docx' in f for f in failures), failures


# --------------------------------------------------------------------------- усиленные чеки чек-листа


def test_case1_slides_check_requires_first_two_topics() -> None:
    """SPEC-API-30: «слайды для занятий 1 и 2» — слайды у первых двух тем, а не «хоть одной лекции»."""
    checks = dict(autorun._checks({'id': 1}, _ok_case1()))
    assert checks['слайды для занятий 1 и 2']
    payload = _ok_case1()
    payload['kit']['program']['lectures'][0]['slides'] = []  # у занятия 1 слайдов нет
    payload['kit']['program']['lectures'].append({'id': 'l3', 'topic_id': 't2.1', 'title': 'Занятие 3', 'slides': [{'n': 1, 'title': 'С', 'bullets': ['x']}]})
    checks = dict(autorun._checks({'id': 1}, payload))
    assert not checks['слайды для занятий 1 и 2']


def test_case5_interview_check_requires_interview_questions() -> None:
    """SPEC-API-30: «вопросы собеседования» — вопросы ИА стажировки, а не любые задания комплекта."""
    checks = dict(autorun._checks({'id': 5}, _case5_payload({'Модуль 1': ['Вопрос 1', 'Вопрос 2', 'Вопрос 3']})))
    assert checks['вопросы собеседования']
    checks = dict(autorun._checks({'id': 5}, _case5_payload(None)))
    assert not checks['вопросы собеседования']
    checks = dict(autorun._checks({'id': 5}, _case5_payload({'Модуль 1': []})))
    assert not checks['вопросы собеседования']
