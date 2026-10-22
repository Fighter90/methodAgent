import { describe, expect, it } from 'vitest'
import { emailError, loginError, passwordError } from '../validate'

describe('SPEC-UI-18: валидация регистрации на клиенте — те же правила, что на сервере', () => {
  it('логин: 3–32 символа, латиница-строчная, цифры, точка, дефис, подчёркивание', () => {
    expect(loginError('madina')).toBeNull()
    expect(loginError('user_2.name')).toBeNull()
    expect(loginError('Ab')).not.toBeNull() // заглавная и короткий
    expect(loginError('абв')).not.toBeNull() // кириллица
    expect(loginError('x')).not.toBeNull()
    expect(loginError('very-long-login-name-exceeding-32-characters')).not.toBeNull()
  })

  it('пароль: от 8 символов, хотя бы буква и цифра', () => {
    expect(passwordError('Passw0rd1')).toBeNull()
    expect(passwordError('kot1')).not.toBeNull() // короче 8
    expect(passwordError('только буквы без цифры')).not.toBeNull()
    expect(passwordError('12345678')).not.toBeNull() // без букв
  })

  it('почта необязательна, но заполненная должна быть корректной', () => {
    expect(emailError('')).toBeNull()
    expect(emailError('a@b.ru')).toBeNull()
    expect(emailError('не-почта')).not.toBeNull()
  })
})
