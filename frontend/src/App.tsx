import { useEffect, useState, type ReactNode } from 'react'
import { Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import { Bell, CircleHelp, FolderKanban, LibraryBig, LogOut, Moon, Settings2, Sun, ClipboardCheck, UserRound } from 'lucide-react'
import { api, getSession, setSession, switchRole, ROLE_LABEL, NETWORK_MSG, type User } from './api'
import { Logo, useTheme, useToast } from './components/ui'
import Landing from './pages/Landing'
import Login from './pages/Login'
import Help from './pages/Help'
import Programs from './pages/Programs'
import Program from './pages/Program'
import Reviews from './pages/Reviews'
import Kb from './pages/Kb'
import Admin from './pages/Admin'
import Me from './pages/Me'


function Shell({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(getSession()?.user || null)
  const [notes, setNotes] = useState<any[]>([])
  const [open, setOpen] = useState(false)
  const [tasks, setTasks] = useState<Record<string, number>>({})
  const [theme, toggle] = useTheme()
  const nav = useNavigate()
  const toast = useToast()
  const loc = useLocation()

  useEffect(() => {
    const onUser = () => setUser(getSession()?.user || null)
    let shown = 0
    const onOffline = () => { if (Date.now() - shown > 20000) { shown = Date.now(); toast(NETWORK_MSG, true) } }
    const onOnline = () => { if (shown) { shown = 0; toast('Связь с сервером восстановлена') } }
    window.addEventListener('ma:user', onUser)
    window.addEventListener('ma:offline', onOffline)
    window.addEventListener('ma:online', onOnline)
    return () => { window.removeEventListener('ma:user', onUser); window.removeEventListener('ma:offline', onOffline); window.removeEventListener('ma:online', onOnline) }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!user) return
    let alive = true
    const load = () => {
      api('/notifications').then((n) => alive && setNotes(n)).catch(() => {})
      api('/me/tasks').then((t) => alive && setTasks(t.tasks || {})).catch(() => {})
    }
    load()
    const t = setInterval(load, 15000)
    return () => { alive = false; clearInterval(t) }
  }, [user, loc.pathname])

  if (!user) return <Navigate to="/auth" replace />
  // у каждой роли свои экраны: администратор не работает с программами, остальные не видят администрирование
  const path = loc.pathname
  if (user.role === 'admin' && (path === '/app' || path.startsWith('/app/p/') || path === '/app/reviews')) return <Navigate to="/app/admin" replace />
  if (user.role !== 'admin' && path === '/app/admin') return <Navigate to="/app" replace />

  function logout() {
    setSession(null)
    window.dispatchEvent(new Event('ma:user'))
    nav('/auth')
  }

  const own = (user.roles || [user.role]).filter((r) => r !== 'api')

  async function switchTo(role: string) {
    try {
      const u = await switchRole(role)
      setUser(u)
      toast(`Вы вошли как ${u.name} · ${ROLE_LABEL[u.role]}`)
      if (u.role === 'expert' && !loc.pathname.includes('/p/')) nav('/app/reviews')
      else if (u.role === 'admin') nav('/app/admin')
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
          {user.role !== 'admin' && <NavLink to="/app" end className="nav-link" title="Программы"><FolderKanban size={16} /> <span className="nav-label">Программы</span></NavLink>}
          {user.role === 'expert' && <NavLink to="/app/reviews" className="nav-link" title="Вычитка"><ClipboardCheck size={16} /> <span className="nav-label">Вычитка</span></NavLink>}
          {['admin', 'methodist', 'head'].includes(user.role) && <NavLink to="/app/kb" className="nav-link" title="База знаний"><LibraryBig size={16} /> <span className="nav-label">База знаний</span></NavLink>}
          {user.role === 'admin' && <NavLink to="/app/admin" className="nav-link" title="Администрирование"><Settings2 size={16} /> <span className="nav-label">Администрирование</span></NavLink>}
          <NavLink to="/help" className="nav-link" title="Справка"><CircleHelp size={16} /> <span className="nav-label">Справка</span></NavLink>
        </nav>
        <div className="grow" />
        {own.length > 1 && (
          <div className="roles" role="tablist" aria-label="Роль">
            {own.map((r) => (
              <button key={r} className={`role-pill ${user.role === r ? 'active' : ''}`} onClick={() => user.role !== r && switchTo(r)} title={`Работать как ${ROLE_LABEL[r]}`}>
                <span className={`avatar av-${r}`}>{user.name[0]}</span><span className="role-name">{ROLE_LABEL[r]}</span>
                {tasks[r] > 0 && <span className="role-count">{tasks[r]}</span>}
              </button>
            ))}
          </div>
        )}
        <div style={{ position: 'relative' }}>
          <button className="icon-btn" aria-label="Уведомления" onClick={() => {
            setOpen((x) => !x)
            if (!open && notes.some((n) => !n.read)) {
              api('/notifications/read', { method: 'POST', json: { ids: [] } }).then(() => setNotes(notes.map((n) => ({ ...n, read: true })))).catch(() => {})
            }
          }}>
            <Bell size={17} />{notes.some((n) => !n.read) && <span className="badge-dot" />}
          </button>
          {open && (
            <div className="card" style={{ position: 'absolute', right: 0, top: 44, width: 340, padding: 10, boxShadow: 'var(--shadow-lg)', animation: 'scaleIn .2s var(--ease)', zIndex: 40 }}>
              <div className="h3" style={{ padding: '4px 6px' }}>Уведомления</div>
              {notes.length === 0 && <div className="small muted" style={{ padding: 6 }}>Пока ничего нового.</div>}
              {notes.slice(0, 8).map((n, i) => (
                <Link key={i} to={`/app/p/${n.program_id}`} onClick={() => setOpen(false)} className="small" style={{ display: 'block', padding: '8px 6px', borderTop: i ? '1px solid var(--line)' : 0, fontWeight: n.read ? 400 : 700 }}>
                  {n.text}<div className="tiny muted">{(n.at || '').slice(11, 16)}</div>
                </Link>
              ))}
            </div>
          )}
        </div>
        <button className="icon-btn" onClick={toggle} aria-label="Тема">{theme === 'dark' ? <Sun size={17} /> : <Moon size={17} />}</button>
        <Link to="/app/me" className="user-chip" title="Личный кабинет">
          <span className={`avatar av-${user.role}`}><UserRound size={14} /></span>
          <span className="user-chip-text"><b>{user.name}</b><span className="tiny muted">{ROLE_LABEL[user.role]}</span></span>
        </Link>
        <button className="btn btn-ghost btn-sm" onClick={logout} title="Выйти из учётной записи"><LogOut size={15} /> <span className="nav-label">Выйти</span></button>
      </header>
      <main key={user.id} className="container page-enter">{children}</main>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/" element={<Landing />} />
      <Route path="/auth" element={<Login />} />
      <Route path="/login" element={<Navigate to="/auth" replace />} />
      <Route path="/signin" element={<Navigate to="/auth" replace />} />
      <Route path="/register" element={<Navigate to="/auth?mode=register" replace />} />
      <Route path="/help" element={<Help />} />
      <Route path="/app" element={<Shell><Programs /></Shell>} />
      <Route path="/app/reviews" element={<Shell><Reviews /></Shell>} />
      <Route path="/app/kb" element={<Shell><Kb /></Shell>} />
      <Route path="/app/admin" element={<Shell><Admin /></Shell>} />
      <Route path="/app/me" element={<Shell><Me /></Shell>} />
      <Route path="/app/p/:id" element={<Shell><Program /></Shell>} />
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
