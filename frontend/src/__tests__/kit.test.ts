import { describe, expect, it } from 'vitest'
import { groupKitByTopic, humanChecklist, KIND_ABBR, KIND_TITLES, orderRegisteredValue, routeBadge, TYPE_HINTS, ARCHIVE_FILTER, programsQuery, canArchive } from '../kit'

/* SPEC-UI-26, SPEC-UI-27, SPEC-UI-25: чистые функции карточки программы */

const doc = {
  volume_h: 16,
  totals: { total: 13 },
  final_assessment: { hours: 2 },
  modules: [
    { id: 'm1', n: 1, title: 'Введение', topics: [
      { id: 't1', n: 1, title: 'Знакомство' },
      { id: 't2', n: 2, title: 'Переменные' },
    ] },
    { id: 'm2', n: 2, title: 'Практика', topics: [{ id: 't3', n: 1, title: 'Проект' }] },
  ],
  kit: {
    lectures: [
      { id: 'l1', topic_id: 't1', module_id: 'm1', title: 'Знакомство', duration_min: 90, slides: [{ id: 's1' }, { id: 's2' }, { id: 's3' }] },
      { id: 'l2', topic_id: 't3', module_id: 'm2', title: 'Проект', duration_min: 45, slides: [] },
    ],
    tasks: [
      { id: 'task1', topic_id: 't2', title: 'Чек-лист', criteria: [{ text: 'a', points: 1 }] },
      { id: 'task2', topic_id: null, title: 'Без темы', criteria: [] },
    ],
    questions: [{ id: 'q1', module_id: 'm1' }, { id: 'q2', module_id: 'm1' }, { id: 'q3', module_id: 'm1' }],
  },
  report: { coverage: [{ means: 3 }, { means: 1 }] },
  sources: [{ id: 's1', confirmed: true }, { id: 's2', confirmed: false }, { id: 's3', confirmed: false }],
}

describe('подсказки видов работ и шаблонов', () => {
  it('у каждого столбца часов есть расшифровка и сокращение', () => {
    for (const k of ['lk', 'pr', 'lb', 'srs']) {
      expect(KIND_TITLES[k], k).toBeTruthy()
      expect(KIND_ABBR[k], k).toBeTruthy()
    }
    expect(KIND_TITLES.pr).toBe('Практические занятия')
    expect(KIND_ABBR.srs).toBe('СРС')
  })

  it('у каждого шаблона АЦР есть расшифровка', () => {
    for (const t of ['dpp_pk', 'dpp_pk_internship', 'doop']) expect(TYPE_HINTS[t], t).toBeTruthy()
    expect(TYPE_HINTS.dpp_pk).toContain('повышения квалификации')
    expect(TYPE_HINTS.dpp_pk_internship).toContain('аудиторных часов нет')
    expect(TYPE_HINTS.doop).toContain('общеразвивающая')
  })
})

describe('groupKitByTopic — файлы комплекта по темам', () => {
  it('складывает лекцию со слайдами и задания в их темы, тест — в модуль', () => {
    const [m1, m2] = groupKitByTopic(doc)
    expect(m1.files).toEqual([{ kind: 'test', label: 'Тест', title: 'Тест модуля 1', meta: '3 вопр.' }])
    expect(m1.topics[0].files).toEqual([{ kind: 'lecture', label: 'Лекция', title: 'Знакомство', meta: '90 мин · 3 слайдов' }])
    expect(m1.topics[1].files).toEqual([{ kind: 'task', label: 'Задание', title: 'Чек-лист', meta: '1 критериев' }])
    expect(m2.files).toEqual([])
    expect(m2.topics[0].files).toEqual([{ kind: 'lecture', label: 'Лекция', title: 'Проект', meta: '45 мин' }])
  })

  it('задание без темы не попадает в чужую тему', () => {
    const titles = groupKitByTopic(doc).flatMap((g) => g.topics.flatMap((t) => t.files.map((f) => f.title)))
    expect(titles).toEqual(['Знакомство', 'Чек-лист', 'Проект'])
  })

  it('модули без комплекта и пустой документ не ломают группировку', () => {
    expect(groupKitByTopic({ modules: doc.modules })).toEqual([
      { id: 'm1', n: 1, title: 'Введение', files: [], topics: [
        { id: 't1', n: 1, title: 'Знакомство', files: [] },
        { id: 't2', n: 2, title: 'Переменные', files: [] },
      ] },
      { id: 'm2', n: 2, title: 'Практика', files: [], topics: [{ id: 't3', n: 1, title: 'Проект', files: [] }] },
    ])
    expect(groupKitByTopic(null)).toEqual([])
  })
})

