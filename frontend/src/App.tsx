import { useEffect, useState, type ReactNode } from 'react'
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Bell, CircleHelp, FolderKanban, LogOut, Moon, Sun, ClipboardCheck } from 'lucide-react'
import { api, getSession, login, setSession, ROLE_LABEL, type User } from './api'
import { Logo, useTheme, useToast } from './components/ui'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Help from './pages/Help'
import Programs from './pages/Programs'
import Program from './pages/Program'
import Reviews from './pages/Reviews'

const SWITCH = [
  { id: 'u-madina', name: 'Мадина', role: 'methodist' },
  { id: 'u-timur', name: 'Тимур', role: 'expert' },
  { id: 'u-ahmed', name: 'Ахмед', role: 'head' },
]

function Shell({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(getSession()?.user || null)
  const [notes, setNotes] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [theme, toggle] = useTheme()
  const nav = useNavigate()
  const toast = useToast()
  const loc = useLocation()

  useEffect(() => {
    if (!user) return
    let alive = true
    const load = () => api('/notifications').then((n) => alive && setNotes(n)).catch(() => {})
    load()
    const t = setInterval(load, 15000)
    return () => { alive = false; clearInterval(t) }
  }, [user, loc.pathname])

  if (!user) return <Navigate to="/login" replace />

  async function switchTo(id: string) {
    try {
      const u = await login(id, 'demo')
      setUser(u)
      toast(`Вы вошли как ${u.name} · ${ROLE_LABEL[u.role]}`)
      if (u.role === 'expert' && !loc.pathname.includes('/p/')) nav('/app/reviews')
      else nav(loc.pathname, { replace: true })
      window.dispatchEvent(new Event('ma:user'))
    } catch (e: any) {
      toast(e.message, true)
    }
  }

  return (
    <div style={{ minHeight: '100vh' }}>
      <header className="topbar">
        <Link to="/app"><Logo /></Link>
        <nav className="row" style={{ gap: 4 }}>
          <NavLink to="/app" end className="nav-link"><FolderKanban size={16} /> Программы</NavLink>
          {user.role === 'expert' && <NavLink to="/app/reviews" className="nav-link"><ClipboardCheck size={16} /> Вычитка</NavLink>}
          <NavLink to="/help" className="nav-link"><CircleHelp size={16} /> Справка</NavLink>
        </nav>
        <div className="grow" />
        <div className="roles" role="tablist" aria-label="Роль">
          {SWITCH.map((u) => (
            <button key={u.id} className={`role-pill ${user.id === u.id || (u.role === user.role && u.role === 'expert') ? 'active' : ''}`} onClick={() => switchTo(u.id)} title={`Войти как ${u.name}`}>
              <span className={`avatar av-${u.role}`}>{u.name[0]}</span>{u.name} · {ROLE_LABEL[u.role]}
            </button>
          ))}
        </div>
        <div style={{ position: 'relative' }}>
          <button className="icon-btn" onClick={() => setOpen((x) => !x)} aria-label="Уведомления">
            <Bell size={17} />{notes.length > 0 && <span className="badge-dot" />}
          </button>
          {open && (
            <div className="card" style={{ position: 'absolute', right: 0, top: 44, width: 340, padding: 10, boxShadow: 'var(--shadow-lg)', animation: 'scaleIn .2s var(--ease)', zIndex: 40 }}>
              <div className="h3" style={{ padding: '4px 6px' }}>Уведомления</div>
              {notes.length === 0 && <div className="small muted" style={{ padding: 6 }}>Пока ничего нового.</div>}
              {notes.slice(0, 8).map((n, i) => (
                <Link key={i} to={`/app/p/${n.program_id}`} onClick={() => setOpen(false)} className="small" style={{ display: 'block', padding: '8px 6px', borderTop: i ? '1px solid var(--line)' : 0 }}>
                  {n.text}<div className="tiny muted">{(n.at || '').slice(11, 16)}</div>
                </Link>
              ))}
            </div>
          )}
        </div>
        <button className="icon-btn" onClick={toggle} aria-label="Тема">{theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button>
        <button className="icon-btn" onClick={() => { setSession(null); nav('/login') }} aria-label="Выйти"><LogOut size={17} /></button>
      </header>
      <main key={user.id} className="container page-enter">{children}</main>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/login" element={<Login />} />
      <Route path="/help" element={<Help />} />
      <Route path="/app" element={<Shell><Programs /></Shell>} />
      <Route path="/app/reviews" element={<Shell><Reviews /></Shell>} />
      <Route path="/app/p/:id" element={<Shell><Program /></Shell>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
