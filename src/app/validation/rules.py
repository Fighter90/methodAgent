"""27 правил автопроверки (ТЗ, таблица 17): 23 кодом и 4 моделью-судьёй.

Правила — чистые функции над ProgramDoc без базы данных. Результат каждого
правила хранит ссылки на узлы графа, чтобы из отчёта перейти к элементу.
Правила судьи (V-21, V-22, V-26, V-27) здесь реализованы эвристиками;
validation/judge.py уточняет их моделью, если судья включён.
"""

from __future__ import annotations

import datetime
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass

from app.kb.registry import match_source, registry, tf_codes
from app.programs.schemas import KINDS, ProgramDoc, ProgramType, Question_, RuleResult
from app.validation.ngrams import overlap_share, similarity

logger = logging.getLogger(__name__)

SKELETON_RULES = {'V-01', 'V-02', 'V-03', 'V-04', 'V-05', 'V-06', 'V-07', 'V-08', 'V-10', 'V-12', 'V-13', 'V-15', 'V-21', 'V-22', 'V-27'}

KIND_RU = {'lk': 'ЛК', 'pr': 'ПР', 'lb': 'ЛБ', 'srs': 'СРС', 'total': 'всего'}

# Разделы шаблона АЦР (V-08). ДПП ПК — 19 разделов, ДООП — по приказу № 629 и образцу интенсива.
# Разделы шаблонов АЦР: (ключ, заголовок, уровень). Уровень 1 — раздел или приложение, 2 — подраздел, 3 — пункт.
# Заголовки и нумерация совпадают с образцами ДПП ПК (стажировка 248 ч) и ДООП (интенсив 24 ч).
SECTIONS_DPP = [
    ('g1', '1. ОБЩАЯ ХАРАКТЕРИСТИКА ДОПОЛНИТЕЛЬНОЙ ПРОФЕССИОНАЛЬНОЙ ПРОГРАММЫ', 1),
    ('annotation', '1.1. Аннотация программы', 2),
    ('goal', '1.2. Цель реализации программы', 2),
    ('results', '1.3. Планируемые результаты обучения (РО)', 2),
    ('ps', '1.4. Программа разработана на основе:', 2),
    ('competencies_list', '1.5. Перечень профессиональных компетенций в рамках имеющейся квалификации, качественное изменение которых осуществляется в результате обучения:', 2),
    ('audience', '1.6. Требования к слушателям (категории слушателей)', 2),
    ('form', '1.7. Форма обучения', 2),
    ('volume', '1.8. Объём программы', 2),
    ('document', '1.9. Выдаваемый документ', 2),
    ('g2', '2. СОДЕРЖАНИЕ ПРОГРАММЫ', 1),
    ('curriculum', '2.1. Учебный план', 2),
    ('utp', '2.2. Учебно-тематический план', 2),
    ('calendar', '2.3. Календарный учебный график', 2),
    ('content', '2.4. Рабочая программа учебных дисциплин', 2),
    ('assessment', '2.5. Оценка качества освоения программы', 2),
    ('attestation_forms', '2.5.1. Форма(ы) текущей, промежуточной и итоговой аттестации', 3),
    ('assessment_materials', '2.5.2. Оценочные материалы', 3),
    ('quality', '2.5.3. Анализ удовлетворённости требований слушателей', 3),
    ('g3', '3. ОРГАНИЗАЦИОННО-ПЕДАГОГИЧЕСКИЕ УСЛОВИЯ РЕАЛИЗАЦИИ ПРОГРАММЫ', 1),
    ('conditions_mt', '3.1. Материально-техническое обеспечение', 2),
    ('conditions_it', '3.2. Учебно-методическое и информационное обеспечение', 2),
    ('lit_npa', '3.2.1. Нормативно-правовые документы', 3),
    ('lit_main', '3.2.2. Основная литература', 3),
    ('lit_extra', '3.2.3. Дополнительная литература', 3),
    ('lit_web', '3.2.4. Интернет-ресурсы', 3),
    ('software', '3.2.5. Программное обеспечение и информационные системы', 3),
    ('process', '3.3. Организация образовательного процесса', 2),
    ('conditions_org', '3.4. Кадровое обеспечение образовательного процесса', 2),
    ('app1', 'Приложение 1', 1),
    ('app2', 'Приложение 2', 1),
]
SECTIONS_DOOP = [
    ('annotation', '1. Пояснительная записка', 1),
    ('relevance', '1.1. Актуальность Программы', 2),
    ('audience', '1.2. Категории обучающихся', 2),
    ('goal', '1.3. Цель и задачи программы', 2),
    ('volume', '1.4. Сроки реализации', 2),
    ('results', '1.5. Планируемые результаты обучения', 2),
    ('calendar', '1.6. Календарный учебный график', 2),
    ('g2', '2. Содержание программы', 1),
    ('curriculum', '2.1. Учебный план', 2),
    ('utp', '2.2. Учебно-тематический план', 2),
    ('assessment', '2.3. Оценочные материалы', 2),
    ('methodical', '2.4. Методические материалы', 2),
    ('g3', '3. Организационно-педагогические условия реализации программы', 1),
    ('conditions_mt', '3.1. Материально-технические условия реализации программы', 2),
    ('conditions_it', '3.2. Учебно-методическое и информационное обеспечение программы', 2),
    ('literature', '3.3. Литература', 2),
    ('lit_main', '3.3.1. Основная литература', 3),
    ('lit_extra', '3.3.2. Дополнительная литература', 3),
    ('lit_web', '3.3.3. Интернет-ресурсы', 3),
    ('conditions_org', '3.4. Кадровое обеспечение программы', 2),
    ('app1', 'Приложение № 1', 1),
]
# Заголовки групп без собственного текста — в проверке полноты не участвуют
GROUP_KEYS = {'g1', 'g2', 'g3'}
TEMPLATE_FORMULA_KEYS = {'approval', 'ps', 'norm', 'lit_npa', 'lit_main', 'lit_extra', 'lit_web', 'software', 'document', 'assessment_materials', 'quality', 'audience', 'app1', 'app2'}

