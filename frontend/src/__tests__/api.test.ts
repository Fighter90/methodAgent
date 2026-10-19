import { beforeEach, describe, expect, it, vi } from 'vitest'
import { api, ApiError, getSession, login, refreshSession, ROLE_CAN, ROLE_LABEL, setSession, STATUS_LABEL, waitJob } from '../api'

const user = { id: 'u1', name: 'Методист', role: 'methodist' as const, title: '' }

function jsonResponse(body: unknown, status = 200) {
  return new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } })
}

beforeEach(() => {
  localStorage.clear()
})

describe('сессия', () => {
  it('сохраняется и очищается в localStorage', () => {
    expect(getSession()).toBeNull()
    setSession({ token: 't', user })
    expect(getSession()).toEqual({ token: 't', user })
    setSession(null)
    expect(getSession()).toBeNull()
  })

  it('битое значение не роняет приложение', () => {
    localStorage.setItem('ma.session', '{')
    expect(getSession()).toBeNull()
  })
})

describe('api()', () => {
  it('передаёт токен в X-MA-Token, а не в Authorization, и сериализует json', async () => {
    setSession({ token: 'tok', user })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ ok: true }))
    const r = await api('/programs', { method: 'POST', json: { a: 1 } })
    expect(r).toEqual({ ok: true })
    const [url, init] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/v1/programs')
    const headers = init!.headers as Record<string, string>
    expect(headers['X-MA-Token']).toBe('tok')
    expect(headers.Authorization).toBeUndefined()
    expect(headers['Content-Type']).toBe('application/json')
    expect(init!.body).toBe('{"a":1}')
  })

  it('показывает message_ru из ответа об ошибке и детали', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ message_ru: 'Нет доступа', details: { x: 1 } }, 403))
    const err = await api('/programs/1').catch((e) => e)
    expect(err).toBeInstanceOf(ApiError)
    expect(err.status).toBe(403)
    expect(err.message).toBe('Нет доступа')
    expect(err.details).toEqual({ x: 1 })
  })

  it('при 401 сбрасывает сессию и ведёт на вход', async () => {
    setSession({ token: 'old', user })
    const assign = vi.fn()
    vi.stubGlobal('location', { pathname: '/app', assign })
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ detail: 'expired' }, 401))
    await expect(api('/me')).rejects.toMatchObject({ status: 401 })
    expect(getSession()).toBeNull()
    expect(assign).toHaveBeenCalledWith('/auth?expired=1')
    vi.unstubAllGlobals()
  })

  it('возвращает текст для не-JSON ответа', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('plain', { headers: { 'content-type': 'text/plain' } }))
    expect(await api('/x')).toBe('plain')
  })
})

