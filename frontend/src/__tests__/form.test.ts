import { beforeEach, describe, expect, it } from 'vitest'
import {
  applyRequestForm, buildStructuredPrefix, EMPTY_REQUEST_FORM, isOrderRegistered, ORDER_CHECKLIST, ORDER_NOTE,
  orderRegisteredValue, orderStorageKey, programMetrics, ruPlural, type RequestFormFields,
} from '../kit'

/* SPEC-UI-28, SPEC-UI-29, SPEC-UI-30: чистые функции формы запроса, чек-листа приказа и честных метрик */

const FULL: RequestFormFields = {
  title: 'Анализ данных на Python',
  program_type: 'dpp_pk',
  audience: 'сотрудники банков',
  entry_level: 'работу в Excel',
  volume_h: 36,
  form: 'очно-заочная',
  duration_value: 4,
  duration_unit: 'weeks',
  final_assessment: 'Защита проекта',
}

describe('buildStructuredPrefix — префикс формы запроса (MET-15)', () => {
  it('склеивает только заполненные поля в порядке формы', () => {
    const p = buildStructuredPrefix(FULL)
    expect(p).toContain('Тема: «Анализ данных на Python»')
    expect(p).toContain('Тип: повышение квалификации')
    expect(p).toContain('Аудитория: сотрудники банков')
    expect(p).toContain('Слушатели уже знают работу в Excel')
    expect(p).toContain('Объём: 36 ч')
    expect(p).toContain('Форма обучения: очно-заочная')
    expect(p).toContain('Срок: примерно 4 недели')
    expect(p).toContain('Итоговая аттестация: защита проекта')
    expect(p.indexOf('Тема')).toBeLessThan(p.indexOf('Объём'))
    expect(p.endsWith('.')).toBe(true)
  })

  it('пустая форма — пустая строка, «предложит агент» в префикс не попадает', () => {
    expect(buildStructuredPrefix({ ...EMPTY_REQUEST_FORM })).toBe('')
    expect(buildStructuredPrefix({ ...FULL, program_type: '', final_assessment: '', title: '', audience: '', entry_level: '' }))
      .toBe('Объём: 36 ч; Форма обучения: очно-заочная; Срок: примерно 4 недели.')
  })

  it('срок в месяцах склоняется и помечается как примерный', () => {
    expect(buildStructuredPrefix({ ...EMPTY_REQUEST_FORM, duration_value: 2, duration_unit: 'months' })).toContain('Срок: примерно 2 месяца')
    expect(buildStructuredPrefix({ ...EMPTY_REQUEST_FORM, duration_value: 1, duration_unit: 'months' })).toContain('Срок: примерно 1 месяц')
    expect(buildStructuredPrefix({ ...EMPTY_REQUEST_FORM, duration_value: 6, duration_unit: 'months' })).toContain('Срок: примерно 6 месяцев')
    expect(buildStructuredPrefix({ ...EMPTY_REQUEST_FORM, duration_value: 1, duration_unit: 'weeks' })).toContain('Срок: примерно 1 неделя')
    expect(buildStructuredPrefix({ ...EMPTY_REQUEST_FORM, duration_value: 3, duration_unit: 'weeks' })).toContain('Срок: примерно 3 недели')
  })

  it('нулевые и отрицательные числа объёма и срока игнорируются', () => {
    expect(buildStructuredPrefix({ ...FULL, volume_h: 0, duration_value: 0 })).not.toContain('Объём')
    expect(buildStructuredPrefix({ ...FULL, volume_h: 0, duration_value: 0 })).not.toContain('Срок')
  })
})

