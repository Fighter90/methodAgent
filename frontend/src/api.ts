export type Role = 'methodist' | 'expert' | 'head' | 'admin' | 'api'

export interface User { id: string; name: string; role: Role; title: string; login?: string; email?: string; roles?: Role[]; source?: string }

const KEY = 'ma.session'

/* token — токен доступа (30 мин), refresh — токен обновления (30 дней) для продления входа без пароля */
export interface Session { token: string; refresh?: string; user: User }

export function getSession(): Session | null {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function setSession(s: Session | null) {
  try {
    if (s) localStorage.setItem(KEY, JSON.stringify(s))
    else localStorage.removeItem(KEY)
  } catch {
    /* приватный режим браузера */
  }
}

export class ApiError extends Error {
  status: number
  details: unknown
  constructor(status: number, message: string, details?: unknown) {
    super(message)
    this.status = status
    this.details = details
  }
}

export async function api<T = any>(path: string, opts: RequestInit & { json?: unknown } = {}, retried = false): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers as Record<string, string>) }
  const s = getSession()
  // свой заголовок, а не Authorization: прокси хаба перехватывает запросы с Authorization
  if (s) headers['X-MA-Token'] = s.token
  let body = opts.body
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.json)
  }
  const safe = !opts.method || ['GET', 'HEAD'].includes(opts.method.toUpperCase())
  let res: Response | null = null
  // Чтение повторяем: короткий обрыв (перезапуск контейнера при выкладке) пользователь не должен видеть
  for (let attempt = 0; !res; attempt++) {
    try {
      res = await fetch(`/api/v1${path}`, { ...opts, headers, body })
    } catch {
      if (safe && attempt < 3) { await sleep(1000 * (attempt + 1)); continue }
      const state = await probe()
      if (state === 'hub') { reloadThroughHub(); throw new ApiError(0, 'Сессия хаба истекла, открываю вход заново…') }
      watchServer()
      throw new ApiError(0, safe ? NETWORK_MSG : 'Запрос не дошёл до сервера. Повторите действие через несколько секунд.')
    }
  }
  // токен доступа живёт 30 минут: один раз продлеваем вход токеном обновления и повторяем запрос
  if (res.status === 401 && s && !retried && !NO_REFRESH.test(path) && (await refreshSession())) return api<T>(path, opts, true)
  if (!res.ok) {
    let msg = `Ошибка ${res.status}`
    let details: unknown
    try {
      const j = await res.json()
      msg = j.message_ru || j.detail || msg
      details = j.details
    } catch {
      /* не JSON */
    }
    if (res.status === 401 && s) {
      // токен обновления истёк или выпущен до смены ключа: на страницу входа, а не баннер о связи
      setSession(null)
      if (!location.pathname.startsWith('/auth')) location.assign('/auth?expired=1')
    }
    throw new ApiError(res.status, msg, details)
  }
  const ct = res.headers.get('content-type') || ''
  return (ct.includes('json') ? res.json() : res.text()) as Promise<T>
}

// неверный пароль при входе — не повод продлевать сессию
const NO_REFRESH = /^\/auth\/(login|register|refresh)\b/
let refreshing: Promise<boolean> | null = null

/* Обмен токена обновления на новую пару (POST /auth/refresh); параллельные 401 ждут один и тот же обмен */
export function refreshSession(): Promise<boolean> {
  const s = getSession()
  if (!s?.refresh) return Promise.resolve(false)
  refreshing ||= (async () => {
    try {
      const r = await fetch('/api/v1/auth/refresh', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ refresh_token: s.refresh }) })
      if (!r.ok) return false
      const j = await r.json()
      // сессию могли сбросить (выход) пока шёл обмен — тогда не восстанавливаем
      if (!getSession()) return false
      setSession({ token: j.access_token, refresh: j.refresh_token, user: { ...s.user, ...j.user } })
      return true
    } catch {
      return false
    } finally {
      refreshing = null
    }
  })()
  return refreshing
}

export const NETWORK_MSG = 'Сервер временно недоступен, повторяю подключение…'

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/* 'hub' — хаб перенаправляет на свой вход (истекла его cookie), 'down' — сервер не отвечает, 'ok' — отвечает */
async function probe(): Promise<'ok' | 'hub' | 'down'> {
  try {
    const r = await fetch('/api/v1/health', { redirect: 'manual', cache: 'no-store' })
    if (r.type === 'opaqueredirect' || (r.status >= 300 && r.status < 400) || r.status === 401 || r.status === 403) return 'hub'
    // Наш сервер отвечает JSON {"status":"ok"}; страница входа хаба вместо него — тоже признак истёкшей сессии
    const j = await r.json().catch(() => null)
    if (j?.status === 'ok') return 'ok'
    return r.ok ? 'hub' : 'down'
  } catch {
    return 'down'
  }
}

/* Перезагрузка страницы проводит браузер через вход хаба и возвращает в демо; не чаще раза в минуту */
function reloadThroughHub() {
  try {
    const last = Number(sessionStorage.getItem('ma:hub-reload') || 0)
    if (Date.now() - last < 60000) { window.dispatchEvent(new Event('ma:offline')); return }
    sessionStorage.setItem('ma:hub-reload', String(Date.now()))
  } catch { /* хранилище недоступно */ }
  window.location.reload()
}