FORBIDDEN_FILLED = ('приказ №', 'фио преподавателя', 'подпись')

CHECK_TITLES = {
    1: 'Арифметика часов',
    2: 'Полнота шаблона',
    3: 'Календарная выполнимость',
    4: 'Поля для людей',
    5: 'Покрытие компетенций',
    6: 'Привязка оценивания к РО',
    7: 'Источники',
    8: 'Оригинальность',
    9: 'Измеримость заданий',
    10: 'Точечная правка без регрессий',
}


def sections_for(doc: ProgramDoc) -> list[tuple[str, str, int]]:
    return SECTIONS_DOOP if doc.type == ProgramType.DOOP else SECTIONS_DPP


@dataclass
class Rule:
    id: str
    title: str
    check: int | None
    kind: str
    fn: Callable[[ProgramDoc, str], tuple[str, list[str], list[str]]]


def _ok() -> tuple[str, list[str], list[str]]:
    return 'pass', [], []


# --- Блокирующая проверка 1. Арифметика часов ---
def v01(doc: ProgramDoc, stage: str):
    msgs, nodes = [], []
    for m in doc.modules:
        for k in ('total', *KINDS):
            s = sum(getattr(t.hours, k) for t in m.topics)
            if m.topics and s != getattr(m.hours, k):
                msgs.append(f'Модуль {m.n}: сумма тем {KIND_RU[k]} {s} ч, в модуле {getattr(m.hours, k)} ч')
                nodes.append(m.id)
    return ('fail' if msgs else 'pass'), msgs, nodes


def v02(doc: ProgramDoc, stage: str):
    msgs, nodes = [], []
    for m in doc.modules:
        if m.hours.kinds_sum() != m.hours.total:
            msgs.append(f'Модуль {m.n}: по видам работы {m.hours.kinds_sum()} ч, всего {m.hours.total} ч')
            nodes.append(m.id)
        for t in m.topics:
            if t.hours.kinds_sum() != t.hours.total:
                msgs.append(f'Тема {t.n}: по видам работы {t.hours.kinds_sum()} ч, всего {t.hours.total} ч')
                nodes.append(t.id)
    return ('fail' if msgs else 'pass'), msgs, nodes


def v03(doc: ProgramDoc, stage: str):
    tot = doc.totals()
    msgs = []
    for k in KINDS:
        s = sum(getattr(m.hours, k) for m in doc.modules)
        if s != getattr(tot, k):
            msgs.append(f'{KIND_RU[k]}: по модулям {s} ч, в итоге {getattr(tot, k)} ч')
    if tot.kinds_sum() != tot.total:
        msgs.append(f'Итоговая строка: по видам работы {tot.kinds_sum()} ч, всего {tot.total} ч')
    return ('fail' if msgs else 'pass'), msgs, []