describe('applyRequestForm — склейка с текстом запроса', () => {
  it('префикс идёт в начале, свободный текст — после пустой строки', () => {
    const t = applyRequestForm(FULL, 'Нужны слайды для модуля про pandas.')
    expect(t.startsWith(buildStructuredPrefix(FULL))).toBe(true)
    expect(t.endsWith('Нужны слайды для модуля про pandas.')).toBe(true)
    expect(t).toContain('.\n\nНужны')
  })

  it('пустая форма не меняет текст, форма без текста остаётся полноценным запросом', () => {
    expect(applyRequestForm({ ...EMPTY_REQUEST_FORM }, '  Описал словами  ')).toBe('Описал словами')
    expect(applyRequestForm(FULL, '')).toBe(buildStructuredPrefix(FULL))
    expect(applyRequestForm(FULL, '').length).toBeGreaterThanOrEqual(5)
  })
})

describe('чек-лист проекта приказа (MET-19)', () => {
  it('четыре поля ручного заполнения и подпись о внесистемной регистрации', () => {
    expect(ORDER_CHECKLIST.map((x) => x.label)).toEqual(['Номер приказа', 'Дата приказа', 'ФИО преподавателей', 'Подписи'])
    expect(ORDER_CHECKLIST.every((x) => x.hint.length > 3)).toBe(true)
    expect(ORDER_NOTE).toContain('вне системы')
  })

  it('ключ в localStorage — ma.order.<id>, отметка roundtrip и битый JSON', () => {
    expect(orderStorageKey('prg-123')).toBe('ma.order.prg-123')
    expect(isOrderRegistered(null)).toBe(false)
    expect(isOrderRegistered('')).toBe(false)
    expect(isOrderRegistered('{битый')).toBe(false)
    expect(isOrderRegistered('{"done":false}')).toBe(false)
    const raw = orderRegisteredValue('2026-10-22T10:00:00Z')
    expect(JSON.parse(raw).done).toBe(true)
    expect(isOrderRegistered(raw)).toBe(true)
  })

  it('отметка сохраняется в localStorage и читается обратно', () => {
    localStorage.clear()
    const key = orderStorageKey('prg-x')
    expect(isOrderRegistered(localStorage.getItem(key))).toBe(false)
    localStorage.setItem(key, orderRegisteredValue())
    expect(isOrderRegistered(localStorage.getItem(key))).toBe(true)
    localStorage.clear()
  })
})

describe('programMetrics — нули не выдаются за результат (MET-8)', () => {
  it('данные есть: показываются время, затраты и токены, подписи нет', () => {
    const m = programMetrics({ timing_s: { skeleton: 3.4, kit: 40.6 }, usage: { calls: 5, cost_rub: 1.234, tokens_in: 100, tokens_out: 50 } })
    expect(m).toEqual({ skeleton: '3 с', kit: '41 с', model: '1.23 ₽ · 5 вызовов', tokens: '150', note: '' })
  })

  it('данных нет: «—» вместо нулей и подпись про автопрогон', () => {
    const m = programMetrics({ timing_s: {}, usage: { calls: 0, cost_rub: 0, tokens_in: 0, tokens_out: 0 } })
    expect(m.skeleton).toBe('—')
    expect(m.kit).toBe('—')
    expect(m.model).toBe('—')
    expect(m.tokens).toBe('—')
    expect(m.note.toLowerCase()).toContain('автопрогона')
  })

  it('пустой документ и время без вызовов модели не ломают блок', () => {
    expect(programMetrics(null).note).toContain('Метрики')
    const m = programMetrics({ timing_s: { skeleton: 2, kit: 9 }, usage: { calls: 0 } })
    expect(m.note).toBe('')
    expect(m.model).toBe('—')
    expect(m.tokens).toBe('—')
  })
})

describe('ruPlural — русские формы числа', () => {
  it('один/две-четыре/пять-двадцать и исключения 11–14', () => {
    expect([1, 2, 5, 11, 21, 22, 25].map((n) => ruPlural(n, 'неделя', 'недели', 'недель')))
      .toEqual(['неделя', 'недели', 'недель', 'недель', 'неделя', 'недели', 'недель'])
  })
})

beforeEach(() => localStorage.clear())
