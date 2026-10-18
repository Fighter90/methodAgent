"""Сценарии сверх основного потока: смена шаблона (FR-06), адаптация (FR-60), актуализация (FR-61),
сравнение версий (FR-38), песочница примеров (FR-46), задачи по ролям (FR-63), документы организации (FR-09)."""

from __future__ import annotations

import copy
import re
from importlib import metadata
from typing import Any

from app.agent import workflow as wf
from app.core.db import now_iso
from app.core.errors import BadRequest, Conflict
from app.kb import orgdocs
from app.kb.registry import tf_codes, tools
from app.programs.schemas import (
    Assumption,
    Kit,
    ProgramDoc,
    ProgramType,
    Source,
    Status,
)
from app.validation.report import build_report
from app.validation.sandbox import libraries, run_detailed

_EDITABLE = (Status.QUESTIONS, Status.SKELETON, Status.RETURNED)


# --------------------------------------------------------------------------- FR-06
def change_template(doc: ProgramDoc, program_type: str) -> None:
    """Методист меняет шаблон АЦР до утверждения каркаса: часы и разделы пересчитываются."""
    if doc.status not in _EDITABLE:
        raise Conflict('Шаблон меняется только до утверждения каркаса', code='SKELETON_LOCKED')
    try:
        ptype = ProgramType(program_type)
    except ValueError as exc:
        raise BadRequest(f'Неизвестный шаблон: {program_type}') from exc
    old = doc.template
    doc.params.program_type = ptype
    doc.params.no_classroom = ptype == ProgramType.DPP_PK_INTERNSHIP
    wf._classify(doc)
    if not doc.modules:
        return
    if ptype == ProgramType.DOOP:
        doc.profstandard = None
        for c in doc.competencies:
            c.ps_code, c.tf_codes = None, []
    elif doc.profstandard:
        codes = [t.code for t in doc.profstandard.tf] or sorted(tf_codes(doc.profstandard.code))
        for i, c in enumerate(doc.competencies):
            c.ps_code = doc.profstandard.code
            if codes and not c.tf_codes:
                c.tf_codes = [codes[i % len(codes)]]
    wf.apply_solver(doc, doc.modules)
    wf.plan_doc_calendar(doc)
    wf._resolve_slide_modules(doc)
    doc.report = build_report(doc, 'skeleton')
    doc.agent_notes.append(f'Шаблон сменён: «{old}» → «{doc.template}». Часы, разделы и выдаваемый документ пересчитаны.')


# --------------------------------------------------------------------------- FR-60
def adapt(src: ProgramDoc, new_id: str, *, volume_h: int | None, audience: str = '', title: str = '', duration_weeks: float | None = None) -> ProgramDoc:
    """Новая программа по готовой: граф компетенций и структура модулей сохраняются, часы пересчитываются солвером."""
    if not src.modules:
        raise Conflict('Адаптировать можно программу с каркасом', code='NO_SKELETON')
    if not volume_h and not audience.strip():
        raise BadRequest('Укажите новый объём или новую аудиторию')
    doc = copy.deepcopy(src)
    old_v = src.volume_h or 0
    doc.id = new_id
    doc.version = 1
    doc.mode = 'interactive'
    doc.created_at = now_iso()
    doc.status = Status.SKELETON
    p = doc.params
    if volume_h:
        if volume_h < 8 or volume_h > 2000:
            raise BadRequest('Объём от 8 до 2000 часов')
        p.volume_h = volume_h
        if p.duration_weeks and old_v and not duration_weeks:
            p.duration_weeks = max(1.0, round(p.duration_weeks * volume_h / old_v, 1))
        if p.min_practice_hours and old_v:
            p.min_practice_hours = round(p.min_practice_hours * volume_h / old_v)
        if p.materials.test_questions and old_v and volume_h < old_v:
            p.materials.test_questions = max(5, round(p.materials.test_questions * volume_h / old_v))
    if duration_weeks:
        p.duration_weeks = duration_weeks
    if audience.strip():
        p.audience = audience.strip()[:300]
    if title.strip():
        p.title = title.strip()[:200]
    doc.title = p.title or src.title
    doc.request = f'Адаптация программы «{src.title}»: {doc.title}, {p.volume_h or old_v} ч, аудитория — {p.audience or "прежняя"}'
    for m in doc.modules:
        m.expert_id, m.review_status = None, 'not_started'
    doc.kit = Kit()
    doc.decisions, doc.comments, doc.approvals, doc.questions = [], [], [], []
    doc.usage = type(doc.usage)()
    doc.timing_s, doc.progress = {}, {}
    doc.agent_notes = []
    doc.assumptions = [*src.assumptions, Assumption(field='source_program', value=src.id, source=f'адаптация «{src.title}», версия {src.version}')]
    wf.apply_solver(doc, doc.modules)
    wf.plan_doc_calendar(doc)
    wf._resolve_slide_modules(doc)
    doc.report = build_report(doc, 'skeleton')
    changes = []
    if volume_h and volume_h != old_v:
        changes.append(f'объём {old_v} → {volume_h} ч')
    if audience.strip() and audience.strip() != src.params.audience:
        changes.append(f'аудитория «{doc.params.audience}»')
    doc.agent_notes.insert(
        0,
        f'Адаптация программы «{src.title}»: {", ".join(changes) or "без изменения параметров"}. Компетенции, индикаторы и РО '
        f'сохранены ({len(doc.competencies)} компетенций, {len(doc.all_outcomes())} РО), часы модулей и тем пересчитаны солвером. '
        'Проверьте каркас и утвердите — комплект соберётся заново.',
    )
    return doc