def v04(doc: ProgramDoc, stage: str):
    tot = doc.totals().total
    if tot + doc.final_assessment.hours != doc.volume_h:
        return 'fail', [f'Итог {tot} ч и ИА {doc.final_assessment.hours} ч не равны {doc.volume_h} ч'], []
    return _ok()


def v05(doc: ProgramDoc, stage: str):
    contact = doc.totals().contact
    text = doc.kit.sections.get('volume', '')
    m = re.search(r'контактн\w+\s+работ\w*[^0-9]{0,30}(\d+)', text.lower())
    if stage == 'kit' and m and int(m.group(1)) != contact:
        return 'fail', [f'В тексте {m.group(1)} ч контактной работы, в плане {contact} ч ЛК, ПР и ЛБ'], ['section:volume']
    return _ok()


def v06(doc: ProgramDoc, stage: str):
    if doc.type != ProgramType.DPP_PK_INTERNSHIP:
        return _ok()
    msgs, nodes = [], []
    for m in doc.modules:
        for t in m.topics:
            if t.hours.contact:
                msgs.append(f'Стажировка: в теме {t.n} указано {t.hours.contact} ч аудиторной работы')
                nodes.append(t.id)
    if doc.totals().contact:
        msgs.append('Стажировка: в итоговой строке есть аудиторные часы')
    return ('fail' if msgs else 'pass'), msgs, nodes


def v07(doc: ProgramDoc, stage: str):
    if doc.type == ProgramType.DPP_PK_INTERNSHIP:
        return _ok()
    tot = doc.totals()
    need = doc.min_practice_hours
    if need and tot.pr + tot.lb < need:
        return 'fail', [f'Практики {tot.pr + tot.lb} ч, в запросе не меньше {need} ч'], []
    if doc.type == ProgramType.DPP_PK and tot.contact and (tot.pr + tot.lb) / tot.contact < 0.4:
        return 'fail', [f'Практика {tot.pr + tot.lb} ч из {tot.contact} аудиторных — меньше 40 %'], []
    return _ok()


# --- 2. Полнота шаблона ---
def v08(doc: ProgramDoc, stage: str):
    if stage == 'skeleton':
        missing = []
        if not doc.goal:
            missing.append('Цель программы')
        if not doc.competencies:
            missing.append('Компетенции')
        if not doc.modules:
            missing.append('Учебный план')
        if not doc.final_assessment.form:
            missing.append('Итоговая аттестация')
        return ('fail' if missing else 'pass'), [f'Не заполнено: {x}' for x in missing], []
    missing = [title for key, title, _lvl in sections_for(doc) if key not in GROUP_KEYS and not doc.kit.sections.get(key, '').strip()]
    return ('fail' if missing else 'pass'), [f'Не заполнен раздел «{x}»' for x in missing], [f'section:{x}' for x in missing]


def v09(doc: ProgramDoc, stage: str):
    # Блокирующая часть — отсутствие запрошенных материалов; пустые пункты слайда — только предупреждение (SPEC-RULES-22)
    hard, warns, nodes = [], [], []
    mat = doc.params.materials
    if mat.test_questions:
        final_qs = [q for q in doc.kit.questions if q.assessment_id == 'test-final']
        if len(final_qs) != mat.test_questions:
            hard.append(f'В запросе {mat.test_questions} вопросов, в итоговом тесте {len(final_qs)}')
    if not any(lec.slides for lec in doc.kit.lectures):
        hard.append('Нет ни одного модуля со слайдами')
    topic_titles = {t.id: t.title for t in doc.all_topics()}
    for lec in doc.kit.lectures:
        if lec.topic_id not in topic_titles:
            hard.append(f'Лекция «{lec.title}» не соответствует теме УТП')
            nodes.append(lec.id)
        elif lec.title.strip().lower() != topic_titles[lec.topic_id].strip().lower():
            hard.append(f'Тема лекции «{lec.title}» не совпадает с темой УТП «{topic_titles[lec.topic_id]}»')
            nodes.append(lec.id)
        for sl in lec.slides:
            if not any(str(b).strip() for b in sl.bullets):
                warns.append(f'Слайд {sl.id} «{sl.title[:40]}» без пунктов')
                nodes.append(sl.id)
    for mod_n in mat.slides_modules:
        mod = next((m for m in doc.modules if m.n == mod_n), None)
        if mod and not any(lec.module_id == mod.id and lec.slides for lec in doc.kit.lectures):
            hard.append(f'Нет слайдов для модуля {mod_n}, указанного в запросе')
    status = 'fail' if hard else ('warn' if warns else 'pass')
    return status, hard + warns, nodes


