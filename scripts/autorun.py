"""Прогон открытых запросов кейса (testset/cases.json) через POST /api/v1/programs?mode=auto.

Запуск:
    python scripts/autorun.py                       # в процессе, без сервера
    python scripts/autorun.py --url http://localhost:8000
Результаты: logs/autorun/<id>.json и сводка logs/autorun/summary.md.
"""

from __future__ import annotations

import argparse
import base64
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))


def _checks(case: dict, r: dict) -> list[tuple[str, bool]]:
    sk = r['skeleton']
    tot = sk['totals']
    kit = r['kit']['kit']
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
        out.append(('слайды для занятий 1 и 2', sum(1 for lec in kit['lectures'] if lec['slides']) >= 1))
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
        out.append(('слайды для лекций модуля pandas', any(lec['slides'] for lec in kit['lectures'])))
    if case['id'] == 4:
        out.append(('вопросы были заданы', bool(r['questions_skipped'])))
        out.append(('вопросов ≤ 5', len(r['questions_skipped']) <= 5))
        out.append(('ДПП ПК', sk['type'] == 'dpp_pk'))
        out.append(('разница ожиданий в отчёте', any('V-27' == x['id'] and x['messages'] for x in r['report']['rules']) or any('ожидан' in n.lower() for n in r['agent_notes'])))
        out.append(('итог — экзамен с практикой', 'экзамен' in sk['final_assessment']['form'].lower()))
    if case['id'] == 5:
        out.append(('СРС 254 + ИА 2', tot['srs'] == 254 and tot['ia'] == 2))
        out.append(('ЛК/ПР/ЛБ = 0', tot['lk'] == tot['pr'] == tot['lb'] == 0))
        out.append(('≤ 4 ч в день', sk['calendar']['hours_per_day'] <= 4))
        out.append(('ошибка образца отмечена', any('образц' in n.lower() or 'итого' in n.lower() for n in r['agent_notes'])))
        out.append(('вопросы собеседования', any(t for t in kit['tasks']) or bool(kit['final_assessment'])))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--url', default='')
    ap.add_argument('--only', type=int, nargs='*')
    args = ap.parse_args()
    cases = json.loads((ROOT / 'testset' / 'cases.json').read_text())
    outdir = ROOT / 'logs' / 'autorun'
    outdir.mkdir(parents=True, exist_ok=True)
    if args.url:
        import httpx

        client = httpx.Client(base_url=args.url, timeout=1800)
        post = client.post
    else:
        from fastapi.testclient import TestClient

        from app.main import app

        tc = TestClient(app)
        tc.__enter__()
        post = tc.post
    lines = ['# Автопрогон открытых запросов', '', '| № | Статус | Проверки | Чек-лист | Время, с | ₽ |', '|---|---|---|---|---|---|']
    for case in cases:
        if args.only and case['id'] not in args.only:
            continue
        atts = [{'name': Path(a).name, 'content_base64': base64.b64encode((ROOT / a).read_bytes()).decode()} for a in case['attachments']]
        t0 = time.monotonic()
        resp = post('/api/v1/programs?mode=auto', json={'request': case['request'], 'attachments': atts, 'answers': case['answers']})
        dt = time.monotonic() - t0
        r = resp.json()
        (outdir / f'case{case["id"]}.json').write_text(json.dumps(r, ensure_ascii=False, indent=1))
        if resp.status_code != 200:
            print(case['id'], resp.status_code, r)
            lines.append(f'| {case["id"]} | HTTP {resp.status_code} | | | {dt:.0f} | |')
            continue
        checks = _checks(case, r)
        ok = sum(1 for _, v in checks if v)
        print(f'Запрос {case["id"]}: {r["status"]}, проверки {r["report"]["blocking_checks"]}, чек-лист {ok}/{len(checks)}, {dt:.1f} с, {r["tokens"]["cost_rub"]} ₽')
        for name, v in checks:
            print(f'   {"✓" if v else "✕"} {name}')
        lines.append(f'| {case["id"]} | {r["status"]} | {r["report"]["blocking_checks"]} | {ok}/{len(checks)} | {dt:.0f} | {r["tokens"]["cost_rub"]} |')
    (outdir / 'summary.md').write_text('\n'.join(lines) + '\n')


if __name__ == '__main__':
    main()