# --------------------------------------------------------------------------- FR-61
_TOOL_ALIASES = {
    'python': r'python', 'pandas': r'pandas', 'numpy': r'numpy', 'matplotlib': r'matplotlib',
    'scikit-learn': r'scikit-learn|sklearn', 'postgresql': r'postgresql|postgres', 'docker': r'docker',
    'kubernetes': r'kubernetes|k8s', 'terraform': r'terraform', 'ansible-core': r'ansible(?:-core)?',
    'prometheus': r'prometheus', 'grafana': r'grafana', 'gitlab-ci': r'gitlab(?:-ci)?', 'nginx': r'nginx', 'jupyterlab': r'jupyterlab',
}


def _ver(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r'\d+', v)[:3])


def scan_text(text: str) -> list[dict[str, str]]:
    """Устаревшие конструкции, версии ниже поддерживаемых, недоступные в России сервисы, старые источники."""
    reg = tools()
    low = text.lower()
    out: list[dict[str, str]] = []
    seen: set[str] = set()

    def _add(kind: str, found: str, message: str, replacement: str) -> None:
        key = f'{kind}:{found.lower()}'
        if key not in seen:
            seen.add(key)
            out.append({'kind': kind, 'found': found, 'message': message, 'replacement': replacement})

    repl = reg.get('outdated_replacements', {})
    for key, msg in reg['outdated'].items():
        if key in low:
            _add('construct', key, msg, repl.get(key, ''))
    current, minimum = reg['current'], reg.get('min_supported', {})
    for tool, pattern in _TOOL_ALIASES.items():
        for m in re.finditer(rf'\b(?:{pattern})\s*v?(\d+(?:\.\d+)?)\b', low):
            v = m.group(1)
            if tool not in current or (tool == 'python' and _ver(v)[0] < 2):
                continue
            if tool in minimum and _ver(v) < _ver(minimum[tool]):
                _add('version', m.group(0), f'{tool} {v} снят с поддержки (минимум {minimum[tool]})', f'{tool} {current[tool]}')
            elif _ver(v)[:1] < _ver(current[tool])[:1] or (_ver(v) < _ver(current[tool]) and tool in ('python', 'pandas', 'postgresql', 'kubernetes')):
                _add('update', m.group(0), f'Есть более новая версия {tool}: {current[tool]}', f'{tool} {current[tool]}')
    for svc in reg.get('ai_services_blocked', []):
        if re.search(rf'\b{re.escape(svc.lower())}\b', low):
            _add('service', svc, f'{svc} недоступен в России без ограничений', 'GigaChat или YandexGPT (Алиса)')
    for y in re.findall(r'\b(19[5-9]\d|200\d|201[0-5])\b(?=\s*\.?\s*[–—-]?\s*\d*\s*с\.)', text):
        _add('source', y, f'Источник {y} года старше 10 лет', 'издание не старше 2016 года из реестра литературы')
    return out