# --- 3. Календарь ---
def v10(doc: ProgramDoc, stage: str):
    cal = doc.calendar
    if cal.conflict and not cal.chosen_option:
        return 'fail', [cal.conflict + ' — выберите вариант'], ['calendar']
    max_day = doc.params.max_hours_per_day
    if max_day and cal.hours_per_day > max_day:
        return 'fail', [f'Нагрузка {cal.hours_per_day} ч в день выше ограничения {max_day} ч'], ['calendar']
    msgs = []
    if cal.chosen_option:
        opt = next((o for o in cal.options if o.id == cal.chosen_option), None)
        if opt:
            msgs.append(f'Конфликт срока решён: {opt.title}')
    return ('warn' if msgs else 'pass'), msgs, []


# --- 4. Поля для людей ---
_FILLED = [
    re.compile(r'приказ\w*\s*№\s*\d', re.IGNORECASE),
    re.compile(r'от\s*«\d{1,2}»', re.IGNORECASE),
    re.compile(r'[А-ЯЁ][а-яё]+\s+[А-ЯЁ]\.\s?[А-ЯЁ]\.'),
]


def v11(doc: ProgramDoc, stage: str):
    # Кадровое обеспечение (3.4) — место, где модель могла бы вписать ФИО преподавателей
    text = ' '.join(doc.kit.sections.get(k, '') for k in ('approval', 'authors', 'document', 'conditions_org'))
    for rx in _FILLED:
        if rx.search(text):
            return 'fail', ['Реквизиты приказа, ФИО преподавателей и подписи должны остаться пустыми полями'], ['section:approval']
    return _ok()


# --- 5. Покрытие ---
def v12(doc: ProgramDoc, stage: str):
    covered = {lo_id for t in doc.all_topics() for lo_id in t.lo_ids}
    miss = [lo for lo in doc.all_outcomes() if lo.id not in covered]
    return ('fail' if miss else 'pass'), [f'{lo.code} не раскрыт ни в одной теме' for lo in miss], [lo.id for lo in miss]


_META_STEM_RX = re.compile(
    r'что\s+(?:слушател\w+|обучающ\w+|студент\w*|курсант\w*)\s+должен\s+уметь'
    r'|какова\s+цель\s+(?:этой\s+)?(?:темы|занятия|модуля|урока)',
    re.IGNORECASE,
)


def _meta_question(doc: ProgramDoc, q: Question_) -> bool:
    """MET-51/R07: чистая метапостановка — «Что слушатель должен уметь…?» без предметных слов РО.

    Верный ответ в таком вопросе угадывается по теме, само действие не проверяется,
    поэтому средством V-13 вопрос не считается. Если в стеме есть предметный фрагмент РО
    (4 слова подряд из его текста), вопрос остаётся средством.
    """
    if not _META_STEM_RX.search(q.stem):
        return False
    stem = ' '.join(re.findall(r'[а-яёa-z0-9_]+', q.stem.lower()))
    words = [w for lo in doc.all_outcomes() if lo.id in q.lo_ids for w in re.findall(r'[а-яёa-z0-9_]+', lo.text.lower())]
    return not any(' '.join(words[i:i + 4]) in stem for i in range(max(0, len(words) - 3)))


def assessment_map(doc: ProgramDoc) -> dict[str, set[str]]:
    """РО → множество оценочных средств, которыми он проверяется.

    Вопрос-метапостановка без предметных слов РО средством не считается (MET-51/R07).
    """
    res: dict[str, set[str]] = {lo.id: set() for lo in doc.all_outcomes()}
    for q in doc.kit.questions:
        if _meta_question(doc, q):
            continue
        for lo_id in q.lo_ids:
            res.setdefault(lo_id, set()).add(q.assessment_id)
    for t in doc.kit.tasks:
        for lo_id in t.lo_ids:
            res.setdefault(lo_id, set()).add(t.assessment_id)
    return res


