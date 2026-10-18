import { useEffect, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Building2, Check, Eye, EyeOff, LockKeyhole, RefreshCw, ShieldCheck, Sparkles, UserPlus } from 'lucide-react'
import { api, ApiError, login, register, ROLE_LABEL, type AuthConfig } from '../api'
import { Logo, Spinner, useMouseParallax, useToast } from '../components/ui'

// Подписи плиток демо-профиля АЦР; сами учётки приходят с сервера (/auth/config)
const TILE_TITLE: Record<string, string> = {
  methodist: 'Методист: создаёт программы, правит каркас и комплект, назначает экспертов',
  expert: 'Эксперт: вычитывает только назначенные ему модули, оставляет замечания',
  head: 'Руководитель: утверждает программы, видит качество, затраты и журнал',
  admin: 'Администратор: полный доступ, пользователи и роли, ключи и настройки агента',
  api: 'API-клиент: автопрогон через API без вопросов; в интерфейсе работает как методист',
}

/* Все демо-учётки на случай, когда сервер (или хаб) не ответил: форма входа не должна оставаться пустой */
const DEMO_FALLBACK: AuthConfig['demo_accounts'] = [
  { login: 'madina', name: 'Мадина', role: 'methodist', title: 'Методист' },
  { login: 'timur', name: 'Тимур А.', role: 'expert', title: 'Эксперт-преподаватель' },
  { login: 'olga', name: 'Ольга К.', role: 'expert', title: 'Эксперт-преподаватель' },
  { login: 'ahmed', name: 'Ахмед', role: 'head', title: 'Руководитель учебного центра' },
  { login: 'admin', name: 'Администратор', role: 'admin', title: 'Администратор профиля' },
  { login: 'api', name: 'API-клиент', role: 'api', title: 'Автопрогон' },
]

type Mode = 'login' | 'register'

