/* Чистые функции карточки программы: расшифровки видов работ и шаблонов (MET-16),
 * группировка файлов комплекта по темам (MET-13) и чек-лист «что проверить человеку» (MET-13б),
 * структурированная форма запроса и сборка params для POST /programs (MET-15, MET-53/R09),
 * чек-лист проекта приказа (MET-19) и честные метрики времени и затрат (MET-8).
 * Модуль без JSX — покрывается vitest-тестами на чистых функциях (__tests__/kit.test.ts, form.test.ts). */

export type Doc = any

/** Полные названия видов работ — подсказки над столбцами часов ЛК/ПР/ЛБ/СРС. */
export const KIND_TITLES: Record<string, string> = {
  lk: 'Лекции',
  pr: 'Практические занятия',
  lb: 'Лабораторные работы',
  srs: 'Самостоятельная работа',
}

/** Сокращения столбцов часов — единые для таблиц и календарного графика. */
export const KIND_ABBR: Record<string, string> = { lk: 'ЛК', pr: 'ПР', lb: 'ЛБ', srs: 'СРС' }

/** Расшифровки шаблонов АЦР — подсказки при наведении. */
export const TYPE_HINTS: Record<string, string> = {
  dpp_pk: 'Дополнительная профессиональная программа повышения квалификации: лекции, практика, самостоятельная работа и итоговая аттестация',
  dpp_pk_internship: 'ДПП ПК в форме стажировки: аудиторных часов нет, только практика на рабочем месте и самостоятельная работа',
  doop: 'Дополнительная общеразвивающая программа для школьников: без привязки к профстандарту',
}

/** Один файл комплекта внутри темы или модуля. */
export interface KitFile { kind: 'lecture' | 'task' | 'test'; label: string; title: string; meta: string }

/** Тема модуля с её файлами. */
export interface KitTopicGroup { id: string; n: number; title: string; files: KitFile[] }

/** Модуль: свой файл (тест) и темы с файлами. */
export interface KitModuleGroup { id: string; n: number; title: string; files: KitFile[]; topics: KitTopicGroup[] }

/** Файлы комплекта, сгруппированные по модулям и темам: у каждой темы её лекции и задания (MET-13а). */
export function groupKitByTopic(doc: Doc): KitModuleGroup[] {
  const kit = doc?.kit || {}
  const byTopic = (items: any[], key: string) => {
    const map = new Map<string, any[]>()
    items.forEach((x) => { if (!x[key]) return; const a = map.get(x[key]) || []; a.push(x); map.set(x[key], a) })
    return map
  }
  const lectures = byTopic(kit.lectures || [], 'topic_id')
  const tasks = byTopic(kit.tasks || [], 'topic_id')
  const questions = new Map<string, number>()
  ;(kit.questions || []).forEach((q: any) => questions.set(q.module_id, (questions.get(q.module_id) || 0) + 1))
  return (doc?.modules || []).map((m: any) => ({
    id: m.id,
    n: m.n,
    title: m.title,
    files: questions.get(m.id) ? [{ kind: 'test', label: 'Тест', title: `Тест модуля ${m.n}`, meta: `${questions.get(m.id)} вопр.` }] : [],
    topics: (m.topics || []).map((t: any) => ({
      id: t.id,
      n: t.n,
      title: t.title,
      files: [
        ...(lectures.get(t.id) || []).map((l: any) => ({ kind: 'lecture', label: 'Лекция', title: l.title, meta: `${l.duration_min} мин${l.slides?.length ? ` · ${l.slides.length} слайдов` : ''}` })),
        ...(tasks.get(t.id) || []).map((a: any) => ({ kind: 'task', label: 'Задание', title: a.title, meta: `${a.criteria?.length || 0} критериев` })),
      ] as KitFile[],
    })),
  }))
}

export interface CheckItem { ok: boolean; label: string; detail: string }

