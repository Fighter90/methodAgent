"""Разделы шаблона АЦР собираются кодом из графа комплекта — без копирования референса.

Заголовки и порядок — в app.validation.rules (SECTIONS_DPP, SECTIONS_DOOP); здесь только тексты.
Строки, начинающиеся с «— », выгружаются в DOCX маркированным списком, с «N. » — нумерованным.
"""

from __future__ import annotations

import re

from app.kb.registry import org_profile, tools
from app.programs.schemas import ProgramDoc, ProgramType

BLANK = '________________'


def plural(n: int, one: str, few: str, many: str) -> str:
    if n % 10 == 1 and n % 100 != 11:
        return one
    if 2 <= n % 10 <= 4 and not 12 <= n % 100 <= 14:
        return few
    return many


def hours_word(n: int) -> str:
    return plural(n, 'час', 'часа', 'часов')


def hours_gen(n: int) -> str:
    """«до 4 часов», «до 1 часа»."""
    return 'часа' if n % 10 == 1 and n % 100 != 11 else 'часов'


def _clean_tf(title: str) -> str:
    return re.sub(r'\s*\(код ТФ[^)]*\)', '', title or '').strip()


def _join(items: list[str]) -> str:
    return '\n'.join(f'— {x};' for x in items[:-1]) + (f'\n— {items[-1]}.' if items else '')


def _numbered(items: list[str]) -> str:
    return '\n'.join(f'{i}. {x}' for i, x in enumerate(items, 1))


def _sentence(text: str) -> str:
    """Убирает хвостовые точки и пробелы, чтобы не получалось «..»."""
    return re.sub(r'[\s.;:]+$', '', text or '').strip()


def _lower_first(text: str) -> str:
    """«Сотрудники банков» → «сотрудники банков», аббревиатуры («ИТ-специалисты») не трогаем."""
    t = _sentence(text)
    if len(t) > 1 and t[0].isupper() and not t[1].isupper():
        return t[0].lower() + t[1:]
    return t


_NOMINATIVE = {
    'учителей': 'учителя', 'детей': 'дети', 'взрослых': 'взрослые', 'руководителей': 'руководители',
    'преподавателей': 'преподаватели', 'обучающихся': 'обучающиеся', 'слушателей': 'слушатели', 'людей': 'люди',
}


def nominative(text: str) -> str:
    """«школьников 8–9 классов» → «школьники 8–9 классов»: аудитория из запроса часто стоит в родительном падеже."""
    t = _sentence(text)
    if not t:
        return t
    first, _, rest = t.partition(' ')
    low = first.lower()
    if low in _NOMINATIVE:
        new = _NOMINATIVE[low]
    elif low.endswith('ов') and len(low) > 4:
        new = low[:-2] + ('и' if low[-3] in 'кгхжшщч' else 'ы')
    else:
        return t
    new = new[0].upper() + new[1:] if first[0].isupper() else new
    return f'{new} {rest}'.strip()


def _upper_first(text: str) -> str:
    t = _sentence(text)
    return t[:1].upper() + t[1:]


