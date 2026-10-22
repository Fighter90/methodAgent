// Валидация форм на клиенте — те же правила, что на сервере (auth/service.py), SPEC-UI-18.
export const LOGIN_RX = /^[a-z0-9][a-z0-9._-]{2,31}$/
export const EMAIL_RX = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function loginError(raw: string): string | null {
  return LOGIN_RX.test(raw.trim().toLowerCase()) ? null : 'Логин: 3–32 символа, латиница, цифры, точка, дефис или подчёркивание'
}

export function emailError(raw: string): string | null {
  const email = raw.trim()
  return !email || EMAIL_RX.test(email) ? null : 'Некорректный адрес почты'
}

export function passwordError(pw: string): string | null {
  return pw.length < 8 || !/\d/.test(pw) || !/\p{L}/u.test(pw) ? 'Пароль: не меньше 8 символов, буква и цифра' : null
}

// Вложения: тот же белый список и предел, что на сервере (core/uploads.py, SPEC-API-41/42) —
// неподходящий файл отклоняется сразу, без кодирования в base64 и без отправки на сервер.
export const FILE_EXT = ['.docx', '.pdf', '.txt', '.md']
export const FILE_ACCEPT = FILE_EXT.join(',')
export const MAX_FILE_MB = 20
export const MAX_FILES = 5

export function fileError(f: { name: string; size: number }): string | null {
  const dot = f.name.lastIndexOf('.')
  const ext = dot > 0 ? f.name.slice(dot).toLowerCase() : ''
  if (ext && !FILE_EXT.includes(ext)) return `«${f.name}»: формат ${ext} не поддерживается — принимаются .docx, .pdf, .txt и .md`
  if (f.size === 0) return `«${f.name}»: файл пустой`
  if (f.size > MAX_FILE_MB * 1024 * 1024) return `«${f.name}»: больше ${MAX_FILE_MB} МБ`
  return null
}