describe('humanChecklist — что проверить человеку перед утверждением', () => {
  it('показывает расхождение часов, неполное покрытие и неподтверждённые источники', () => {
    const items = humanChecklist(doc)
    expect(items.map((i) => i.ok)).toEqual([false, false, false])
    expect(items.map((i) => i.label)).toEqual(['Суммы часов', 'Покрытие компетенций', 'Источники'])
    expect(items[0].detail).toContain('15 ч из заявленных 16 ч')
    expect(items[1].detail).toContain('1 из 2')
    expect(items[2].detail).toContain('2 источников нет в реестре')
  })

  it('все пункты зелёные, когда часы сходятся, покрытие полное и источники из реестра', () => {
    const items = humanChecklist({ ...doc, totals: { total: 14 }, report: { coverage: [{ means: 2 }, { means: 3 }] }, sources: [{ confirmed: true }] })
    expect(items.map((i) => i.ok)).toEqual([true, true, true])
    expect(items[2].detail).toContain('реестре')
  })

  it('без отчёта о покрытии пункта о компетенциях нет', () => {
    expect(humanChecklist({ volume_h: 16, totals: { total: 14 }, final_assessment: { hours: 2 } }).map((i) => i.label))
      .toEqual(['Суммы часов', 'Источники'])
  })
})

describe('routeBadge', () => {
  it('SPEC-UI-33: плашка статуса вместо неактивной кнопки отправки', () => {
    expect(routeBadge('kit_ready')).toBeNull()
    expect(routeBadge('returned')).toBeNull()
    expect(routeBadge('on_approval')).toEqual({ text: 'На утверждении у руководителя', tone: 'wait' })
    const approvals = [{ stage: 'skeleton', decision: 'approve', at: '2026-10-20T10:00:00' }, { stage: 'program', decision: 'approve', at: '2026-10-23T01:10:00' }]
    expect(routeBadge('approved', approvals)).toEqual({ text: 'Утверждена руководителем · 23.10.2026', tone: 'ok' })
    expect(routeBadge('approved', approvals, orderRegisteredValue('2026-10-24T09:00:00Z'))).toEqual({ text: 'Зарегистрирована · 24.10.2026', tone: 'ok' })
  })
})

describe('архив методиста', () => {
  it('SPEC-UI-34: чип «Архив» запрашивает archived=true, кнопка архива — только у методиста и не на утверждении', () => {
    expect(programsQuery(ARCHIVE_FILTER)).toBe('?archived=true')
    expect(programsQuery('on_approval', '2026-10-01')).toBe('?status=on_approval&since=2026-10-01')
    expect(programsQuery('')).toBe('')
    expect(canArchive('methodist', 'kit_ready')).toBe(true)
    expect(canArchive('methodist', 'approved')).toBe(true)
    expect(canArchive('methodist', 'on_approval')).toBe(false)
    expect(canArchive('methodist', 'generating')).toBe(false)
    expect(canArchive('methodist', 'kit_ready', '2026-10-23T01:00:00')).toBe(false)
    expect(canArchive('head', 'kit_ready')).toBe(false)
    expect(canArchive('expert', 'kit_ready')).toBe(false)
  })
})
