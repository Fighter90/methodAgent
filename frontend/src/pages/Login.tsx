import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowLeft, ArrowRight, Check, LockKeyhole, ShieldCheck, Sparkles } from 'lucide-react'
import { login } from '../api'
import { Logo, Spinner, useMouseParallax, useToast } from '../components/ui'

const USERS = [
  { id: 'u-madina', name: 'Мадина', role: 'methodist', title: 'Методист: собирает программу и утверждает каркас' },
  { id: 'u-timur', name: 'Тимур А.', role: 'expert', title: 'Эксперт: вычитывает свои модули' },
  { id: 'u-olga', name: 'Ольга К.', role: 'expert', title: 'Эксперт: вычитывает свои модули' },
  { id: 'u-ahmed', name: 'Ахмед', role: 'head', title: 'Руководитель: утверждает программу' },
]

export default function Login() {
  const [userId, setUserId] = useState('u-madina')
  const [password, setPassword] = useState('demo')
  const [busy, setBusy] = useState(false)
  const nav = useNavigate()
  const toast = useToast()
  const m = useMouseParallax(1)
  const L = (d: number) => ({ transform: `translate3d(${m.x * d}px, ${m.y * d}px, 0)` })

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    setBusy(true)
    try {
      const u = await login(userId, password)
      toast(`Здравствуйте, ${u.name}!`)
      nav(u.role === 'expert' ? '/app/reviews' : '/app')
    } catch (err: any) {
      toast(err.message || 'Не удалось войти', true)
    } finally {
      setBusy(false)
    }
  }

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
        <form className="auth-form" onSubmit={submit}>
          <div className="row" style={{ gap: 10, marginBottom: 6 }}>
            <span className="glass-icon" style={{ background: 'var(--accent-soft)', color: 'var(--accent)', borderColor: 'transparent' }}><LockKeyhole size={20} /></span>
          </div>
          <h2 className="h1" style={{ marginTop: 14 }}>Вход в МетодАгент</h2>
          <p className="muted" style={{ marginTop: 0 }}>Выберите демо-пользователя. Пароль у всех: <span className="kbd">demo</span></p>

          <div style={{ display: 'grid', gap: 8, margin: '20px 0' }} className="stagger">
            {USERS.map((u) => (
              <button type="button" key={u.id} className={`user-tile ${userId === u.id ? 'sel' : ''}`} onClick={() => setUserId(u.id)}>
                <span className={`avatar av-${u.role}`} style={{ width: 38, height: 38 }}>{u.name[0]}</span>
                <span className="grow">
                  <b style={{ display: 'block' }}>{u.name}</b>
                  <span className="small muted">{u.title}</span>
                </span>
                {userId === u.id && <Check size={18} color="var(--accent)" />}
              </button>
            ))}
          </div>

          <label className="label" htmlFor="pw">Пароль</label>
          <input id="pw" className="field" type="password" value={password} onChange={(e) => setPassword(e.target.value)} autoComplete="current-password" />

          <button className="btn btn-primary btn-lg" style={{ width: '100%', justifyContent: 'center', marginTop: 18 }} disabled={busy}>
            {busy ? <Spinner /> : <>Войти <ArrowRight size={18} /></>}
          </button>
          <p className="small muted row" style={{ gap: 8, marginTop: 18 }}>
            <ShieldCheck size={16} /> Права проверяются на каждом действии: эксперт видит только свои модули.
          </p>
          <p className="small muted">Нужна помощь? Откройте <Link to="/help" style={{ color: 'var(--accent)', fontWeight: 700 }}>справку</Link>.</p>
        </form>
      </main>
    </div>
  )
}