def _software(doc: ProgramDoc) -> list[str]:
    text = ' '.join([doc.title, doc.params.direction, *(f'{t.title} {t.description}' for t in doc.all_topics()), *(c for lec in doc.kit.lectures for c in lec.code_examples)]).lower()
    cur = tools()['current']
    names = {
        'python': 'Python', 'pandas': 'pandas', 'numpy': 'NumPy', 'matplotlib': 'Matplotlib', 'seaborn': 'seaborn',
        'scikit-learn': 'scikit-learn', 'jupyterlab': 'JupyterLab', 'postgresql': 'PostgreSQL', 'sqlalchemy': 'SQLAlchemy',
        'docker': 'Docker', 'kubernetes': 'Kubernetes', 'terraform': 'Terraform', 'opentofu': 'OpenTofu', 'ansible-core': 'Ansible',
        'prometheus': 'Prometheus', 'grafana': 'Grafana', 'gitlab-ci': 'GitLab CI', 'nginx': 'nginx', 'fastapi': 'FastAPI',
    }
    keys = {'scikit-learn': ('scikit', 'sklearn'), 'ansible-core': ('ansible',), 'gitlab-ci': ('gitlab', 'ci/cd'), 'postgresql': ('postgres', 'sql'), 'kubernetes': ('kubernetes', 'k8s')}
    out = [f'{names[k]} {v}' for k, v in cur.items() if k in names and any(x in text for x in keys.get(k, (k,)))]
    if 'linux' in text:
        out.insert(0, 'ОС семейства Linux (Ubuntu Server, Astra Linux или РЕД ОС) для учебного стенда')
    if re.search(r'\bии\b|нейросет|искусственн\w* интеллект|gigachat|yandexgpt|\bllm\b', text):
        out.append('GigaChat, YandexGPT (Алиса) — сервисы ИИ, доступные в России')
    out += ['Браузер (Яндекс Браузер, Chrome или Firefox)', 'Офисный пакет (МойОфис или Р7-Офис) и средство подготовки презентаций',
            'Электронная информационно-образовательная среда организации', 'Платформа видеоконференцсвязи (МТС Линк или Яндекс Телемост)']
    return out


def _literature(doc: ProgramDoc) -> tuple[list[str], list[str], list[str], list[str]]:
    """НПА, основная, дополнительная литература и интернет-ресурсы — без повторов."""
    seen: set[str] = set()
    npa, books, web = [], [], []
    for s in doc.sources:
        key = s.bibl.lower().replace(' [не подтверждено]', '')
        if key in seen:
            continue
        seen.add(key)
        line = s.bibl + (f' — URL: {s.url}' if s.url and s.url not in s.bibl else '')
        if s.kind in ('law', 'ps'):
            npa.append(line)
        elif s.kind == 'url' or (s.kind == 'doc' and s.url):
            web.append(line)
        else:
            books.append((s.confirmed, line))
    books.sort(key=lambda x: not x[0])
    main = [b for _, b in books[:4]]
    extra = [b for _, b in books[4:]]
    return npa, main, extra, web