def actualize_doc(doc: ProgramDoc) -> list[dict[str, Any]]:
    """Находки по узлам программы: тема, лекция, задание, вопрос, источник — с адресом для точечной правки."""
    found: list[dict[str, Any]] = []

    def _scan(node: str, where: str, text: str) -> None:
        for f in scan_text(text):
            found.append({**f, 'node_id': node, 'where': where})

    for m in doc.modules:
        _scan(m.id, f'Модуль {m.n}. {m.title}', m.title)
        for t in m.topics:
            _scan(t.id, f'Тема {t.n}. {t.title}', t.title)
    for lec in doc.kit.lectures:
        body = ' '.join([lec.title, *lec.code_examples, *(b for s in lec.slides for b in s.bullets), *(str(x.get('text', '')) for x in lec.plan)])
        _scan(lec.topic_id, f'Лекция «{lec.title}»', body)
    for mp in doc.kit.module_programs:
        _scan(mp.module_id, 'Программа модуля', mp.annotation)
    for t in doc.kit.tasks:
        _scan(t.id, t.title, f'{t.title} {t.statement}')
    for q in doc.kit.questions:
        _scan(q.id, f'Вопрос {q.id}', f'{q.stem} {" ".join(q.options)}')
    for s in doc.sources:
        _scan('', 'Список источников', s.bibl)
    for ref in doc.references:
        _scan('', f'Референс «{ref.name}»', ref.text_sample)
    return found


# --------------------------------------------------------------------------- FR-38
def _hours(h: Any) -> str:
    return f'ЛК {h.lk} · ПР {h.pr} · ЛБ {h.lb} · СРС {h.srs} = {h.total}'


def diff(a: ProgramDoc, b: ProgramDoc) -> dict[str, Any]:
    """Что изменилось от версии a к версии b: поля, модули, темы, РО и узлы комплекта."""
    ch: list[dict[str, str]] = []

    def _cmp(kind: str, label: str, x: Any, y: Any) -> None:
        if x != y:
            ch.append({'kind': kind, 'label': label, 'before': str(x if x not in (None, '') else '—'), 'after': str(y if y not in (None, '') else '—')})

    _cmp('field', 'Название', a.title, b.title)
    _cmp('field', 'Статус', a.status.value, b.status.value)
    _cmp('field', 'Шаблон', a.template, b.template)
    _cmp('field', 'Объём, ч', a.volume_h, b.volume_h)
    _cmp('field', 'Цель', a.goal, b.goal)
    _cmp('field', 'Итоговая аттестация', f'{a.final_assessment.form}, {a.final_assessment.hours} ч', f'{b.final_assessment.form}, {b.final_assessment.hours} ч')
    _cmp('field', 'Календарь', f'{a.calendar.weeks} нед., {a.calendar.hours_per_day} ч/день', f'{b.calendar.weeks} нед., {b.calendar.hours_per_day} ч/день')
    am, bm = {m.id: m for m in a.modules}, {m.id: m for m in b.modules}
    for mid in [*am, *(x for x in bm if x not in am)]:
        x, y = am.get(mid), bm.get(mid)
        if x and not y:
            ch.append({'kind': 'module', 'label': f'Модуль {x.n}', 'before': x.title, 'after': 'удалён'})
            continue
        if y and not x:
            ch.append({'kind': 'module', 'label': f'Модуль {y.n}', 'before': 'нет', 'after': y.title})
            continue
        _cmp('module', f'Модуль {y.n}: название', x.title, y.title)
        _cmp('hours', f'Модуль {y.n}: часы', _hours(x.hours), _hours(y.hours))
        at, bt = {t.id: t for t in x.topics}, {t.id: t for t in y.topics}
        for tid in [*at, *(t for t in bt if t not in at)]:
            tx, ty = at.get(tid), bt.get(tid)
            if tx and not ty:
                ch.append({'kind': 'topic', 'label': f'Тема {tx.n}', 'before': tx.title, 'after': 'удалена'})
            elif ty and not tx:
                ch.append({'kind': 'topic', 'label': f'Тема {ty.n}', 'before': 'нет', 'after': ty.title})
            else:
                _cmp('topic', f'Тема {ty.n}: название', tx.title, ty.title)
                _cmp('hours', f'Тема {ty.n}: часы', _hours(tx.hours), _hours(ty.hours))
    ac, bc = {c.id: c for c in a.competencies}, {c.id: c for c in b.competencies}
    for cid, y in bc.items():
        x = ac.get(cid)
        _cmp('competency', f'{y.code}', x.title if x else 'нет', y.title)
    alo, blo = {lo.id: lo for lo in a.all_outcomes()}, {lo.id: lo for lo in b.all_outcomes()}
    for lid, y in blo.items():
        x = alo.get(lid)
        _cmp('outcome', y.code, x.text if x else 'нет', y.text)
    ha, hb = wf.kit_hashes(a), wf.kit_hashes(b)
    kit_changed = sorted(k for k in hb if k in ha and ha[k] != hb[k] and ':' not in k)
    kit_added = sorted(k for k in hb if k not in ha and ':' not in k)
    kit_removed = sorted(k for k in ha if k not in hb and ':' not in k)
    return {
        'a': a.version, 'b': b.version, 'changes': ch,
        'kit': {'changed': kit_changed, 'added': kit_added, 'removed': kit_removed},
        'summary': {
            'fields': len(ch), 'kit_changed': len(kit_changed), 'kit_added': len(kit_added), 'kit_removed': len(kit_removed),
            'blocking_a': a.report.blocking_passed if a.report else 0, 'blocking_b': b.report.blocking_passed if b.report else 0,
        },
    }