def planned_assessment_map(doc: ProgramDoc) -> dict[str, set[str]]:
    """На этапе каркаса: средства по плану — контроль модуля и итоговая аттестация."""
    res: dict[str, set[str]] = {lo.id: set() for lo in doc.all_outcomes()}
    for m in doc.modules:
        for t in m.topics:
            for lo_id in t.lo_ids:
                res.setdefault(lo_id, set()).add(f'ctrl-{m.id}')
                if t.hours.pr + t.hours.lb > 0 or doc.type == ProgramType.DPP_PK_INTERNSHIP:
                    res[lo_id].add(f'sem-{m.id}')
    if doc.final_assessment.form:
        for lo_id in res:
            res[lo_id].add('final')
    return res


def v13(doc: ProgramDoc, stage: str):
    amap = planned_assessment_map(doc) if stage == 'skeleton' else assessment_map(doc)
    codes = {lo.id: lo.code for lo in doc.all_outcomes()}
    weak = [(lo_id, means) for lo_id, means in amap.items() if lo_id in codes and len(means) < 2]
    msgs = [f'{codes[lo_id]} проверяется {len(m)} средством(ами), нужно не меньше двух' for lo_id, m in weak]
    # MET-51/R07: вопрос-метапостановка средством не считается — честный статус и пометка для вычитки
    meta = [q.id for q in doc.kit.questions if _meta_question(doc, q)]
    msgs += [f'Вопрос {q}: метапостановка без предметных слов из РО — средством не считается, нужна вычитка эксперта' for q in meta]
    if weak:
        return 'fail', msgs, [lo_id for lo_id, _ in weak]
    return ('warn' if meta else 'pass'), msgs, []


# --- 6. Привязка оценивания ---
def v14(doc: ProgramDoc, stage: str):
    ids = {lo.id for lo in doc.all_outcomes()}
    bad = [q.id for q in doc.kit.questions if not q.lo_ids or any(x not in ids for x in q.lo_ids)]
    bad += [t.id for t in doc.kit.tasks if not t.lo_ids or any(x not in ids for x in t.lo_ids)]
    return ('fail' if bad else 'pass'), [f'{x}: не привязан к существующему РО' for x in bad[:20]], bad


# --- 7. Источники ---
def v15(doc: ProgramDoc, stage: str):
    msgs, nodes = [], []
    if doc.type == ProgramType.DOOP:
        if doc.profstandard or any(c.ps_code for c in doc.competencies):
            msgs.append('В ДООП не должно быть раздела профстандартов')
        return ('fail' if msgs else 'pass'), msgs, nodes
    if not doc.profstandard:
        return 'fail', ['Для ДПП ПК не выбран профстандарт из реестра'], []
    valid = tf_codes(doc.profstandard.code)
    if not valid:
        return 'fail', [f'ПС {doc.profstandard.code} не найден в реестре'], []
    for c in doc.competencies:
        for code in c.tf_codes:
            if code not in valid:
                msgs.append(f'Код ТФ {code} не найден в ПС {doc.profstandard.code}')
                nodes.append(c.id)
    if msgs:
        return 'fail', msgs, nodes
    if not doc.profstandard.confirmed:
        return 'warn', [f'Коды ТФ ПС {doc.profstandard.code} взяты из реестра, но помечены «сверить с реестром Минтруда»'], []
    return _ok()


def v16(doc: ProgramDoc, stage: str):
    unconfirmed = [s for s in doc.sources if not s.confirmed]
    for s in doc.sources:
        if not s.confirmed and match_source(s.bibl):
            s.confirmed = True
    still = [s for s in unconfirmed if not s.confirmed]
    unmarked = [s for s in still if 'не подтверждено' not in s.bibl]
    if unmarked:
        return 'fail', [f'Источник «{s.bibl[:60]}» не найден и не помечен' for s in unmarked], [s.id for s in unmarked]
    if still:
        return 'warn', [f'{len(still)} источник(а) не найдено в реестре — помечены «не подтверждено»'] + _stale_registry_warn(), [s.id for s in still]
    status, ok_msg, nodes = _ok()
    stale = _stale_registry_warn()
    return ('warn', [*ok_msg, *stale], nodes) if stale else _ok()


def _stale_registry_warn() -> list[str]:
    """MET-10: реестр с датой проверки старше 180 дней — предупреждение в отчёте V-16."""
    stale_kinds = []
    limit = (datetime.date.today() - datetime.timedelta(days=180)).isoformat()
    for kind in ('npa', 'ps', 'literature'):
        items = registry().get(kind) or []
        dates = [i.get('checked_at', '') for i in items if i.get('checked_at')]
        if items and (not dates or min(dates) < limit):
            stale_kinds.append(kind)
    if not stale_kinds:
        return []
    return [f'Реестр ({", ".join(stale_kinds)}) не обновлялся более 180 дней — проверьте актуальность нормативной базы']


