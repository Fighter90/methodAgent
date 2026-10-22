import { describe, expect, it } from 'vitest'
import { emailError, FILE_ACCEPT, fileError, loginError, passwordError } from '../validate'

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

describe('SPEC-UI-31: вложения проверяются на клиенте до отправки — белый список и 20 МБ, как на сервере', () => {
  it('разрешённые расширения и файл без расширения проходят', () => {
    expect(fileError({ name: 'program.DOCX', size: 1000 })).toBeNull()
    expect(fileError({ name: 'ref.pdf', size: 1000 })).toBeNull()
    expect(fileError({ name: 'notes.md', size: 10 })).toBeNull()
    expect(fileError({ name: 'Программа АЦР', size: 10 })).toBeNull()
  })
  it('чужой тип, пустой и слишком большой файл отклоняются с понятным текстом', () => {
    expect(fileError({ name: 'setup.exe', size: 10 })).toContain('.exe не поддерживается')
    expect(fileError({ name: 'a.txt', size: 0 })).toContain('пустой')
    expect(fileError({ name: 'big.pdf', size: 20 * 1024 * 1024 + 1 })).toContain('больше 20 МБ')
    expect(FILE_ACCEPT).toBe('.docx,.pdf,.txt,.md')
  })
})