# --------------------------------------------------------------------------- FR-46
def _lib_version(name: str) -> str:
    dist = {'sklearn': 'scikit-learn'}.get(name, name)
    current = tools()['current']
    if dist in current:
        return current[dist]
    try:
        return metadata.version(dist)
    except metadata.PackageNotFoundError:
        return ''


def sandbox_report(doc: ProgramDoc, limit: int = 20) -> dict[str, Any]:
    """Каждый пример кода из лекций: результат запуска, версии библиотек, время, устаревшие конструкции."""
    import platform

    items = []
    for lec in doc.kit.lectures:
        for i, code in enumerate(lec.code_examples):
            if len(items) >= limit:
                break
            r = run_detailed(code)
            libs = [{'name': n, 'version': _lib_version(n)} for n in libraries(code)]
            outdated = [f for f in scan_text(code) if f['kind'] in ('construct', 'version')]
            items.append({'lecture': lec.title, 'topic_id': lec.topic_id, 'module_id': lec.module_id, 'n': i + 1, 'code': code[:3000], **r, 'libs': libs, 'outdated': outdated})
    return {
        'python': platform.python_version(),
        'checked': len(items),
        'failed': sum(1 for x in items if not x['ok']),
        'outdated': sum(len(x['outdated']) for x in items),
        'items': items,
    }


# --------------------------------------------------------------------------- FR-63
def tasks_for(docs: list[ProgramDoc], user_id: str, role: str) -> int:
    if role == 'methodist':
        open_states = {Status.QUESTIONS, Status.SKELETON, Status.RETURNED, Status.KIT_READY}
        n = sum(1 for d in docs if d.status in open_states)
        n += sum(1 for d in docs for c in d.comments if c.status == 'open')
        return n
    if role == 'expert':
        return sum(1 for d in docs for m in d.modules if m.expert_id == user_id and m.review_status not in ('accepted',))
    if role == 'head':
        return sum(1 for d in docs if d.status == Status.ON_APPROVAL)
    return 0