# --- 8. Оригинальность ---
def v17(doc: ProgramDoc, stage: str):
    ref = ' '.join(r.text_sample for r in doc.references)
    if not ref.strip():
        return _ok()
    # Обязательные формулы шаблона и реквизиты НПА совпадают с любым образцом — сравнивается только содержание
    k = doc.kit
    texts = (
        [v for key, v in k.sections.items() if key not in TEMPLATE_FORMULA_KEYS]
        + [mp.annotation + ' ' + ' '.join(c.get('text', '') for c in mp.content) for mp in k.module_programs]
        + [q.stem + ' ' + ' '.join(q.options) for q in k.questions]
        + [t.statement + ' ' + t.expected_result for t in k.tasks]
        + [' '.join(str(x.get('text', '')) for x in lec.plan) + ' ' + ' '.join(b for sl in lec.slides for b in sl.bullets) for lec in k.lectures]
    )
    share = overlap_share(' '.join(texts), ref)
    if share >= 0.05:
        return 'fail', [f'Совпадение с референсом по 8-граммам {share:.0%} (порог 5 %)'], []
    return 'pass', [f'Совпадение с референсом {share:.1%}'], []


# --- 9. Измеримость ---
def v18(doc: ProgramDoc, stage: str):
    # Критерий без текста так же бесполезен, как без баллов (MET-33: контрпример аудита — пустые критерии)
    bad = [t for t in doc.kit.tasks if not t.criteria or any(c.points <= 0 or not c.text.strip() for c in t.criteria)]
    return ('fail' if bad else 'pass'), [f'{t.title}: нет критериев оценки с текстом и баллами' for t in bad], [t.id for t in bad]


def v19(doc: ProgramDoc, stage: str):
    bad = [q for q in doc.kit.questions if not (0 <= q.key < len(q.options)) or len(set(o.strip().lower() for o in q.options)) != len(q.options)]
    return ('fail' if bad else 'pass'), [f'Вопрос {q.id}: ключ должен указывать ровно на один уникальный вариант' for q in bad], [q.id for q in bad]


# --- 10. Правка без регрессий: результат пишет workflow после точечной правки ---
def v20(doc: ProgramDoc, stage: str):
    last = doc.progress.get('last_edit_check')
    if last and not last.get('ok', True):
        return 'fail', [last.get('message', 'Правка изменила элементы вне потомков узла')], last.get('nodes', [])
    return _ok()


# --- Предупреждения ---
_PREREQ = [
    (('класс', 'ооп', 'объект'), ('цикл', 'услов', 'переменн')),
    (('api',), ('функци', 'цикл')),
    (('ci/cd', 'конвейер'), ('git',)),
    (('kubernetes',), ('docker',)),
]


def v21(doc: ProgramDoc, stage: str):
    topics = [t.title.lower() for t in doc.all_topics()]
    msgs, nodes = [], []
    for advanced, basics in _PREREQ:
        adv_idx = next((i for i, t in enumerate(topics) if any(a in t for a in advanced)), None)
        if adv_idx is None:
            continue
        for b in basics:
            b_idx = next((i for i, t in enumerate(topics) if b in t), None)
            if b_idx is not None and b_idx > adv_idx:
                msgs.append(f'Тема «{doc.all_topics()[adv_idx].title}» стоит раньше темы «{doc.all_topics()[b_idx].title}»')
                nodes.append(f'{doc.all_topics()[adv_idx].id}>{doc.all_topics()[b_idx].id}')
    return ('warn' if msgs else 'pass'), msgs, nodes


_VAGUE = ('понимает', 'знаком', 'имеет представление', 'осознаёт', 'осознает', 'изучает', 'знает о')


def v22(doc: ProgramDoc, stage: str):
    bad = [lo for lo in doc.all_outcomes() if lo.text.lower().startswith(_VAGUE) or any(v in lo.text.lower()[:25] for v in _VAGUE)]
    return ('warn' if bad else 'pass'), [f'{lo.code} «{lo.text}» нельзя проверить заданием' for lo in bad], [lo.id for lo in bad]


