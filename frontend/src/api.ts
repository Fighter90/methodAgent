export type Role = 'methodist' | 'expert' | 'head' | 'admin' | 'api'

export interface User { id: string; name: string; role: Role; title: string; login?: string; email?: string; roles?: Role[]; source?: string }

const KEY = 'ma.session'

export function getSession(): { token: string; user: User } | null {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? JSON.parse(raw) : null
  } catch {
    return null
  }
}

export function setSession(s: { token: string; user: User } | null) {
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

export async function api<T = any>(path: string, opts: RequestInit & { json?: unknown } = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers as Record<string, string>) }
  const s = getSession()
  if (s) headers['Authorization'] = `Bearer ${s.token}`
  let body = opts.body
  if (opts.json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(opts.json)
  }
  let res: Response
  try {
    res = await fetch(`/api/v1${path}`, { ...opts, headers, body })
  } catch {
    // Запрос оборван до сервера: нет сети или истекла сессия хаба, который пускает на адрес команды только с его cookie
    window.dispatchEvent(new Event('ma:offline'))
    throw new ApiError(0, NETWORK_MSG)
  }
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
    if (res.status === 401) setSession(null)
    throw new ApiError(res.status, msg, details)
  }
  const ct = res.headers.get('content-type') || ''
  return (ct.includes('json') ? res.json() : res.text()) as Promise<T>
}

export const NETWORK_MSG = 'Нет связи с сервером. Если демо открыто через хаб, его сессия могла истечь: обновите страницу.'

export async function login(login: string, password: string) {
  const r = await api<{ access_token: string; user: User }>('/auth/login', { method: 'POST', json: { login, password } })
  setSession({ token: r.access_token, user: r.user })
  return r.user
}

export async function register(body: { name: string; login: string; email: string; password: string; consent: boolean }) {
  const r = await api<{ access_token: string; user: User }>('/auth/register', { method: 'POST', json: body })
  setSession({ token: r.access_token, user: r.user })
  return r.user
}

export async function switchRole(role: string) {
  const r = await api<{ access_token: string; user: User }>('/auth/switch-role', { method: 'POST', json: { role } })
  setSession({ token: r.access_token, user: r.user })
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
  const s = getSession()
  const res = await fetch(`/api/v1/programs/${programId}/export/${fmt}`, { headers: s ? { Authorization: `Bearer ${s.token}` } : {} })
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
