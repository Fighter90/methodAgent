/*
 * UI e2e по ролям: вход через форму, стартовая страница роли, основные экраны без ошибок консоли,
 * перенаправление с запрещённых роли страниц, «Выйти», справка.
 *
 * Использует библиотеку playwright (без @playwright/test) и уже установленный Chromium:
 *   PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers NODE_PATH=$(npm root -g) node e2e/ui_roles.spec.cjs
 * Переменные: BASE_URL (по умолчанию http://127.0.0.1:8000), SHOTS_DIR (каталог скриншотов),
 * CHROMIUM_PATH (явный путь к chrome, если версия playwright не совпадает с браузером).
 * Перед запуском желательно прогнать scripts/e2e_regression.py — тогда есть программы и задания на вычитку.
 * Код выхода 1, если хотя бы одна проверка не прошла.
 */
'use strict'

const fs = require('fs')
const path = require('path')
const { chromium } = require('playwright')

const BASE = (process.env.BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')
const SHOTS = process.env.SHOTS_DIR || path.join(__dirname, '..', 'logs', 'e2e-shots')
const PASSWORD = 'demo'

let passed = 0
const failed = []
function check(name, ok, detail) {
  if (ok) { passed++; console.log(`PASS ${name}`) } else { failed.push(`${name}${detail ? ' — ' + detail : ''}`); console.log(`FAIL ${name}${detail ? ' — ' + detail : ''}`) }
  return ok
}

async function apiLogin(login) {
  const r = await fetch(`${BASE}/api/v1/auth/login`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ login, password: PASSWORD }) })
  return (await r.json()).access_token
}
async function apiGet(token, p) {
  const r = await fetch(`${BASE}/api/v1${p}`, { headers: { 'X-MA-Token': token } })
  return r.ok ? r.json() : null
}

function findChromium() {
  if (process.env.CHROMIUM_PATH) return process.env.CHROMIUM_PATH
  const root = process.env.PLAYWRIGHT_BROWSERS_PATH || '/opt/pw-browsers'
  try {
    for (const d of fs.readdirSync(root).filter((x) => /^chromium-\d+$/.test(x)).sort().reverse()) {
      const p = path.join(root, d, 'chrome-linux', 'chrome')
      if (fs.existsSync(p)) return p
    }
  } catch (_) { /* каталог браузеров не найден — пусть playwright ищет сам */ }
  return undefined
}

// Ожидаемые ответы API, которые интерфейс показывает как сообщение (не ошибка страницы)
const BENIGN = [/Failed to load resource: the server responded with a status of 40[134]/]

async function newPage(browser, label) {
  const ctx = await browser.newContext({ viewport: { width: 1360, height: 900 }, locale: 'ru-RU' })
  const page = await ctx.newPage()
  page.errors = []
  page.on('console', (m) => { if (m.type() === 'error' && !BENIGN.some((re) => re.test(m.text()))) page.errors.push(m.text()) })
  page.on('pageerror', (e) => page.errors.push(`pageerror: ${e.message}`))
  page.label = label
  return { ctx, page }
}

async function shot(page, name) {
  await page.screenshot({ path: path.join(SHOTS, `${page.label}-${name}.png`), fullPage: false })
}

async function screen(page, url, name, heading, extra) {
  page.errors.length = 0
  await page.goto(BASE + url, { waitUntil: 'networkidle' })
  let ok = true
  if (heading) {
    try { await page.getByRole('heading', { name: heading }).first().waitFor({ timeout: 10000 }) } catch (_) { ok = false }
    check(`${page.label}: ${name} — заголовок «${heading}»`, ok, ok ? '' : `url=${page.url()}`)
  }
  if (extra) await extra()
  await page.waitForTimeout(400)
  await shot(page, name)
  check(`${page.label}: ${name} — без ошибок консоли`, page.errors.length === 0, page.errors.slice(0, 3).join(' | '))
}

async function formLogin(page, login) {
  await page.goto(`${BASE}/auth`, { waitUntil: 'networkidle' })
  await page.fill('#login', login)
  await page.fill('#pw', PASSWORD)
  await page.locator('form').filter({ has: page.locator('#login') }).locator('button.btn-primary').click()
}

async function expectPath(page, want, name) {
  try {
    await page.waitForURL((u) => new URL(u).pathname === want, { timeout: 10000 })
    return check(name, true)
  } catch (_) {
    return check(name, false, `путь ${new URL(page.url()).pathname}, ждали ${want}`)
  }
}