def v23(doc: ProgramDoc, stage: str):
    """Устаревшие конструкции и версии ниже поддерживаемых — сверка с реестром версий (FR-10, FR-61)."""
    from app.agent.extras import scan_text

    text = ' '.join(
        [lec.title + ' ' + ' '.join(lec.code_examples) + ' ' + ' '.join(b for s in lec.slides for b in s.bullets) for lec in doc.kit.lectures]
        + [mp.annotation + ' ' + ' '.join(c.get('text', '') for c in mp.content) for mp in doc.kit.module_programs]
        + [t.title + ' ' + t.description for t in doc.all_topics()]
    )
    found = [f for f in scan_text(text) if f['kind'] in ('construct', 'version', 'update')]
    msgs = [f['message'] + (f' → {f["replacement"]}' if f.get('replacement') else '') for f in found]
    return ('warn' if msgs else 'pass'), msgs[:20], []


def v24(doc: ProgramDoc, stage: str):
    from app.validation.sandbox import check_examples

    errors = check_examples(doc)
    return ('warn' if errors else 'pass'), errors, []


def v25(doc: ProgramDoc, stage: str):
    """Дубли тем между модулями (сходство > 0.85) и дубли строк материалов (SPEC-RULES-22):
    одинаковые формулировки вопросов (в том числе с разными ключами), пункты одного слайда, строки одного плана."""
    topics = doc.all_topics()
    msgs, nodes = [], []
    for i, a in enumerate(topics):
        for b in topics[i + 1 :]:
            if a.id.split('.')[0] != b.id.split('.')[0] and similarity(a.title, b.title) > 0.85:
                msgs.append(f'Темы {a.n} и {b.n} почти совпадают')
    by_stem: dict[str, list] = {}
    for q in doc.kit.questions:
        by_stem.setdefault(' '.join(q.stem.lower().split()), []).append(q)
    for qs in by_stem.values():
        if len(qs) > 1:
            ids = ', '.join(q.id for q in qs[:3])
            if len({q.key for q in qs}) > 1:
                msgs.append(f'Одинаковые вопросы ({ids}) помечают разными ключами верный ответ — проверьте ключ')
            else:
                msgs.append(f'Вопрос повторяется: {ids}')
            nodes += [q.id for q in qs[:3]]
    for lec in doc.kit.lectures:
        for sl in lec.slides:
            bullets = [' '.join(str(b).lower().split()) for b in sl.bullets if str(b).strip()]
            if len(bullets) != len(set(bullets)):
                msgs.append(f'Слайд {sl.id}: повторяются пункты')
                nodes.append(sl.id)
        plan = [' '.join(str(p.get('text', '')).lower().split()) for p in lec.plan if isinstance(p, dict) and str(p.get('text', '')).strip()]
        if len(plan) != len(set(plan)):
            msgs.append(f'Лекция {lec.id}: повторяются строки плана')
            nodes.append(lec.id)
    return ('warn' if msgs else 'pass'), msgs[:20], nodes[:20]


def _latin_share(text: str) -> float:
    """Доля латинских букв среди букв текста (MET-33: английский текст материалов ловится кодом, без модели)."""
    letters = [ch.lower() for ch in text if ch.isalpha()]
    if not letters:
        return 0.0
    return sum('a' <= ch <= 'z' for ch in letters) / len(letters)


def v26(doc: ProgramDoc, stage: str):
    msgs, nodes = [], []
    text = ' '.join(doc.kit.sections.values()) + ' '.join(q.stem for q in doc.kit.questions)
    letters = [ch for ch in text if ch.isalpha()]
    if letters:
        cyr = sum('а' <= ch.lower() <= 'я' or ch.lower() == 'ё' for ch in letters) / len(letters)
        if cyr < 0.8:
            msgs.append(f'Доля русского текста {cyr:.0%} — проверьте язык материалов')
    # Контекст судьи (SPEC-RULES-21): каждый узел с преимущественно латинским текстом — отдельная находка
    for q in doc.kit.questions:
        if _latin_share(q.stem + ' ' + ' '.join(q.options)) > 0.3:
            msgs.append(f'Вопрос {q.id}: больше 30 % латиницы — вопрос или варианты не на русском')
            nodes.append(q.id)
    for lec in doc.kit.lectures:
        for sl in lec.slides:
            if _latin_share(sl.title + ' ' + ' '.join(sl.bullets) + ' ' + sl.notes) > 0.3:
                msgs.append(f'Слайд {sl.id}: больше 30 % латиницы — проверьте язык материалов')
                nodes.append(sl.id)
    return ('warn' if msgs else 'pass'), msgs[:20], nodes[:20]


