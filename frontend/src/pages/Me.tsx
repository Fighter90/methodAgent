import { useEffect, useState } from 'react'
import { KeyRound, Save, UserRound } from 'lucide-react'
import { api, getSession, setSession, ROLE_LABEL, type User } from '../api'
import { Spinner, useToast } from '../components/ui'

/* Личный кабинет: данные пользователя, роли и смена пароля */
export default function Me() {
  const toast = useToast()
  const [me, setMe] = useState<(User & { roles: string[] }) | null>(null)
  const [form, setForm] = useState({ name: '', email: '', title: '' })
  const [pw, setPw] = useState({ current: '', next: '', confirm: '' })
  const [busy, setBusy] = useState('')

  useEffect(() => {
    api('/auth/me').then((u) => { setMe(u); setForm({ name: u.name, email: u.email || '', title: u.title || '' }) }).catch((e) => toast(e.message, true))
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  if (!me) return <div className="card card-pad"><Spinner /></div>
  const demo = me.source === 'demo'

  async function save(e: React.FormEvent) {
    e.preventDefault()
    setBusy('profile')
    try {
      const u = await api('/auth/me', { method: 'PUT', json: form })
      setMe(u)
      const s = getSession()
      if (s) setSession({ ...s, user: { ...s.user, name: u.name, title: u.title, email: u.email } })
      window.dispatchEvent(new Event('ma:user'))
      toast('Данные сохранены')
    } catch (err: any) { toast(err.message, true) } finally { setBusy('') }
  }

  async function changePw(e: React.FormEvent) {
    e.preventDefault()
    if (pw.next.length < 8 || !/\d/.test(pw.next) || !/\p{L}/u.test(pw.next)) return toast('Новый пароль: не меньше 8 символов, буква и цифра', true)
    if (pw.next !== pw.confirm) return toast('Пароли не совпадают', true)
    setBusy('pw')
    try {
      await api('/auth/me/password', { method: 'PUT', json: { current: pw.current, new: pw.next } })
      setPw({ current: '', next: '', confirm: '' })
      toast('Пароль изменён')
    } catch (err: any) { toast(err.message, true) } finally { setBusy('') }
  }

  return (
    <div className="grid-2">
      <section className="card card-pad">
        <div className="row"><span className={`avatar av-${me.role}`}><UserRound size={15} /></span><h1 className="h2" style={{ margin: 0 }}>Личный кабинет</h1></div>
        <p className="muted small">Логин <b>{me.login}</b> · текущая роль <b>{ROLE_LABEL[me.role]}</b> · все роли: {me.roles.map((r) => ROLE_LABEL[r]).join(', ')}</p>
        {demo && <div className="callout small">Это демо-учётка: имя и пароль меняет администратор в разделе «Администрирование».</div>}
        <form onSubmit={save}>
          <label className="label" htmlFor="me-name">Имя и фамилия</label>
          <input id="me-name" className="field" value={form.name} disabled={demo} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          <label className="label" htmlFor="me-email" style={{ marginTop: 12 }}>Почта</label>
          <input id="me-email" className="field" type="email" value={form.email} disabled={demo} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          <label className="label" htmlFor="me-title" style={{ marginTop: 12 }}>Должность</label>
          <input id="me-title" className="field" value={form.title} disabled={demo} onChange={(e) => setForm({ ...form, title: e.target.value })} />
          <button className="btn btn-primary" style={{ marginTop: 16 }} disabled={demo || busy === 'profile'}>{busy === 'profile' ? <Spinner /> : <><Save size={15} /> Сохранить</>}</button>
        </form>
        <p className="small muted" style={{ marginTop: 16 }}>Роли назначает администратор. Новый пользователь получает минимальные права, пока администратор их не расширит.</p>
      </section>
      <section className="card card-pad">
        <div className="row"><span className="avatar av-agent"><KeyRound size={15} /></span><h2 className="h2" style={{ margin: 0 }}>Безопасность</h2></div>
        <form onSubmit={changePw} style={{ marginTop: 12 }}>
          <label className="label" htmlFor="pw-cur">Текущий пароль</label>
          <input id="pw-cur" className="field" type="password" autoComplete="current-password" disabled={demo} value={pw.current} onChange={(e) => setPw({ ...pw, current: e.target.value })} />
          <label className="label" htmlFor="pw-new" style={{ marginTop: 12 }}>Новый пароль</label>
          <input id="pw-new" className="field" type="password" autoComplete="new-password" disabled={demo} value={pw.next} onChange={(e) => setPw({ ...pw, next: e.target.value })} />
          <label className="label" htmlFor="pw-rep" style={{ marginTop: 12 }}>Повторите пароль</label>
          <input id="pw-rep" className="field" type="password" autoComplete="new-password" disabled={demo} value={pw.confirm} onChange={(e) => setPw({ ...pw, confirm: e.target.value })} />
          <button className="btn btn-soft" style={{ marginTop: 16 }} disabled={demo || busy === 'pw'}>{busy === 'pw' ? <Spinner /> : 'Сменить пароль'}</button>
        </form>
        <p className="small muted" style={{ marginTop: 16 }}>Пароль хранится только в виде хеша bcrypt. Вход через SSO организации появится, когда администратор его подключит.</p>
      </section>
    </div>
  )
}