# --------------------------------------------------------------------------- нормативная база знаний
def apply_norms(doc: ProgramDoc) -> list[dict[str, Any]]:
    """Выдержки НПА и ФГОС под запрос: идут в промпты каркаса и комплекта, акт — в нормативную базу программы."""
    from app.kb import norms
    from app.kb.registry import _stems_hit, registry

    if doc.type is None:
        return []
    p = doc.params
    query = ' '.join([doc.request, p.title, p.direction, p.audience, p.form, p.final_assessment_form, ' '.join(p.required_topics)])
    npa = {i['id']: i for i in registry()['npa']}
    low = query.lower()
    known = {s.id for s in doc.norm_base}

    def relevant(npa_id: str) -> bool:
        # выдержки акта идут в промпт, только если сам акт относится к запросу (как в norm_base_for): ДОТ — при дистанционке, СанПиН — для детей
        item = npa.get(npa_id)
        return not npa_id or npa_id in known or bool(item and (item.get('core') or _stems_hit(item.get('keywords', []), low)))

    hits = [h for h in norms.search(query, doc.type.value, k=12) if relevant(h['npa_id'])][:4]
    doc.norm_fragments = [{'name': h['name'], 'text': h['text'], 'doc_id': h['doc_id']} for h in hits]
    for h in hits:
        item = npa.get(h['npa_id'])
        if item and item['id'] not in known and doc.type.value in item.get('applies', []):
            known.add(item['id'])
            doc.norm_base.append(Source(id=item['id'], kind='law', bibl=item['bibl'], url=item.get('url', ''), confirmed=True, checked_at=item.get('checked_at', '')))
    if hits:
        names = ', '.join(dict.fromkeys(f'«{h["name"]}»' for h in hits))
        doc.agent_notes.append(f'Опираюсь на нормативную базу знаний: {names}.')
    return hits


# --------------------------------------------------------------------------- FR-09
async def apply_org_docs(doc: ProgramDoc) -> list[dict[str, Any]]:
    """Режим «документы организации»: находит фрагменты положений и шаблонов и ссылается на них."""
    if doc.norm_mode != 'org':
        return []
    query = ' '.join([doc.request, doc.params.title, doc.params.direction, ' '.join(doc.params.required_topics)])
    hits = await orgdocs.search(query, k=4)
    if not hits:
        doc.agent_notes.append('Режим «документы организации»: база знаний пуста или не нашла подходящих фрагментов — использованы госстандарты.')
        return []
    known = {s.id for s in doc.norm_base}
    for h in hits:
        sid = f'{h["doc_id"]}#{h["chunk"]}'
        if h['doc_id'] in known or sid in known:
            continue
        known.add(h['doc_id'])
        doc.norm_base.append(Source(id=h['doc_id'], kind='doc', bibl=f'{h["name"]} (документ организации)', confirmed=True, checked_at=now_iso()[:10]))
    doc.org_fragments = [{'name': h['name'], 'text': h['text']} for h in hits]
    names = ', '.join(dict.fromkeys(f'«{h["name"]}»' for h in hits))
    doc.agent_notes.append(f'Использую документы организации: {names}. Ссылки добавлены в нормативную базу.')
    tpl = orgdocs.templates()
    if tpl and not any(r.structure for r in doc.references):
        from app.programs.schemas import ReferenceInfo

        doc.references.append(ReferenceInfo(name=tpl[0]['name'], structure=tpl[0].get('structure', [])))
    return hits


# --------------------------------------------------------------------------- FR-39
def suggest_experts(doc: ProgramDoc) -> dict[str, Any]:
    """Подсказка экспертов из профиля: совпадение навыков с темами модуля, при равенстве — меньшая нагрузка."""
    from app.core.security import users
    from app.kb.registry import org_profile

    prof = org_profile().get('experts') or []
    known = {e['id']: e for e in prof}
    experts = [
        {'id': u.id, 'name': u.name, 'title': u.title, 'skills': known.get(u.id, {}).get('skills', [])}
        for u in users().values() if 'expert' in u.roles
    ]
    load = {e['id']: 0 for e in experts}
    out = []
    for m in doc.modules:
        text = (m.title + ' ' + ' '.join(t.title + ' ' + t.description for t in m.topics)).lower()
        scored = sorted(experts, key=lambda e: (-sum(1 for s in e['skills'] if s in text), load[e['id']]))
        best = scored[0] if scored else None
        if best:
            load[best['id']] += 1
            hits = [s for s in best['skills'] if s in text]
            out.append({'module_id': m.id, 'expert_id': best['id'], 'reason': f'совпадение по темам: {", ".join(hits[:3])}' if hits else 'по нагрузке'})
    return {'experts': experts, 'suggestions': out}
