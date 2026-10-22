"""Прогон открытых запросов кейса (testset/cases.json) через POST /api/v1/programs?mode=auto.

Запуск:
    python scripts/autorun.py                       # в процессе, без сервера
    python scripts/autorun.py --url http://localhost:8000
Результаты: logs/autorun/<id>.json и сводка logs/autorun/summary.md.

Автопрогон — независимая приёмка (SPEC-API-30): при любом провале процесс завершается
с ненулевым кодом выхода. Провал — это HTTP-ответ не 200/202 (202 дожидается задания),
конечный статус не done, проваленный чек чек-листа или выгрузка, которая не скачалась
или не прошла структурную проверку `export_problems`.

Приёмка слайдов (SPEC-Q-02, MET-58/R14): слайды засчитываются, только если у каждой
заявленной темы есть лекция с непустыми слайдами, а `module_id` этой лекции совпадает
с модулем темы; лекции со слайдами из чужих модулей проваливают чек своего кейса.
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))

# Выгрузки в формате Word: проверяются python-docx
DOCX_FORMATS = frozenset({'docx', 'order_draft', 'lectures_docx'})
# Обязательные поля JSON-выгрузки по схеме 4.8 ТЗ
JSON_REQUIRED = ('id', 'title', 'type', 'volume_h', 'competencies', 'modules', 'assessments', 'questions', 'tasks', 'lectures')
# Обязательные поля ответа автопрогона, без которых приёмка невозможна
PAYLOAD_KEYS = ('skeleton', 'report', 'kit', 'files')


def export_problems(fmt: str, data: bytes) -> list[str]:
    """Структурная проверка выгрузки (SPEC-API-30): список проблем; пустой список — выгрузка корректна.

    docx открывается python-docx и не пуст; pptx открывается python-pptx и содержит слайд;
    moodle_xml разбирается XML-парсером и содержит вопросы; gift содержит категорию и вопросы;
    json содержит обязательные поля схемы 4.8. Неизвестный формат — только непустой файл.
    """
    if not data:
        return ['файл пустой']
    try:
        if fmt in DOCX_FORMATS:
            from docx import Document

            d = Document(io.BytesIO(data))
            if not d.paragraphs and not d.tables:
                return ['docx без абзацев и таблиц']
        elif fmt == 'pptx':
            from pptx import Presentation

            if not len(Presentation(io.BytesIO(data)).slides):
                return ['pptx без слайдов']
        elif fmt == 'moodle_xml':
            root = ET.fromstring(data)
            if root.find('question') is None:
                return ['moodle_xml без вопросов']
        elif fmt == 'gift':
            text = data.decode('utf-8')
            if '$CATEGORY:' not in text or '::' not in text:
                return ['gift без категорий или вопросов']
        elif fmt == 'json':
            program = json.loads(data).get('program') or {}
            missing = [k for k in JSON_REQUIRED if k not in program]
            if missing:
                return ['json без полей: ' + ', '.join(missing)]
    except Exception as exc:  # любая ошибка разбора означает битую выгрузку
        return [f'не разбирается: {type(exc).__name__}: {exc}']
    return []


def _slides_problems(kit: dict, wanted: list[str]) -> list[str]:
    """Приёмка слайдов (SPEC-Q-02): список проблем; пустой список — слайды полные и в своих модулях.

    Для каждой заявленной темы `wanted` должна найтись лекция с непустыми слайдами,
    у которой `module_id` совпадает с модулем этой темы по плану комплекта; лекция
    со слайдами по чужой теме или из модуля вне комплекта — провал приёмки.
    """
    owner = {t['id']: m['id'] for m in kit.get('modules', []) for t in m.get('topics', [])}
    problems: list[str] = []
    for lec in kit.get('lectures', []):
        if not lec.get('slides'):
            continue
        if lec.get('topic_id') not in owner or lec.get('module_id') != owner[lec.get('topic_id')]:
            problems.append(f'лекция {lec.get("id")!r} со слайдами не принадлежит своему модулю '
                            f'(module_id={lec.get("module_id")!r}, тема {lec.get("topic_id")!r})')
    for tid in wanted:
        if not any(lec.get('topic_id') == tid and lec.get('module_id') == owner.get(tid) and lec.get('slides')
                   for lec in kit.get('lectures', [])):
            problems.append(f'у темы {tid} нет лекции со слайдами её модуля')
    return problems


def _checks(case: dict, r: dict) -> list[tuple[str, bool]]:
    sk = r['skeleton']
    tot = sk['totals']
    kit = r['kit']['program']  # комплект по схеме 4.8
    mods = sk['modules']
    out: list[tuple[str, bool]] = []
    vol = {1: 16, 2: 36, 3: 72, 4: 72, 5: 256}[case['id']]
    out.append((f'объём ровно {vol} ч', tot['all'] == vol))
    rows_ok = all(m['lk'] + m['pr'] + m['lb'] + m['srs'] == m['total'] and sum(t['total'] for t in m['topics']) == m['total'] for m in mods)
    out.append(('часы сходятся во всех строках', rows_ok))
    out.append(('блокирующие проверки 10/10', r['report']['blocking_checks'] == '10/10'))
    out.append(('выгрузки docx и json', {'docx', 'json'} <= set(r['files'])))
    q_by_lo: dict[str, int] = {}
    for q in kit['questions']:
        for lo in q['lo_ids']:
            q_by_lo[lo] = q_by_lo.get(lo, 0) + 1
    if case['id'] == 1:
        out.append(('шаблон ДООП', sk['type'] == 'doop'))
        out.append(('практика ≥ 8 ч', tot['pr'] + tot['lb'] >= 8))
        out.append(('8 занятий за 4 недели', sk['calendar']['sessions'] == 8 and sk['calendar']['weeks'] <= 4))
        finals = [q for q in kit['questions'] if q['assessment_id'].startswith('final') or 'final' in q['assessment_id']]
        out.append(('итоговый тест 10 вопросов с РО', len(finals) == 10 and all(q['lo_ids'] for q in finals)))
        # Слайды именно первых двух тем-занятий своего модуля, а не «хоть одной лекции» (SPEC-Q-02)
        first_two = [t['id'] for m in kit['modules'] for t in m['topics']][:2]
        out.append(('слайды для занятий 1 и 2', len(first_two) == 2 and not _slides_problems(kit, first_two)))
        out.append(('нет профстандарта', sk['ps_code'] is None))
        out.append(('итог — защита проекта', 'проект' in sk['final_assessment']['form'].lower()))
    if case['id'] == 2:
        out.append(('ДПП ПК, удостоверение', sk['type'] == 'dpp_pk' and 'удостоверение' in sk['issued_document'].lower()))
        out.append(('ПС «Педагог» 01.001', sk['ps_code'] == '01.001'))
        text = json.dumps(r, ensure_ascii=False).lower()
        out.append(('тема о рисках и персональных данных', 'персональн' in text))
        out.append(('нет недоступных в РФ сервисов', not any(x in text for x in ('chatgpt', 'midjourney', 'claude'))))
        out.append(('итог — портфолио', 'портфолио' in sk['final_assessment']['form'].lower()))
    if case['id'] == 3:
        titles = ' '.join(m['title'] + ' ' + ' '.join(t['title'] for t in m['topics']) for m in mods).lower()
        out.append(('pandas, визуализация, SQL, статистика', all(x in titles for x in ('pandas', 'визуализ', 'sql', 'статист'))))
        out.append(('вводный блок Python первым', 'python' in mods[0]['title'].lower()))
        out.append(('4 недели', sk['calendar']['weeks'] == 4))
        out.append(('ПС по данным', sk['ps_code'] in ('06.042', '06.033', '06.016')))
        # Каждая тема модуля pandas из плана ответа — со слайдами своего модуля (SPEC-Q-02)
        pmods = [m for m in kit['modules'] if 'pandas' in m['title'].lower()]
        wanted = [t['id'] for m in pmods for t in m['topics']]
        out.append(('слайды для всех тем модуля pandas', bool(wanted) and not _slides_problems(kit, wanted)))
    if case['id'] == 4:
        asked = r['questions_asked']  # все вопросы clarify; questions_skipped — только неотвеченные
        out.append(('вопросы были заданы', bool(asked)))
        out.append(('вопросов ≤ 5', len(asked) <= 5))
        out.append(('ДПП ПК', sk['type'] == 'dpp_pk'))
        out.append(('разница ожиданий в отчёте', any('V-27' == x['id'] and x['messages'] for x in r['report']['rules']) or any('ожидан' in n.lower() for n in r['agent_notes'])))
        out.append(('итог — экзамен с практикой', 'экзамен' in sk['final_assessment']['form'].lower()))
    if case['id'] == 5:
        out.append(('СРС 254 + ИА 2', tot['srs'] == 254 and tot['ia'] == 2))
        out.append(('ЛК/ПР/ЛБ = 0', tot['lk'] == tot['pr'] == tot['lb'] == 0))
        out.append(('≤ 4 ч в день', sk['calendar']['hours_per_day'] <= 4))
        out.append(('ошибка образца отмечена', any('образц' in n.lower() or 'итого' in n.lower() for n in r['agent_notes'])))
        # Вопросы собеседования стажировки, а не любые задания комплекта
        iq = (kit.get('final_assessment_materials') or {}).get('interview_questions')
        out.append(('вопросы собеседования', isinstance(iq, dict) and any(iq.values())))
        # Слайды не заказаны, но появившиеся лекции со слайдами обязаны быть в модулях комплекта (SPEC-Q-02)
        out.append(('слайды лекций в своих модулях', not _slides_problems(kit, [])))
    return out


def _job_result(get: Any, payload: dict) -> tuple[dict | None, str | None]:
    """Дожидается задания автопрогона (ответ 202): (результат, сообщение о провале)."""
    job_id = payload.get('job_id')
    if not job_id:
        return None, 'ответ 202 без job_id'
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        info = get(f'/api/v1/jobs/{job_id}').json()
        if info.get('status') == 'done':
            result = info.get('result') or {}
            return (result, None) if result else (None, 'задание done без результата')
        if info.get('status') in ('failed', 'error'):
            return None, f'задание {info.get("status")}: {info.get("error") or "без описания"}'
        time.sleep(1)
    return None, f'задание {job_id} не завершилось за 900 с'


def run(post: Any, get: Any, cases: list[dict], outdir: Path) -> list[str]:
    """Прогоняет кейсы через API, скачивает и проверяет выгрузки; возвращает список провалов."""
    failures: list[str] = []
    lines = ['# Автопрогон открытых запросов', '', '| № | Статус | Проверки | Чек-лист | Время, с | ₽ |', '|---|---|---|---|---|---|']
    for case in cases:
        atts = [{'name': Path(a).name, 'content_base64': base64.b64encode((ROOT / a).read_bytes()).decode()} for a in case['attachments']]
        t0 = time.monotonic()
        resp = post('/api/v1/programs?mode=auto', json={'request': case['request'], 'attachments': atts, 'answers': case['answers']})
        dt = time.monotonic() - t0
        try:
            payload = resp.json()
        except ValueError:
            payload = {}
        r: dict[str, Any] = payload if isinstance(payload, dict) else {}
        if resp.status_code == 202:  # wait=false: приёмка дожидается результата задания
            t_job = time.monotonic()
            r, err = _job_result(get, r)
            dt += time.monotonic() - t_job
            if err:
                print(f'Запрос {case["id"]}: FAIL ({err})')
                lines.append(f'| {case["id"]} | задание | | | {dt:.0f} | |')
                failures.append(f'кейс {case["id"]}: {err}')
                continue
        elif resp.status_code != 200:
            print(f'Запрос {case["id"]}: FAIL, HTTP {resp.status_code}')
            lines.append(f'| {case["id"]} | HTTP {resp.status_code} | | | {dt:.0f} | |')
            failures.append(f'кейс {case["id"]}: HTTP {resp.status_code} вместо 200/202')
            continue
        missing = [k for k in PAYLOAD_KEYS if k not in r]
        if missing:
            print(f'Запрос {case["id"]}: FAIL, в ответе нет {", ".join(missing)}')
            lines.append(f'| {case["id"]} | неполный ответ | | | {dt:.0f} | |')
            failures.append(f'кейс {case["id"]}: в ответе нет {", ".join(missing)}')
            continue
        (outdir / f'case{case["id"]}.json').write_text(json.dumps(r, ensure_ascii=False, indent=1))
        checks = _checks(case, r)
        ok = sum(1 for _, v in checks if v)
        print(f'Запрос {case["id"]}: {r["status"]}, проверки {r["report"]["blocking_checks"]}, чек-лист {ok}/{len(checks)}, {dt:.1f} с, {r["tokens"]["cost_rub"]} ₽')
        for name, v in checks:
            print(f'   {"✓" if v else "✕"} {name}')
        lines.append(f'| {case["id"]} | {r["status"]} | {r["report"]["blocking_checks"]} | {ok}/{len(checks)} | {dt:.0f} | {r["tokens"]["cost_rub"]} |')
        # SPEC-API-30: конечный статус и каждый чек чек-листа обязательны
        if r.get('status') != 'done':
            failures.append(f'кейс {case["id"]}: статус {r.get("status")!r} вместо done')
        failures.extend(f'кейс {case["id"]}: чек провален — {name}' for name, v in checks if not v)
        # SPEC-API-30: каждая выгрузка скачивается и проверяется структурно
        for fmt in sorted(r.get('files', {})):
            path = '/api/v1/' + r['files'][fmt].split('/api/v1/', 1)[-1]
            er = get(path)
            if er.status_code != 200 or not er.content:
                failures.append(f'кейс {case["id"]}: выгрузка {fmt}: HTTP {er.status_code}')
                continue
            problems = export_problems(fmt, er.content)
            failures.extend(f'кейс {case["id"]}: выгрузка {fmt}: {p}' for p in problems)
    (outdir / 'summary.md').write_text('\n'.join(lines) + '\n')
    return failures


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='')
    ap.add_argument('--only', type=int, nargs='*')
    args = ap.parse_args()
    cases = json.loads((ROOT / 'testset' / 'cases.json').read_text())
    if args.only:
        cases = [c for c in cases if c['id'] in args.only]
    outdir = ROOT / 'logs' / 'autorun'
    outdir.mkdir(parents=True, exist_ok=True)
    if args.url:
        import httpx

        client = httpx.Client(base_url=args.url, timeout=1800)
        post, get = client.post, client.get
    else:
        from fastapi.testclient import TestClient

        from app.main import app

        tc = TestClient(app)
        tc.__enter__()
        post, get = tc.post, tc.get
    failures = run(post, get, cases, outdir)
    if failures:
        print('Автопрогон провален:')
        for f in failures:
            print(f'   ✕ {f}')
        return 1
    print('Автопрогон: все кейсы и выгрузки прошли')
    return 0


if __name__ == '__main__':
    sys.exit(main())