export default function Login() {
  const [params, setParams] = useSearchParams()
  const mode: Mode = params.get('mode') === 'register' ? 'register' : 'login'
  const [cfg, setCfg] = useState<AuthConfig | null>(null)
  const [loginName, setLoginName] = useState('madina')
  const [password, setPassword] = useState('demo')
  const [showPw, setShowPw] = useState(false)
  const [reg, setReg] = useState({ name: '', login: '', email: '', password: '', confirm: '', consent: false })
  const [error, setError] = useState<{ text: string; offline?: boolean } | null>(null)
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()
  const toast = useToast()
  const m = useMouseParallax(1)
  const L = (d: number) => ({ transform: `translate3d(${m.x * d}px, ${m.y * d}px, 0)` })

  useEffect(() => {
    const load = () => api<AuthConfig>('/auth/config').then((c) => {
      setCfg(c)
      setError((e) => (e?.offline ? null : e))
      if (!c.demo_accounts.length) { setLoginName(''); setPassword('') }
    }).catch((e) => setError({ text: e.message, offline: e instanceof ApiError && e.status === 0 }))
    load()
    // сервер вернулся после перезапуска: убираем ошибку и подгружаем учётки без ручного обновления
    window.addEventListener('ma:online', load)
    return () => window.removeEventListener('ma:online', load)
  }, [])

  const switchMode = (next: Mode) => {
    const p = new URLSearchParams(params)
    if (next === 'register') p.set('mode', 'register')
    else p.delete('mode')
    setParams(p, { replace: true })
    setError(null)
  }

  const fail = (e: any) => setError({ text: e.message || 'Не удалось выполнить запрос', offline: e instanceof ApiError && e.status === 0 })
  const enter = (u: { name: string; role: string }) => {
    toast(`Здравствуйте, ${u.name}!`)
    nav(u.role === 'expert' ? '/app/reviews' : u.role === 'admin' ? '/app/admin' : '/app')
  }

  async function submitLogin(e: React.FormEvent) {
    e.preventDefault()
    if (!loginName.trim() || !password) return setError({ text: 'Введите логин и пароль' })
    setBusy(true); setError(null)
    try { enter(await login(loginName.trim(), password)) } catch (err) { fail(err) } finally { setBusy(false) }
  }

  async function submitRegister(e: React.FormEvent) {
    e.preventDefault()
    if (reg.name.trim().length < 2) return setError({ text: 'Укажите имя' })
    if (!/^[a-z0-9][a-z0-9._-]{2,31}$/.test(reg.login.trim().toLowerCase())) return setError({ text: 'Логин: 3–32 символа, латиница, цифры, точка, дефис или подчёркивание' })
    if (reg.email && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(reg.email.trim())) return setError({ text: 'Некорректный адрес почты' })
    if (reg.password.length < 8 || !/\d/.test(reg.password) || !/\p{L}/u.test(reg.password)) return setError({ text: 'Пароль: не меньше 8 символов, буква и цифра' })
    if (reg.password !== reg.confirm) return setError({ text: 'Пароли не совпадают' })
    if (!reg.consent) return setError({ text: 'Нужно согласие на обработку персональных данных' })
    setBusy(true); setError(null)
    try {
      const u = await register({ name: reg.name.trim(), login: reg.login.trim().toLowerCase(), email: reg.email.trim(), password: reg.password, consent: reg.consent })
      toast(`Учётная запись создана. Роль: ${ROLE_LABEL[u.role]}. Права расширяет администратор.`)
      nav(u.role === 'expert' ? '/app/reviews' : '/app')
    } catch (err) { fail(err) } finally { setBusy(false) }
  }

  const sso = cfg?.sso
  const demoAccounts = cfg ? cfg.demo_accounts : DEMO_FALLBACK
  const demoPassword = cfg?.demo_password || 'demo'
  const pwToggle = (
    <button type="button" className="icon-btn pw-eye" onClick={() => setShowPw((x) => !x)} aria-label={showPw ? 'Скрыть пароль' : 'Показать пароль'}>
      {showPw ? <EyeOff size={16} /> : <Eye size={16} />}
    </button>
  )

  return (
    <div className="auth">
      <aside className="auth-art">
        <div className="hero-bg">
          <div className="orb o1 auth-layer" style={{ ...L(-50), top: -200, left: -160 }} />
          <div className="orb o2 auth-layer" style={{ ...L(40), bottom: -220, right: -160 }} />
          <div className="grid-floor auth-layer" style={L(-14)} />
          <div className="noise" />
        </div>
        <div className="orbit-wrap"><span className="orbit-dot" /></div>

        <div style={{ position: 'relative', zIndex: 2 }} className="row">
          <Logo light />
          <div className="grow" />
          <Link to="/" className="btn btn-glass btn-sm"><ArrowLeft size={15} /> На главную</Link>
        </div>

        <div style={{ position: 'relative', zIndex: 2, maxWidth: 560 }} className="stagger">
          <span className="eyebrow"><span className="dot" />Рабочее место методического отдела</span>
          <h1 className="display" style={{ fontSize: 'clamp(34px, 4.4vw, 60px)' }}>Один запрос —<br /><span className="grad-text">полный комплект программы</span></h1>
          <p className="lead">
            Опишите программу своими словами. Агент определит тип и шаблон АЦР, задаст недостающие вопросы, предложит каркас с проверенными часами и после вашего утверждения соберёт тесты, задания, лекции и слайды.
          </p>
          <div style={{ display: 'grid', gap: 10, marginTop: 24 }}>
            {['Часы считает солвер, а не модель', 'Профстандарты и НПА только из реестра', 'Реквизиты приказа, ФИО и подписи заполняют люди'].map((t) => (
              <div key={t} className="row" style={{ gap: 10, color: '#cfd6dd', fontSize: 15 }}>
                <span style={{ width: 22, height: 22, borderRadius: 8, background: 'rgba(33,160,56,.2)', color: '#5DD879', display: 'grid', placeItems: 'center' }}><Check size={14} /></span>{t}
              </div>
            ))}
          </div>
        </div>

        <div style={{ position: 'relative', zIndex: 2, height: 150 }}>
          <div className="float-card auth-layer" style={{ ...L(30), width: 270, left: 0, bottom: 0 }}>
            <h5>Проверка каркаса</h5>
            <div className="mini-check"><i>✓</i>Часы 72 из 72</div>
            <div className="mini-check"><i>✓</i>ПС 06.042 из реестра</div>
            <div className="mini-check"><i style={{ background: 'rgba(242,177,19,.18)', color: '#F5C451' }}>!</i>РО 4.2 — нужно решение</div>
          </div>
          <div className="float-card auth-layer" style={{ ...L(-24), width: 240, left: 300, bottom: 30, animation: 'float 7s ease-in-out infinite' }}>
            <div className="row" style={{ gap: 10 }}>
              <span className="avatar av-agent"><Sparkles size={14} /></span>
              <span className="tiny" style={{ color: '#cfd6dd' }}>Комплект собран: 10 из 10 блокирующих проверок</span>
            </div>
          </div>
        </div>
      </aside>

      <main className="auth-form-wrap">
        <div className="auth-form">
          <div className="row" style={{ gap: 10, marginBottom: 6 }}>
            <span className="glass-icon" style={{ background: 'var(--accent-soft)', color: 'var(--accent)', borderColor: 'transparent' }}>{mode === 'login' ? <LockKeyhole size={20} /> : <UserPlus size={20} />}</span>
          </div>
          <h2 className="h1" style={{ marginTop: 14 }}>{mode === 'login' ? 'Вход в МетодАгент' : 'Регистрация'}</h2>

          {(cfg?.registration_enabled ?? true) && (
            <div className="seg" role="tablist" style={{ margin: '6px 0 14px', gridTemplateColumns: '1fr 1fr' }}>
              <button role="tab" aria-selected={mode === 'login'} className={`seg-btn ${mode === 'login' ? 'active' : ''}`} onClick={() => switchMode('login')}>Вход</button>
              <button role="tab" aria-selected={mode === 'register'} className={`seg-btn ${mode === 'register' ? 'active' : ''}`} onClick={() => switchMode('register')}>Регистрация</button>
            </div>
          )}

          {error && (
            <div className="callout small" role="alert" style={{ borderColor: 'var(--err, #d64545)', marginBottom: 12 }}>
              {error.text}
              {error.offline && <button type="button" className="btn btn-soft btn-sm" style={{ marginLeft: 8 }} onClick={() => location.reload()}><RefreshCw size={13} /> Обновить страницу</button>}
            </div>
          )}

          {mode === 'login' ? (
            <form onSubmit={submitLogin} noValidate>
              {!!demoAccounts.length && (
                <>
                  <p className="muted" style={{ marginTop: 0 }}>Демо-пользователи с разными правами доступа. Нажмите на пользователя — логин и пароль подставятся в форму. Пароль у всех: <span className="kbd">{demoPassword}</span></p>
                  <div style={{ display: 'grid', gap: 8, margin: '12px 0 18px' }} className="stagger">
                    {demoAccounts.map((u) => (
                      <button type="button" key={u.login} className={`user-tile ${loginName === u.login ? 'sel' : ''}`} onClick={() => { setLoginName(u.login); setPassword(demoPassword); setError(null) }}>
                        <span className={`avatar av-${u.role}`} style={{ width: 38, height: 38 }}>{u.name[0]}</span>
                        <span className="grow">
                          <b style={{ display: 'block' }}>{u.name} <span className="small muted" style={{ fontWeight: 400 }}>· {u.login}</span></b>
                          <span className="small muted">{TILE_TITLE[u.role] || u.title}</span>
                        </span>
                        {loginName === u.login && <Check size={18} color="var(--accent)" />}
                      </button>
                    ))}
                  </div>
                  <p className="small muted" style={{ marginTop: -8, marginBottom: 16 }}>Новый пользователь после регистрации получает минимальные права: роль «{ROLE_LABEL[cfg?.registration_default_role || 'expert']}» без назначенных модулей. Расширить права может администратор.</p>
                </>
              )}
              {params.get('expired') && !error && <div className="callout small" style={{ marginBottom: 12 }}>Сессия истекла, войдите снова.</div>}
              <label className="label" htmlFor="login">Логин или почта</label>
              <input id="login" className="field" value={loginName} onChange={(e) => setLoginName(e.target.value)} autoComplete="username" placeholder="например, madina" />
              <label className="label" htmlFor="pw" style={{ marginTop: 12 }}>Пароль</label>
              <div className="pw-wrap">
                <input id="pw" className="field" type={showPw ? 'text' : 'password'} value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />
                {pwToggle}
              </div>
              <button className="btn btn-primary btn-lg" style={{ width: '100%', justifyContent: 'center', marginTop: 18 }} disabled={busy}>
                {busy ? <Spinner /> : <>Войти <ArrowRight size={18} /></>}
              </button>
              <button type="button" className="btn btn-ghost btn-lg" style={{ width: '100%', justifyContent: 'center', marginTop: 10 }} disabled
                title="Единый вход организации (OIDC или SAML) предусмотрен: параметры задаёт администратор, подключение — в следующей версии">
                <Building2 size={17} /> {sso?.enabled ? sso.display_name : 'Войти через SSO организации'} <span className="chip" style={{ marginLeft: 6 }}>скоро</span>
              </button>
              <p className="tiny muted" style={{ marginTop: 6 }}>Вход через SSO (OIDC или SAML) предусмотрен: администратор задаёт параметры в настройках, протокол подключается в следующей версии.</p>
            </form>
          ) : (
            <form onSubmit={submitRegister} noValidate>
              <p className="muted" style={{ marginTop: 0 }}>После регистрации вы получите минимальные права: роль «{ROLE_LABEL[cfg?.registration_default_role || 'expert']}». Расширить их может администратор.</p>
              <label className="label" htmlFor="r-name">Имя и фамилия</label>
              <input id="r-name" className="field" value={reg.name} onChange={(e) => setReg({ ...reg, name: e.target.value })} autoComplete="name" placeholder="Ирина Петрова" />
              <label className="label" htmlFor="r-login" style={{ marginTop: 12 }}>Логин</label>
              <input id="r-login" className="field" value={reg.login} onChange={(e) => setReg({ ...reg, login: e.target.value })} autoComplete="username" placeholder="irina.petrova" />
              <label className="label" htmlFor="r-email" style={{ marginTop: 12 }}>Почта <span className="muted small">(необязательно, для уведомлений и входа)</span></label>
              <input id="r-email" className="field" type="email" value={reg.email} onChange={(e) => setReg({ ...reg, email: e.target.value })} autoComplete="email" placeholder="you@example.ru" />
              <label className="label" htmlFor="r-pw" style={{ marginTop: 12 }}>Пароль <span className="muted small">(не меньше 8 символов, буква и цифра)</span></label>
              <div className="pw-wrap">
                <input id="r-pw" className="field" type={showPw ? 'text' : 'password'} value={reg.password} onChange={(e) => setReg({ ...reg, password: e.target.value })} autoComplete="new-password" />
                {pwToggle}
              </div>
              <label className="label" htmlFor="r-pw2" style={{ marginTop: 12 }}>Повторите пароль</label>
              <input id="r-pw2" className="field" type={showPw ? 'text' : 'password'} value={reg.confirm} onChange={(e) => setReg({ ...reg, confirm: e.target.value })} autoComplete="new-password" />
              <label className="row small" style={{ gap: 8, marginTop: 14, alignItems: 'flex-start' }}>
                <input type="checkbox" checked={reg.consent} onChange={(e) => setReg({ ...reg, consent: e.target.checked })} style={{ marginTop: 3 }} />
                <span>Согласен на обработку персональных данных (имя, логин, почта) для работы в МетодАгенте по 152-ФЗ</span>
              </label>
              <button className="btn btn-primary btn-lg" style={{ width: '100%', justifyContent: 'center', marginTop: 18 }} disabled={busy}>
                {busy ? <Spinner /> : <>Зарегистрироваться <ArrowRight size={18} /></>}
              </button>
            </form>
          )}

          <p className="small muted row" style={{ gap: 8, marginTop: 18 }}>
            <ShieldCheck size={16} /> Права проверяются на каждом действии: эксперт видит только свои модули.
          </p>
          <p className="small muted">Нужна помощь? Откройте <Link to="/help#access" style={{ color: 'var(--accent)', fontWeight: 700 }}>справку</Link>.</p>
        </div>
      </main>
    </div>
  )
}
