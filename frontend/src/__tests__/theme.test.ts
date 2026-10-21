import { createElement } from 'react'
import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import { useTheme } from '../components/ui'

let sink: { div: HTMLDivElement; root: { unmount: () => void } } | null = null

beforeEach(() => {
  localStorage.clear()
  document.documentElement.removeAttribute('data-theme')
})

afterEach(() => {
  sink?.root.unmount()
  sink?.div.remove()
  sink = null
})

describe('тема интерфейса', () => {
  it('SPEC-UI-20: выбор темы запоминается в ma.theme и переключается', async () => {
    localStorage.setItem('ma.theme', 'dark')
    const div = document.createElement('div')
    document.body.append(div)
    let theme = ''
    let toggle: () => void = () => {}
    function Probe() {
      const [t, tg] = useTheme()
      theme = t
      toggle = tg
      return null
    }
    const root = createRoot(div)
    sink = { div, root }
    await act(async () => {
      root.render(createElement(Probe))
    })
    expect(theme).toBe('dark')
    expect(document.documentElement.getAttribute('data-theme')).toBe('dark')
    await act(async () => {
      toggle()
    })
    expect(theme).toBe('light')
    expect(localStorage.getItem('ma.theme')).toBe('light')
    expect(document.documentElement.getAttribute('data-theme')).toBe('light')
  })

  it('SPEC-UI-20: без сохранённого выбора — светлая тема', async () => {
    const div = document.createElement('div')
    document.body.append(div)
    let theme = ''
    function Probe() {
      const [t] = useTheme()
      theme = t
      return null
    }
    const root = createRoot(div)
    sink = { div, root }
    await act(async () => {
      root.render(createElement(Probe))
    })
    expect(theme).toBe('light')
  })
})