/** Что человеку осталось проверить глазами перед утверждением (MET-13б): суммы часов, покрытие компетенций, источники. */
export function humanChecklist(doc: Doc): CheckItem[] {
  const volume = doc?.volume_h || 0
  const tot = (doc?.totals?.total || 0) + (doc?.final_assessment?.hours || 0)
  const rows = doc?.report?.coverage || []
  const covered = rows.filter((r: any) => (r.means || 0) >= 2).length
  const unconfirmed = (doc?.sources || []).filter((s: any) => !s.confirmed).length
  const items: CheckItem[] = [
    { ok: tot === volume, label: 'Суммы часов', detail: `Итого с аттестацией ${tot} ч из заявленных ${volume} ч${tot === volume ? '' : ' — расхождение нужно устранить до утверждения'}.` },
  ]
  if (rows.length) items.push({ ok: covered === rows.length, label: 'Покрытие компетенций', detail: `Каждый результат обучения проверяют минимум два средства: выполнено для ${covered} из ${rows.length}.` })
  items.push({ ok: unconfirmed === 0, label: 'Источники', detail: unconfirmed ? `${unconfirmed} источников нет в реестре — в документе они помечены «не подтверждено». Проверьте или замените.` : 'Все источники найдены в реестре НПА и литературы.' })
  return items
}

/* ---------------- Структурированная форма запроса (MET-15) ---------------- */

export interface RequestFormFields {
  title: string                                   // тема / название программы
  program_type: '' | 'dpp_pk' | 'doop'            // '' — предложит агент
  audience: string                                // для кого
  entry_level: string                             // что слушатели уже знают
  volume_h: number | ''                           // объём в академических часах
  form: '' | 'очная' | 'очно-заочная' | 'заочная' | 'дистанционная'
  duration_value: number | ''                     // примерный срок
  duration_unit: 'weeks' | 'months'
  final_assessment: '' | 'Защита проекта' | 'Зачёт по портфолио' | 'Экзамен' | 'Защита отчёта о стажировке'
}

export const EMPTY_REQUEST_FORM: RequestFormFields = {
  title: '', program_type: '', audience: '', entry_level: '', volume_h: '', form: '', duration_value: '', duration_unit: 'weeks', final_assessment: '',
}

export const VOLUME_PRESETS = [16, 36, 72, 256]

export const REQUEST_FORM_TYPE_LABEL: Record<RequestFormFields['program_type'], string> = {
  '': 'Предложит агент', dpp_pk: 'Повышение квалификации', doop: 'Общеразвивающая',
}

export const REQUEST_FORM_FINAL_OPTIONS: RequestFormFields['final_assessment'][] = ['Защита проекта', 'Зачёт по портфолио', 'Экзамен', 'Защита отчёта о стажировке']

export const REQUEST_FORM_FORM_OPTIONS: RequestFormFields['form'][] = ['очная', 'очно-заочная', 'заочная', 'дистанционная']

/** Поля формы в формате `params` запроса `POST /programs` (R09/MET-53): имена совпадают с моделью Params бэкенда. */
export interface RequestFormParams {
  title?: string
  program_type?: 'dpp_pk' | 'doop'
  audience?: string
  entry_level?: string
  volume_h?: number
  form?: string
  duration_weeks?: number
  final_assessment_form?: string
}

/** Свободный текст-заглушка, когда поля формы заполнены, а текст запроса пуст:
 * бэкенд требует в `request` не меньше 5 символов, реальное описание несёт `params`. */
export const FORM_ONLY_REQUEST = 'Параметры программы заданы в полях формы'

/** Структура `params` только из заполненных полей формы (R09/MET-53): «предложит агент» и пустые
 * строки не отправляются; срок в месяцах переводится в недели так же, как в intake бэкенда
 * (1 месяц ≈ 4.3 недели). */
export function buildRequestParams(f: RequestFormFields): RequestFormParams {
  const p: RequestFormParams = {}
  const title = (f.title || '').trim()
  if (title) p.title = title
  if (f.program_type) p.program_type = f.program_type
  const audience = (f.audience || '').trim()
  if (audience) p.audience = audience
  const entry = (f.entry_level || '').trim()
  if (entry) p.entry_level = entry
  if (f.volume_h !== '' && Number(f.volume_h) > 0) p.volume_h = Number(f.volume_h)
  if (f.form) p.form = f.form
  if (f.duration_value !== '' && Number(f.duration_value) > 0) {
    const n = Number(f.duration_value)
    p.duration_weeks = f.duration_unit === 'months' ? Math.round(n * 4.3 * 10) / 10 : n
  }
  if (f.final_assessment) p.final_assessment_form = f.final_assessment
  return p
}