def v27(doc: ProgramDoc, stage: str):
    exp = doc.params.customer_expectation
    promises = ('полностью подготов', 'специалист любого', 'гарантир')
    text = (doc.goal + ' ' + ' '.join(lo.text for lo in doc.all_outcomes())).lower()
    msgs = [f'Формулировка обещает слишком много: «{p}»' for p in promises if p in text]
    if exp:
        note = next((n for n in doc.agent_notes if 'ожидани' in n.lower()), None)
        if not note:
            msgs.append(f'Запрос: «{exp}»; {doc.volume_h} ч дают начальный уровень — разрыв нужно показать методисту')
    return ('warn' if msgs else 'pass'), msgs, []


RULES: list[Rule] = [
    Rule('V-01', 'Сумма часов тем равна часам модуля по каждому виду работы', 1, 'code', v01),
    Rule('V-02', 'В каждой строке ЛК + ПР + ЛБ + СРС равно «Всего»', 1, 'code', v02),
    Rule('V-03', 'Сумма модулей по каждому виду работы равна итоговой строке', 1, 'code', v03),
    Rule('V-04', 'Итог вместе с ИА равен запрошенному объёму', 1, 'code', v04),
    Rule('V-05', 'Контактная работа в тексте равна ЛК + ПР + ЛБ в плане', 1, 'code', v05),
    Rule('V-06', 'Стажировка: ЛК, ПР и ЛБ равны 0 во всех строках', 1, 'code', v06),
    Rule('V-07', 'Доля практики не ниже заданной', 1, 'code', v07),
    Rule('V-08', 'Заполнены все обязательные разделы шаблона', 2, 'code', v08),
    Rule('V-09', 'Есть материалы из запроса, темы слайдов совпадают с УТП', 2, 'code', v09),
    Rule('V-10', 'Нагрузка и график укладываются в ограничения запроса', 3, 'code', v10),
    Rule('V-11', 'Реквизиты приказа, ФИО и подписи — пустые поля', 4, 'code', v11),
    Rule('V-12', 'Каждый РО раскрыт хотя бы в одной теме', 5, 'code', v12),
    Rule('V-13', 'Каждый РО проверяется не меньше чем двумя средствами', 5, 'code', v13),
    Rule('V-14', 'Каждый вопрос и задание привязаны к существующему РО', 6, 'code', v14),
    Rule('V-15', 'ПС и коды ТФ только из реестра; в ДООП раздела ПС нет', 7, 'code', v15),
    Rule('V-16', 'Источник найден в реестре или помечен «не подтверждено»', 7, 'code', v16),
    Rule('V-17', 'Совпадение 8-грамм с референсами меньше 5 %', 8, 'code', v17),
    Rule('V-18', 'У каждого задания есть критерии с текстом и баллами', 9, 'code', v18),
    Rule('V-19', 'У вопроса ровно один верный вариант', 9, 'code', v19),
    Rule('V-20', 'После правки изменились только потомки узла', 10, 'code', v20),
    Rule('V-21', 'Порядок тем учитывает пререквизиты', None, 'llm', v21),
    Rule('V-22', 'РО сформулирован проверяемым действием', None, 'llm', v22),
    Rule('V-23', 'Версии инструментов актуальны', None, 'code', v23),
    Rule('V-24', 'Примеры кода выполняются без ошибок', None, 'code', v24),
    Rule('V-25', 'Нет дублей тем между модулями и дублей строк материалов', None, 'code', v25),
    Rule('V-26', 'Текст на русском, термины поясняются', None, 'llm', v26),
    Rule('V-27', 'Обещания реалистичны, разрыв показан методисту', None, 'llm', v27),
]


def run_rules(doc: ProgramDoc, stage: str) -> list[RuleResult]:
    results = []
    for rule in RULES:
        if stage == 'skeleton' and rule.id not in SKELETON_RULES:
            continue
        try:
            status, msgs, nodes = rule.fn(doc, stage)
        except Exception as exc:  # noqa: BLE001 — страховка отчёта: сбой одного из 27 правил не роняет проверку, правило получает «!»
            logger.exception('rules program=%s stage=%s rule=%s: правило упало', doc.id, stage, rule.id)
            status, msgs, nodes = 'warn', [f'Правило не выполнено: {type(exc).__name__}'], []
        if rule.check is None and status == 'fail':
            status = 'warn'
        results.append(RuleResult(id=rule.id, title=rule.title, check=rule.check, kind=rule.kind, status=status, messages=msgs, nodes=nodes))
    return results
