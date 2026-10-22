import { beforeEach, describe, expect, it } from 'vitest'
import {
  buildRequestParams, EMPTY_REQUEST_FORM, FORM_ONLY_REQUEST, hasRequestParams, isOrderRegistered,
  ORDER_CHECKLIST, ORDER_NOTE, orderRegisteredValue, orderStorageKey, programMetrics,
  VOLUME_PRESETS, type RequestFormFields,
} from '../kit'

/* SPEC-UI-28, SPEC-UI-29, SPEC-UI-30: чистые функции формы запроса (сборка params для POST /programs),
 * чек-листа приказа и честных метрик */

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

describe('buildRequestParams — сборка params для POST /programs (MET-53/R09)', () => {
  it('заполненные поля уходят с именами модели Params бэкенда', () => {
    expect(buildRequestParams(FULL)).toEqual({
      title: 'Анализ данных на Python',
      program_type: 'dpp_pk',
      audience: 'сотрудники банков',
      entry_level: 'работу в Excel',
      volume_h: 36,
      form: 'очно-заочная',
      duration_weeks: 4,
      final_assessment_form: 'Защита проекта',
    })
  })

  it('«предложит агент» и пустые поля в params не попадают, пробелы по краям обрезаются', () => {
    expect(buildRequestParams({ ...EMPTY_REQUEST_FORM })).toEqual({})
    expect(buildRequestParams({
      ...FULL, title: '  ', audience: ' учителя школ ', entry_level: '', program_type: '', form: '', final_assessment: '',
    })).toEqual({ audience: 'учителя школ', volume_h: 36, duration_weeks: 4 })
  })

  it('пресеты объёма 16/36/72/256 отправляются полем volume_h и только им', () => {
    expect(VOLUME_PRESETS).toEqual([16, 36, 72, 256])
    for (const v of VOLUME_PRESETS) {
      expect(buildRequestParams({ ...EMPTY_REQUEST_FORM, volume_h: v })).toEqual({ volume_h: v })
    }
  })

  it('срок в месяцах переводится в недели как в intake бэкенда (1 месяц ≈ 4.3 недели)', () => {
    expect(buildRequestParams({ ...EMPTY_REQUEST_FORM, duration_value: 1, duration_unit: 'months' }).duration_weeks).toBe(4.3)
    expect(buildRequestParams({ ...EMPTY_REQUEST_FORM, duration_value: 2, duration_unit: 'months' }).duration_weeks).toBe(8.6)
    expect(buildRequestParams({ ...EMPTY_REQUEST_FORM, duration_value: 3, duration_unit: 'weeks' }).duration_weeks).toBe(3)
  })

  it('нулевые и отрицательные объём и срок не отправляются', () => {
    expect(buildRequestParams({ ...FULL, volume_h: 0 })).not.toHaveProperty('volume_h')
    expect(buildRequestParams({ ...FULL, volume_h: -16 })).not.toHaveProperty('volume_h')
    expect(buildRequestParams({ ...FULL, duration_value: 0 })).not.toHaveProperty('duration_weeks')
  })

  it('заглушка текста для отправки формы без текста удовлетворяет минимуму request бэкенда (5 символов)', () => {
    expect(FORM_ONLY_REQUEST.length).toBeGreaterThanOrEqual(5)
  })

  it('hasRequestParams отличает пустую форму от формы с хоть одним полем', () => {
    expect(hasRequestParams({})).toBe(false)
    expect(hasRequestParams(buildRequestParams(EMPTY_REQUEST_FORM))).toBe(false)
    expect(hasRequestParams(buildRequestParams(FULL))).toBe(true)
    expect(hasRequestParams({ volume_h: 16 })).toBe(true)
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

beforeEach(() => localStorage.clear())