/** Есть ли в структуре хоть одно заполненное поле: пустая форма идёт старым multipart-путём. */
export function hasRequestParams(p: RequestFormParams): boolean {
  return Object.keys(p).length > 0
}

/* ---------------- Чек-лист проекта приказа (MET-19) ---------------- */

/** Поля проекта приказа, которые агент не заполняет: их вписывают люди при регистрации. */
export const ORDER_CHECKLIST: { label: string; hint: string }[] = [
  { label: 'Номер приказа', hint: 'присваивается при регистрации' },
  { label: 'Дата приказа', hint: 'дата утверждения' },
  { label: 'ФИО преподавателей', hint: 'заполняет организация' },
  { label: 'Подписи', hint: 'руководитель и преподаватели' },
]

export const ORDER_NOTE = 'Регистрацию программа проходит вне системы'

/** Ключ отметки «программа зарегистрирована» в localStorage — статус на сервере не меняется. */
export function orderStorageKey(programId: string): string {
  return `ma.order.${programId}`
}

/** Значение-отметка регистрации: { done: true, at } в JSON. */
export function orderRegisteredValue(at = new Date().toISOString()): string {
  return JSON.stringify({ done: true, at })
}

export function isOrderRegistered(raw: string | null | undefined): boolean {
  if (!raw) return false
  try {
    return JSON.parse(raw)?.done === true
  } catch {
    return false
  }
}

export function readStore(key: string): string | null {
  try {
    return localStorage.getItem(key)
  } catch {
    return null
  }
}

export function writeStore(key: string, value: string): void {
  try {
    localStorage.setItem(key, value)
  } catch {
    /* хранилище недоступно — отметка просто не сохранится */
  }
}

/* ---------------- Честные метрики времени и затрат (MET-8) ---------------- */

export interface ProgramMetrics {
  skeleton: string   // время каркаса или «—»
  kit: string        // время комплекта или «—»
  model: string      // «X ₽ · Y вызовов» или «—»
  tokens: string     // сумма токенов или «—»
  note: string       // подпись, когда данных нет; '' — когда есть
}

/** Данные есть только там, где они реально собирались: ноль не выдаётся за результат (MET-8). */
export function programMetrics(doc: Doc): ProgramMetrics {
  const t = doc?.timing_s || {}
  const usage = doc?.usage || {}
  const sec = (v: unknown) => (typeof v === 'number' && v > 0 ? `${Math.round(v)} с` : '—')
  const called = Number(usage.calls) > 0
  return {
    skeleton: sec(t.skeleton),
    kit: sec(t.kit),
    model: called ? `${Number(usage.cost_rub || 0).toFixed(2)} ₽ · ${usage.calls} вызовов` : '—',
    tokens: called ? String(Number(usage.tokens_in || 0) + Number(usage.tokens_out || 0)) : '—',
    note: typeof t.skeleton === 'number' && typeof t.kit === 'number'
      ? ''
      : 'Метрики времени и затрат собираются в режиме автопрогона — для этой программы данных нет',
  }
}

/** Плашка вместо кнопки «Отправить на утверждение» в «Маршрут программы» (SPEC-UI-33):
 * на утверждении — «На утверждении у руководителя», утверждена — «Утверждена руководителем · дата»,
 * после отметки регистрации — «Зарегистрирована · дата». Для остальных статусов плашки нет — видна кнопка. */
export function routeBadge(
  status: string,
  approvals: { stage: string; decision: string; at: string }[] = [],
  registeredRaw?: string | null,
): { text: string; tone: 'ok' | 'wait' } | null {
  const day = (iso?: string) => (iso ? iso.slice(0, 10).split('-').reverse().join('.') : '')
  const withDate = (t: string, iso?: string) => (day(iso) ? `${t} · ${day(iso)}` : t)
  if (status === 'on_approval') return { text: 'На утверждении у руководителя', tone: 'wait' }
  if (status !== 'approved') return null
  if (isOrderRegistered(registeredRaw)) {
    let at: string | undefined
    try { at = JSON.parse(registeredRaw as string)?.at } catch { /* отметка без даты */ }
    return { text: withDate('Зарегистрирована', at), tone: 'ok' }
  }
  const approval = [...approvals].reverse().find((a) => a.stage === 'program' && a.decision === 'approve')
  return { text: withDate('Утверждена руководителем', approval?.at), tone: 'ok' }
}