let watching = false
/* Пока сервер недоступен, проверяем его раз в 3 с и сообщаем, когда связь вернулась */
function watchServer() {
  window.dispatchEvent(new Event('ma:offline'))
  if (watching) return
  watching = true
  const tick = async () => {
    const state = await probe()
    if (state === 'ok') { watching = false; window.dispatchEvent(new Event('ma:online')); return }
    if (state === 'hub') { watching = false; reloadThroughHub(); return }
    setTimeout(tick, 3000)
  }
  setTimeout(tick, 3000)
}

/* refresh_token может отсутствовать у старого сервера — тогда вход не продлевается */
interface TokenPair { access_token: string; refresh_token?: string; user: User }

export async function login(login: string, password: string) {
  const r = await api<TokenPair>('/auth/login', { method: 'POST', json: { login, password } })
  setSession({ token: r.access_token, refresh: r.refresh_token, user: r.user })
  // у API-клиента в интерфейсе нет своих экранов: работает как методист, токен с ролью api остаётся для автопрогона
  if (r.user.role === 'api' && (r.user.roles || []).includes('methodist')) return switchRole('methodist')
  return r.user
}

export async function register(body: { name: string; login: string; email: string; password: string; consent: boolean }) {
  const r = await api<TokenPair>('/auth/register', { method: 'POST', json: body })
  setSession({ token: r.access_token, refresh: r.refresh_token, user: r.user })
  return r.user
}

export async function switchRole(role: string) {
  const r = await api<TokenPair>('/auth/switch-role', { method: 'POST', json: { role } })
  setSession({ token: r.access_token, refresh: r.refresh_token, user: r.user })
  return r.user
}

export interface AuthConfig {
  demo_accounts: { login: string; name: string; role: Role; title: string }[]
  demo_password: string
  registration_enabled: boolean
  registration_default_role: Role
  sso: { enabled: boolean; provider: string; display_name: string; configured: boolean; available: boolean }
}

export async function waitJob(jobId: string, onProgress?: (p: any) => void): Promise<any> {
  for (;;) {
    const j = await api(`/jobs/${jobId}`)
    onProgress?.(j.progress)
    if (j.status === 'done') return j
    if (j.status === 'failed') throw new ApiError(500, j.error || 'Задание завершилось ошибкой')
    await new Promise((r) => setTimeout(r, 1200))
  }
}

export async function download(programId: string, fmt: string) {
  const get = () => {
    const s = getSession()
    return fetch(`/api/v1/programs/${programId}/export/${fmt}`, { headers: s ? { 'X-MA-Token': s.token } : {} })
  }
  let res = await get()
  if (res.status === 401 && (await refreshSession())) res = await get()
  if (!res.ok) throw new ApiError(res.status, 'Не удалось выгрузить файл')
  const cd = res.headers.get('content-disposition') || ''
  const m = /filename\*=UTF-8''([^;]+)/.exec(cd)
  const name = m ? decodeURIComponent(m[1]) : `program.${fmt}`
  const blob = await res.blob()
  const a = document.createElement('a')
  a.href = URL.createObjectURL(blob)
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(a.href), 2000)
}

export const ROLE_LABEL: Record<string, string> = { methodist: 'методист', expert: 'эксперт', head: 'руководитель', admin: 'администратор', api: 'API' }

/* Что делает каждая роль. Роли не пересекаются: одна учётка может иметь несколько ролей, но в каждый момент работает в одной */
export const ROLE_CAN: Record<string, { can: string[]; cannot: string }> = {
  methodist: {
    can: ['создаёт программу по запросу или файлу и отвечает на вопросы агента', 'правит и утверждает каркас, собирает комплект', 'назначает экспертов на модули и отвечает на их замечания', 'отправляет программу руководителю, восстанавливает версии, выгружает DOCX/PDF/JSON'],
    cannot: 'не утверждает программу итогово, не ведёт пользователей и настройки',
  },
  expert: {
    can: ['видит только программы, где ему назначены модули', 'вычитывает свои модули: правки и замечания', 'принимает модуль или возвращает на доработку'],
    cannot: 'не создаёт программы, не правит каркас, не видит чужие модули',
  },
  head: {
    can: ['видит все программы, их качество, затраты и журнал', 'сравнивает версии и смотрит отчёт агента', 'утверждает программу или возвращает методисту'],
    cannot: 'не создаёт и не правит программы, не ведёт пользователей',
  },
  admin: {
    can: ['ведёт пользователей: создаёт, назначает роли, отключает', 'задаёт ключи и настройки агента, навыки и регистрацию', 'наполняет базу знаний и профиль организации', 'смотрит журнал действий'],
    cannot: 'не создаёт, не вычитывает и не утверждает программы',
  },
  api: {
    can: ['запускает автопрогон через API без вопросов', 'в интерфейсе работает как методист'],
    cannot: 'служебная учётка для интеграций',
  },
}

export const STATUS_LABEL: Record<string, string> = {
  draft: 'Черновик',
  questions: 'Нужны ответы',
  skeleton: 'Каркас на проверке',
  skeleton_approved: 'Каркас утверждён',
  generating: 'Собираю комплект',
  kit_ready: 'Комплект готов',
  on_review: 'Вычитка экспертов',
  on_approval: 'На утверждении',
  approved: 'Утверждена',
  returned: 'Возвращена',
  failed: 'Ошибка',
}