async function logout(page) {
  await page.getByRole('button', { name: /Выйти/ }).first().click()
  await expectPath(page, '/auth', `${page.label}: «Выйти» ведёт на форму входа`)
  await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })
  await expectPath(page, '/auth', `${page.label}: после выхода /app → /auth`)
  const stored = await page.evaluate(() => Object.keys(localStorage).filter((k) => /ma/i.test(k)).map((k) => localStorage.getItem(k)).join(''))
  check(`${page.label}: после выхода токена в localStorage нет`, !/access_token/.test(stored))
}

async function run() {
  fs.mkdirSync(SHOTS, { recursive: true })
  const browser = await chromium.launch({ headless: true, executablePath: findChromium() })
  const tokens = {}
  for (const u of ['madina', 'timur', 'olga', 'ahmed', 'admin']) tokens[u] = await apiLogin(u)
  const programs = (await apiGet(tokens.madina, '/programs')) || []
  const anyProgram = programs[0]
  const reviews = { timur: (await apiGet(tokens.timur, '/reviews')) || [], olga: (await apiGet(tokens.olga, '/reviews')) || [] }

  // Без входа
  {
    const { ctx, page } = await newPage(browser, 'anon')
    await screen(page, '/', 'landing', null)
    await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })
    await expectPath(page, '/auth', 'anon: /app без входа → /auth')
    await screen(page, '/auth', 'login-form', null, async () => {
      check('anon: форма входа с полями логина и пароля', (await page.locator('#login').count()) === 1 && (await page.locator('#pw').count()) === 1)
    })
    await screen(page, '/help', 'help', 'Как работать с МетодАгентом')
    page.errors.length = 0
    await page.goto(`${BASE}/auth`, { waitUntil: 'networkidle' })
    await page.fill('#login', 'madina'); await page.fill('#pw', 'wrong-password')
    await page.locator('form').filter({ has: page.locator('#login') }).locator('button.btn-primary').click()
    let shown = true
    try { await page.getByText('Неверный логин или пароль').first().waitFor({ timeout: 5000 }) } catch (_) { shown = false }
    check('anon: неверный пароль — сообщение на форме', shown)
    await ctx.close()
  }

  // Методист
  {
    const { ctx, page } = await newPage(browser, 'methodist')
    await formLogin(page, 'madina')
    await expectPath(page, '/app', 'methodist: после входа — Программы (/app)')
    await screen(page, '/app', 'programs', 'Мои программы', async () => {
      check('methodist: форма новой программы', await page.getByRole('heading', { name: 'Новая программа' }).count() > 0)
      check('methodist: в меню нет «Администрирование»', await page.locator('header nav').getByRole('link', { name: 'Администрирование', exact: true }).count() === 0)
    })
    if (anyProgram) await screen(page, `/app/p/${anyProgram.id}`, 'program', null, async () => {
      let ok = true
      try { await page.getByText(anyProgram.title.slice(0, 20)).first().waitFor({ timeout: 10000 }) } catch (_) { ok = false }
      check('methodist: карточка программы показывает название', ok)
    })
    await screen(page, '/app/kb', 'kb', 'База знаний организации')
    await screen(page, '/app/me', 'me', 'Личный кабинет')
    await page.goto(`${BASE}/app/admin`, { waitUntil: 'networkidle' })
    await expectPath(page, '/app', 'methodist: /app/admin → /app')
    await screen(page, '/help', 'help', 'Как работать с МетодАгентом')
    await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })
    await logout(page)
    await ctx.close()
  }

  // Эксперты
  for (const user of ['timur', 'olga']) {
    const { ctx, page } = await newPage(browser, `expert-${user}`)
    await formLogin(page, user)
    await expectPath(page, '/app/reviews', `expert-${user}: после входа — Вычитка (/app/reviews)`)
    await screen(page, '/app/reviews', 'reviews', 'Вычитка модулей', async () => {
      check(`expert-${user}: в меню нет «Администрирование» и «База знаний»`,
        await page.locator('header nav').getByRole('link', { name: 'Администрирование', exact: true }).count() === 0 && await page.locator('header nav').getByRole('link', { name: 'База знаний', exact: true }).count() === 0)
      for (const r of reviews[user].slice(0, 2)) {
        check(`expert-${user}: в списке модуль «${r.title.slice(0, 30)}»`, await page.getByText(r.title.slice(0, 25)).count() > 0)
      }
      const foreign = [...reviews[user === 'timur' ? 'olga' : 'timur']].filter((r) => !reviews[user].some((x) => x.title === r.title))
      if (foreign.length) check(`expert-${user}: чужих модулей в списке нет`, await page.getByText(foreign[0].title.slice(0, 25), { exact: false }).count() === 0)
    })
    if (reviews[user][0]) await screen(page, `/app/p/${reviews[user][0].program_id}`, 'program', null)
    await screen(page, '/app', 'programs', null)
    await page.goto(`${BASE}/app/admin`, { waitUntil: 'networkidle' })
    await expectPath(page, '/app', `expert-${user}: /app/admin → /app`)
    await screen(page, '/help', 'help', 'Как работать с МетодАгентом')
    await page.goto(`${BASE}/app/reviews`, { waitUntil: 'networkidle' })
    await logout(page)
    await ctx.close()
  }

  // Руководитель
  {
    const { ctx, page } = await newPage(browser, 'head')
    await formLogin(page, 'ahmed')
    await expectPath(page, '/app', 'head: после входа — Программы (/app)')
    await screen(page, '/app', 'programs', 'Программы организации', async () => {
      check('head: нет формы новой программы', await page.getByRole('heading', { name: 'Новая программа' }).count() === 0)
    })
    const approved = programs.find((p) => p.status === 'approved') || anyProgram
    if (approved) await screen(page, `/app/p/${approved.id}`, 'program', null)
    await screen(page, '/app/kb', 'kb', 'База знаний организации')
    await page.goto(`${BASE}/app/admin`, { waitUntil: 'networkidle' })
    await expectPath(page, '/app', 'head: /app/admin → /app')
    await screen(page, '/help', 'help', 'Как работать с МетодАгентом')
    await page.goto(`${BASE}/app`, { waitUntil: 'networkidle' })
    await logout(page)
    await ctx.close()
  }

  // Администратор
  {
    const { ctx, page } = await newPage(browser, 'admin')
    await formLogin(page, 'admin')
    await expectPath(page, '/app/admin', 'admin: после входа — Администрирование (/app/admin)')
    await screen(page, '/app/admin', 'admin-users', 'Администрирование', async () => {
      check('admin: в меню нет «Программы»', await page.locator('header nav').getByRole('link', { name: 'Программы', exact: true }).count() === 0)
      for (const [tab, name] of [['Настройки агента', 'settings'], ['Навыки агента', 'skills'], ['Журнал', 'journal'], ['Пользователи', 'users']]) {
        page.errors.length = 0
        await page.getByRole('tab', { name: new RegExp(tab) }).click()
        await page.waitForLoadState('networkidle')
        await page.waitForTimeout(300)
        await shot(page, `admin-${name}`)
        check(`admin: вкладка «${tab}» без ошибок консоли`, page.errors.length === 0, page.errors.slice(0, 3).join(' | '))
      }
      const body = await page.locator('body').innerText()
      check('admin: вкладка пользователей показывает демо-учётки', /madina/.test(body) && /ahmed/.test(body))
    })
    await page.getByRole('tab', { name: /Настройки агента/ }).click()
    await page.waitForLoadState('networkidle')
    check('admin: секреты в настройках не показываются открытым текстом', !(await page.locator('body').innerText()).includes('smtp-'))
    await screen(page, '/app/kb', 'kb', 'База знаний организации')
    await screen(page, '/app/me', 'me', 'Личный кабинет')
    for (const p of ['/app', '/app/reviews', `/app/p/${anyProgram ? anyProgram.id : 'x'}`]) {
      await page.goto(BASE + p, { waitUntil: 'networkidle' })
      await expectPath(page, '/app/admin', `admin: ${p} → /app/admin`)
    }
    await screen(page, '/help', 'help', 'Как работать с МетодАгентом')
    await page.goto(`${BASE}/app/admin`, { waitUntil: 'networkidle' })
    await logout(page)
    await ctx.close()
  }

  await browser.close()
  console.log(`\n== Итого UI: ${passed}/${passed + failed.length} PASS, ${failed.length} FAIL; скриншоты: ${SHOTS}`)
  for (const f of failed) console.log(`  FAIL ${f}`)
  process.exit(failed.length ? 1 : 0)
}

run().catch((e) => { console.error(e); process.exit(2) })
