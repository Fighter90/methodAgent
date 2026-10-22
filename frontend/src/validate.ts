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