describe('токен обновления', () => {
  it('при 401 один раз обменивает refresh_token и повторяет запрос с новым токеном', async () => {
    setSession({ token: 'old', refresh: 'r1', user })
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ message_ru: 'Токен недействителен или истёк' }, 401))
      .mockResolvedValueOnce(jsonResponse({ access_token: 'new', refresh_token: 'r2', user }))
      .mockResolvedValueOnce(jsonResponse({ ok: 1 }))
    expect(await api('/programs')).toEqual({ ok: 1 })
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/auth/refresh')
    expect(JSON.parse(fetchMock.mock.calls[1][1]!.body as string)).toEqual({ refresh_token: 'r1' })
    expect((fetchMock.mock.calls[2][1]!.headers as Record<string, string>)['X-MA-Token']).toBe('new')
    expect(getSession()).toMatchObject({ token: 'new', refresh: 'r2' })
  })

  it('если обмен не удался — сессия сбрасывается и переход на вход', async () => {
    setSession({ token: 'old', refresh: 'bad', user })
    const assign = vi.fn()
    vi.stubGlobal('location', { pathname: '/app', assign })
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ message_ru: 'истёк' }, 401))
      .mockResolvedValueOnce(jsonResponse({ message_ru: 'Нужен токен обновления' }, 401))
    await expect(api('/me')).rejects.toMatchObject({ status: 401 })
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(getSession()).toBeNull()
    expect(assign).toHaveBeenCalledWith('/auth?expired=1')
    vi.unstubAllGlobals()
  })

  it('повторный 401 после обмена не зацикливается', async () => {
    setSession({ token: 'old', refresh: 'r1', user })
    vi.stubGlobal('location', { pathname: '/app', assign: vi.fn() })
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({}, 401))
      .mockResolvedValueOnce(jsonResponse({ access_token: 'new', refresh_token: 'r2', user }))
      .mockResolvedValueOnce(jsonResponse({}, 401))
    await expect(api('/me')).rejects.toMatchObject({ status: 401 })
    expect(fetchMock).toHaveBeenCalledTimes(3)
    expect(getSession()).toBeNull()
    vi.unstubAllGlobals()
  })

  it('неверный пароль при входе не запускает обмен токена', async () => {
    setSession({ token: 'old', refresh: 'r1', user })
    vi.stubGlobal('location', { pathname: '/auth', assign: vi.fn() })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ message_ru: 'Неверный логин или пароль' }, 401))
    await expect(login('m', 'bad')).rejects.toThrow('Неверный логин или пароль')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    vi.unstubAllGlobals()
  })

  it('без refresh_token обмен не выполняется, параллельные вызовы делят один запрос', async () => {
    setSession({ token: 't', user })
    expect(await refreshSession()).toBe(false)
    setSession({ token: 't', refresh: 'r1', user })
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ access_token: 'n', refresh_token: 'r2', user }))
    const [a, b] = await Promise.all([refreshSession(), refreshSession()])
    expect(a && b).toBe(true)
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })
})

describe('login()', () => {
  it('сохраняет токен доступа, токен обновления и пользователя', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ access_token: 'a', refresh_token: 'r', user }))
    expect(await login('m', 'p')).toEqual(user)
    expect(getSession()).toMatchObject({ token: 'a', refresh: 'r' })
  })

  it('API-клиент с ролью методиста переключается в методиста', async () => {
    const apiUser = { ...user, role: 'api', roles: ['api', 'methodist'] }
    const fetchMock = vi.spyOn(globalThis, 'fetch')
      .mockResolvedValueOnce(jsonResponse({ access_token: 'a', user: apiUser }))
      .mockResolvedValueOnce(jsonResponse({ access_token: 'b', user }))
    const u = await login('api', 'p')
    expect(u.role).toBe('methodist')
    expect(fetchMock.mock.calls[1][0]).toBe('/api/v1/auth/switch-role')
    expect(getSession()?.token).toBe('b')
  })
})

describe('waitJob()', () => {
  it('отдаёт прогресс и результат готового задания', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ status: 'done', progress: { pct: 100 } }))
    const onProgress = vi.fn()
    const j = await waitJob('j1', onProgress)
    expect(j.status).toBe('done')
    expect(onProgress).toHaveBeenCalledWith({ pct: 100 })
  })

  it('бросает ошибку упавшего задания', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(jsonResponse({ status: 'failed', error: 'Шлюз недоступен' }))
    await expect(waitJob('j1')).rejects.toThrow('Шлюз недоступен')
  })
})

describe('справочники ролей и статусов', () => {
  it('у каждой роли есть подпись и описание прав', () => {
    for (const role of ['methodist', 'expert', 'head', 'admin', 'api']) {
      expect(ROLE_LABEL[role]).toBeTruthy()
      expect(ROLE_CAN[role].can.length).toBeGreaterThan(0)
      expect(ROLE_CAN[role].cannot).toBeTruthy()
    }
  })

  it('статусы жизненного цикла программы подписаны по-русски', () => {
    for (const s of ['draft', 'skeleton', 'kit_ready', 'on_review', 'on_approval']) {
      expect(STATUS_LABEL[s]).toMatch(/[а-яё]/i)
    }
  })
})