def build_sections(doc: ProgramDoc) -> dict[str, str]:
    tot = doc.totals()
    p = doc.params
    doop = doc.type == ProgramType.DOOP
    internship = doc.type == ProgramType.DPP_PK_INTERNSHIP
    fa = doc.final_assessment
    cal = doc.calendar
    org = org_profile()
    goal = _sentence(doc.goal)
    audience = nominative(p.audience) or ('обучающиеся по профилю программы' if doop else 'специалисты по профилю программы')
    form = _lower_first(p.form) or 'очная'
    s: dict[str, str] = {}

    s['approval'] = f'УТВЕРЖДЕНО\nПриказом № ____-{org.get("order_prefix", "ОБР")} от «___» __________ 20__ г.'
    s['authors'] = f'Составитель: {BLANK} (ФИО, должность). Подпись: {BLANK}.'

    # --- Режим и объём ---
    if cal.sessions:
        s['regime'] = f'Занятия {cal.days_per_week} {plural(cal.days_per_week, "раз", "раза", "раз")} в неделю по {cal.session_hours} ак. ч; всего {cal.sessions} занятий за {cal.weeks} нед.'
        regime_short = f'{cal.days_per_week} {plural(cal.days_per_week, "раз", "раза", "раз")} в неделю по {cal.session_hours} {hours_word(cal.session_hours)}'
    else:
        s['regime'] = f'Не более {cal.hours_per_day} ак. ч в день, {cal.days_per_week} дней в неделю; {cal.work_days} {plural(cal.work_days, "учебный день", "учебных дня", "учебных дней")} за {cal.weeks} нед.'
        regime_short = f'до {cal.hours_per_day} {hours_gen(cal.hours_per_day)} в день'
    days = cal.work_days or (cal.sessions or 0)
    term = f'{days} {plural(days, "день", "дня", "дней")}' if days else f'{cal.weeks} нед.'

    modules_list = [f'{m.title} ({m.hours.total} ч)' for m in doc.modules]
    s['annotation'] = (
        f'Программа «{doc.title}» ({doc.volume_h} ак. ч). Цель программы — {_lower_first(goal) or "совершенствование профессиональных компетенций"}. '
        f'Программа предназначена для слушателей категории: {_lower_first(audience)}.\n'
        'Содержание программы охватывает:\n' + _join(modules_list)
    )
    s['relevance'] = (
        f'Актуальность программы обусловлена спросом на практические навыки в области «{p.direction or doc.title}» '
        'и необходимостью применять современные инструменты и сервисы, доступные в России (версии актуальны на 2026 год). '
        'Программа построена на практике: каждый модуль завершается результатом, который обучающийся выполняет сам.'
    )
    if doop:
        direction = 'техническую' if any(k in (doc.title + p.direction).lower() for k in ('python', 'программ', 'ии', 'робот', 'данн', 'цифров', 'it', 'ит')) else 'социально-гуманитарную'
        s['annotation'] = (
            f'Дополнительная общеразвивающая программа «{doc.title}» имеет {direction} направленность и реализуется на базовом уровне.\n'
            f'{_upper_first(goal)}.\n'
            'Уровень освоения программы: базовый.\n'
            f'Направленность (профиль) программы – {direction.replace("ую", "ая")}.\n'
            f'Форма обучения: {form}.' + (' С применением электронного обучения и дистанционных образовательных технологий.' if p.distance else '') + '\n'
            f'Программа включает {len(doc.modules)} {plural(len(doc.modules), "модуль", "модуля", "модулей")}: {", ".join(modules_list)}.\n'
            f'Документ, выдаваемый по итогам обучения: {doc.issued_document.lower() or "сертификат об освоении программы"}.\n'
            'Условия обучения: компьютерный класс или ноутбук на каждого обучающегося, доступ в интернет, установленное программное обеспечение по перечню раздела 3.2.'
        )

    # --- Цель ---
    if doop:
        tasks_list = [f'Сформировать: {_lower_first(c.title)}' for c in doc.competencies] or ['Сформировать практические навыки по теме программы']
        s['goal'] = f'Цель Программы – {_lower_first(goal)}.\nРеализация поставленной цели предусматривает решение ряда задач.\nЗадачи Программы\n' + _join(tasks_list)
    else:
        s['goal'] = f'{_upper_first(goal)}.'
        if doc.profstandard and doc.profstandard.tf:
            s['goal'] += '\nПрограмма направлена на совершенствование профессиональных компетенций для выполнения трудовых функций:\n' + _join([_sentence(_clean_tf(t.title)) for t in doc.profstandard.tf])

    # --- Результаты ---
    if doop:
        kinds = {'know': 'Знания:', 'can': 'Умения:', 'own': 'Навыки:'}
        lines = []
        for kind, label in kinds.items():
            items = [_sentence(lo.text) for c in doc.competencies for i in c.indicators if i.kind == kind for lo in i.outcomes]
            if items:
                lines.append(label)
                lines.append(_join(items))
        s['results'] = '\n'.join(lines)
    else:
        res = ['Программа направлена на освоение (совершенствование) следующих профессиональных компетенций:']
        for c in doc.competencies:
            res.append(f'{c.code}. {c.title}' + (f' (ТФ {", ".join(c.tf_codes)} ПС {c.ps_code})' if c.tf_codes else ''))
            for ind in c.indicators:
                label = {'know': 'Знать', 'can': 'Уметь', 'own': 'Владеть'}[ind.kind]
                for lo in ind.outcomes:
                    res.append(f'  {lo.code} ({label}): {lo.text}')
        s['results'] = '\n'.join(res)

    # --- 1.4 ---
    base = []
    if doc.profstandard and not doop:
        ps = doc.profstandard
        base.append(f'Профессионального стандарта {ps.code} «{ps.title}» ({ps.order})' + ('' if ps.confirmed else ' — коды трудовых функций требуют сверки с реестром Минтруда России'))
    base.append('Федерального закона от 29.12.2012 № 273-ФЗ «Об образовании в Российской Федерации» и Порядка организации и осуществления образовательной деятельности по дополнительным профессиональным программам (приказ Минобрнауки России № 499)')
    if p.required_topics:
        base.append('Требований заказчика к содержанию: ' + ', '.join(p.required_topics[:6]))
    s['ps'] = _join(base)
    tf_titles = {t.code: _clean_tf(t.title) for t in (doc.profstandard.tf if doc.profstandard else [])}
    comp_lines = []
    for c in doc.competencies:
        if c.tf_codes:
            comp_lines += [f'{code} {_sentence(tf_titles.get(code, c.title))}.' for code in c.tf_codes]
        else:
            comp_lines.append(f'{c.code}. {_sentence(c.title)}.')
    s['competencies_list'] = '\n'.join(dict.fromkeys(comp_lines))

    # --- Слушатели, форма, объём, документ ---
    if doop:
        s['audience'] = f'{_upper_first(audience)}. Входной уровень: {_lower_first(p.entry_level) or "специальной подготовки не требуется"}.'
    else:
        s['audience'] = (
            'К освоению программы допускаются лица, имеющие среднее профессиональное и (или) высшее образование, а также лица, '
            f'получающие среднее профессиональное и (или) высшее образование. Категория слушателей: {_lower_first(audience)}. '
            f'Входной уровень: {_lower_first(p.entry_level) or "специальной подготовки не требуется"}.'
        )
    s['form'] = f'{_upper_first(form)}.' + (' С применением электронного обучения и дистанционных образовательных технологий.' if p.distance else '')
    if internship:
        s['form'] = 'Стажировка' + (' с применением электронного обучения и дистанционных образовательных технологий' if p.distance else '') + '. Стажировка проходит на рабочем месте под руководством наставника от организации; аудиторных занятий нет.'
    s['form'] += f'\nРежим занятий: {regime_short}.'
    if doop:
        s['volume'] = (
            f'Срок реализации: {cal.weeks} {plural(int(cal.weeks), "неделя", "недели", "недель")} ({term}).\n'
            f'Трудоемкость: {doc.volume_h} {hours_word(doc.volume_h)}.\n'
            'Конкретные даты начала и окончания обучения, а также расписание занятий устанавливаются для каждой учебной группы '
            'приказом организации о зачислении и утверждённым расписанием по мере комплектации учебных групп.'
        )
    else:
        s['volume'] = (
            f'{doc.volume_h} академических {plural(doc.volume_h, "час", "часа", "часов")}.\n'
            f'— Контактная работа: {tot.contact} {hours_word(tot.contact)} (лекции {tot.lk}, практические занятия {tot.pr}, лабораторные работы {tot.lb}).\n'
            f'— Самостоятельная работа слушателей (СРС): {tot.srs} {hours_word(tot.srs)}.\n'
            f'— Итоговая аттестация: {fa.hours} {hours_word(fa.hours)}.\n'
            f'— Срок обучения: {term} ({regime_short}).'
        )
    s['document'] = (doc.issued_document or ('Сертификат об освоении программы' if doop else 'Удостоверение о повышении квалификации')) + (' установленного образца.' if not doop else '.')

    # --- Планы и график ---
    s['curriculum'] = 'Учебный план приведён в таблице: разделы программы, трудоёмкость по видам работы и формы аттестации.'
    s['utp'] = 'Учебно-тематический план приведён в таблице: темы разделов с часами по видам работы' + (' и содержанием занятий.' if doop else '.')
    if doop:
        s['calendar'] = (
            f'Количество учебных недель – {cal.weeks}.\nКоличество учебных дней – {days}.\nРежим занятий: {regime_short}.\n'
            f'Общая трудоёмкость программы — {doc.volume_h} {hours_word(doc.volume_h)}: {tot.contact} {hours_word(tot.contact)} аудиторных занятий '
            f'({tot.lk} ч теоретических и {tot.pr + tot.lb} ч практических), {tot.srs} ч самостоятельной работы и {fa.hours} ч итоговой аттестации.'
        )
    else:
        s['calendar'] = (
            f'Срок обучения: {term}.\nРежим занятий: {regime_short}.\n'
            + ('Программа реализуется с применением ЭО и ДОТ. ' if p.distance else '')
            + 'Даты занятий устанавливаются при наборе групп; распределение часов по неделям приведено в таблице.'
        )
    s['content'] = '\n'.join(f'Раздел {m.n}. {m.title}: ' + '; '.join(f'тема {t.n} «{t.title}»' for t in m.topics) for m in doc.modules)

    # --- Оценка ---
    controls = sorted({m.control for m in doc.modules})
    final_task = next((t for t in doc.kit.tasks if t.assessment_id == 'final'), None)
    crit = [f'{_sentence(c.text)} — до {c.points} {plural(c.points, "балла", "баллов", "баллов")}' for c in (final_task.criteria if final_task else [])]
    total_pts = sum(c.points for c in final_task.criteria) if final_task and final_task.criteria else 0
    s['assessment'] = (
        'Освоение программы оценивается в ходе текущего контроля по разделам и итоговой аттестации.\n'
        f'Текущий контроль проводится в форме: {", ".join(_lower_first(c) for c in controls)}.\n'
        f'Итоговая аттестация проводится в форме: {_lower_first(fa.form)} ({fa.hours} {hours_word(fa.hours)}).\n'
        'Условия допуска к итоговой аттестации: пройден текущий контроль. '
        'Каждый результат обучения проверяется не менее чем двумя оценочными средствами.'
    )
    s['attestation_forms'] = (
        f'Текущий контроль: {", ".join(_lower_first(c) for c in controls)} по каждому разделу программы.\n'
        f'Итоговая аттестация (ИА): {_lower_first(fa.form)}. {_sentence(fa.description)}.\n'
        + ('Критерии оценки:\n' + _join(crit) + '\n' if crit else '')
        + (f'Результат: зачтено / не зачтено. «Зачтено» ставится при сумме не менее {round(total_pts * 0.7)} из {total_pts} баллов. ' if total_pts else 'Результат: зачтено / не зачтено. ')
        + ('Удостоверение выдаётся по решению аттестационной комиссии при результате «зачтено».' if not doop else '')
    )
    s['assessment_materials'] = 'Оценочные материалы для текущего контроля приведены в Приложении 1.\nОценочные материалы для итоговой аттестации приведены в Приложении 2.'
    s['quality'] = (
        'До начала обучения по программе и по итогам обучения проводится анкетирование слушателей для анализа ожиданий '
        'и удовлетворённости требований к организации и качеству обучения.'
    )
    if doop:
        s['assessment'] = (
            f'Текущий контроль: {", ".join(_lower_first(c) for c in controls)} по итогам каждого модуля. '
            'Оценочные материалы — тесты с ключами и практические задания с критериями; этапы контроля приведены в таблице.\n'
            f'Итоговая аттестация — {_lower_first(fa.form)} ({fa.hours} {hours_word(fa.hours)}). {_sentence(fa.description)}.\n'
            + ('Критерии оценивания:\n' + _join(crit) + '\n' if crit else '')
            + f'Обучающимся, успешно освоившим программу, выдаётся {doc.issued_document.lower() or "сертификат об освоении программы"}.'
        )
    s['final'] = f'Итоговая аттестация — {_lower_first(fa.form)}, {fa.hours} {hours_word(fa.hours)}. {_sentence(fa.description)}.'

    # --- Условия ---
    if internship or (p.distance and tot.contact == 0):
        s['conditions_mt'] = 'Стажировка реализуется на рабочем месте в организации-партнёре и с применением дистанционных образовательных технологий и электронного обучения: компьютер с доступом в интернет, электронная информационно-образовательная среда, видеоконференцсвязь для собеседований с руководителем стажировки.'
    else:
        s['conditions_mt'] = _join([
            'учебная аудитория, оборудованная рабочими местами для одновременной работы всех обучающихся',
            'компьютер или ноутбук на каждое рабочее место с установленным программным обеспечением по перечню раздела 3.2',
            'стабильный доступ в интернет',
            'проектор или экран для демонстрации презентаций',
            'электронная информационно-образовательная среда для размещения материалов и приёма заданий',
        ])
    s['conditions_it'] = (
        'Комплект учебно-методических материалов программы: рабочие программы разделов, планы и конспекты лекций, '
        'презентации к занятиям, практические задания с критериями оценивания, тесты с ключами, материалы итоговой аттестации.'
    )
    npa, main, extra, web = _literature(doc)
    s['lit_npa'] = _numbered(npa) or '1. Федеральный закон от 29.12.2012 № 273-ФЗ «Об образовании в Российской Федерации».'
    s['lit_main'] = _numbered(main) or 'Основная литература подбирается из реестра источников организации.'
    s['lit_extra'] = _numbered(extra) or 'Дополнительные материалы — официальная документация инструментов (раздел «Интернет-ресурсы»).'
    s['lit_web'] = _numbered(web) or 'Интернет-ресурсы публикуются в электронной информационно-образовательной среде.'
    software = _software(doc)
    s['software'] = _numbered(software)
    if doop:
        s['conditions_it'] += '\nДля осуществления образовательного процесса необходимо следующее программное обеспечение:\n' + _join(software)
        s['literature'] = 'Перечень основной и дополнительной литературы и интернет-ресурсов приведён ниже.'
    s['process'] = (
        'Образовательный процесс организуется по учебному плану и календарному учебному графику. '
        + ('Стажировка проходит на рабочем месте: слушатель выполняет задания по индивидуальному плану, наставник от организации '
           'консультирует и проводит собеседования по разделам; результаты фиксируются в отчёте о стажировке. ' if internship else
           'Занятия проводятся в форме лекций, практических и лабораторных работ; самостоятельная работа сопровождается консультациями. ')
        + ('Используются электронное обучение и дистанционные образовательные технологии. ' if p.distance else '')
        + 'Обучение ведётся на русском языке.'
    )
    s['conditions_org'] = (
        ('Руководитель стажировки: специалист профильной организации с опытом практической работы не менее 3 лет. ' if internship else '')
        + 'Реализацию программы обеспечивают педагогические работники и эксперты-практики, имеющие опыт работы в профильной области. '
        + 'Не менее 70 % преподавателей имеют практический опыт работы в отрасли не менее 2 лет. '
        + 'Свою квалификацию преподаватели повышают не реже раза в три года.'
    )
    s['methodical'] = (
        'Методические рекомендации для теоретических занятий: лекция строится по плану с распределением времени, '
        'каждое занятие начинается с повторения материала предыдущего и завершается вопросами для самоконтроля.\n'
        'Методические рекомендации для практических занятий: задания выполняются по инструкции с критериями оценивания; '
        'педагог показывает пример выполнения, затем обучающиеся работают самостоятельно или в парах.\n'
        'Методические рекомендации по самостоятельной работе: обучающийся повторяет материал по конспекту и презентации, '
        'выполняет задания для самоконтроля и готовит итоговую работу.\n'
        'Групповые и индивидуальные консультации проводятся по сложным вопросам и при подготовке к итоговой аттестации.\n'
        'К каждому занятию подготовлены план с распределением времени, презентация, практические задания с критериями и тест с ключами.'
    )
    s['app1'] = 'Пример оценочных материалов для текущего контроля'
    s['app2'] = 'Пример оценочных материалов для итоговой аттестации'
    if doop:
        s['app1'] = 'Оценочные материалы: тесты с ключами и практические задания с критериями оценивания'
    s['norm'] = '; '.join(src.bibl for src in doc.norm_base)
    return s
