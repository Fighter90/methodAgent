import { useEffect, useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { Bot, History, KeyRound, Plus, RotateCcw, Save, Settings2, Users } from 'lucide-react'
import { api, ROLE_LABEL } from '../api'
import { Spinner, useToast } from '../components/ui'

const ROLES = ['methodist', 'expert', 'head', 'admin'] as const
const SOURCE: Record<string, string> = { demo: 'демо', local: 'учётная запись', sso: 'SSO' }
type Tab = 'users' | 'settings' | 'skills' | 'journal'

/* Администрирование: пользователи и роли, ключи и настройки агента, навыки, журнал */
export default function Admin() {
  const [tab, setTab] = useState<Tab>('users')
  const tabs: [Tab, string, any][] = [['users', 'Пользователи', Users], ['settings', 'Настройки агента', KeyRound], ['skills', 'Навыки агента', Bot], ['journal', 'Журнал', History]]
  return (
    <div className="col" style={{ gap: 16 }}>
      <section className="card card-pad">
        <div className="row"><span className="avatar av-admin"><Settings2 size={15} /></span><h1 className="h2" style={{ margin: 0 }}>Администрирование</h1></div>
        <p className="muted">Пользователи и роли, ключи и модели, лимиты, вход и регистрация, SSO, параметры навыков. Профиль организации, шаблоны и реестры ПС, НПА и литературы — в разделе <Link to="/app/kb" style={{ color: 'var(--accent)', fontWeight: 700 }}>«База знаний»</Link>.</p>
        <div className="seg" role="tablist" style={{ gridTemplateColumns: `repeat(${tabs.length}, minmax(0, 1fr))` }}>
          {tabs.map(([k, l, I]) => <button key={k} role="tab" aria-selected={tab === k} className={`seg-btn ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}><I size={14} style={{ verticalAlign: -2 }} /> {l}</button>)}
        </div>
      </section>
      {tab === 'users' && <UsersTab />}
      {tab === 'settings' && <SettingsTab />}
      {tab === 'skills' && <SkillsTab />}
      {tab === 'journal' && <JournalTab />}
    </div>
  )
}

function UsersTab() {
  const toast = useToast()
  const [items, setItems] = useState<any[] | null>(null)
  const [draft, setDraft] = useState({ login: '', name: '', email: '', password: '', roles: ['expert'] as string[] })
  const load = () => api('/admin/users').then(setItems).catch((e) => toast(e.message, true))
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function patch(id: string, body: any, ok = 'Сохранено') {
    try { await api(`/admin/users/${id}`, { method: 'PATCH', json: body }); toast(ok); load() } catch (e: any) { toast(e.message, true) }
  }
  async function create(e: React.FormEvent) {
    e.preventDefault()
    try {
      await api('/admin/users', { method: 'POST', json: draft })
      toast(`Пользователь ${draft.login} создан`)
      setDraft({ login: '', name: '', email: '', password: '', roles: ['expert'] })
      load()
    } catch (err: any) { toast(err.message, true) }
  }
  const toggle = (list: string[], r: string) => (list.includes(r) ? list.filter((x) => x !== r) : [...list, r])

  if (!items) return <div className="card card-pad"><Spinner /></div>
  return (
    <>
      <section className="card card-pad" style={{ overflowX: 'auto' }}>
        <h2 className="h3">Пользователи и роли</h2>
        <table className="table admin-table">
          <thead><tr><th>Пользователь</th><th>Логин</th><th>Роли</th><th>Тип</th><th>Доступ</th><th></th></tr></thead>
          <tbody>
            {items.map((u) => (
              <tr key={u.id} style={{ opacity: u.active ? 1 : 0.55 }}>
                <td><b>{u.name}</b><div className="tiny muted">{u.email || u.title}</div></td>
                <td className="small">{u.login}</td>
                <td>
                  <div className="row-wrap" style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
                    {ROLES.map((r) => (
                      <label key={r} className={`chip ${u.roles.includes(r) ? 'chip-blue' : ''}`} style={{ cursor: u.id === 'u-api' ? 'default' : 'pointer' }}>
                        <input type="checkbox" hidden disabled={u.id === 'u-api'} checked={u.roles.includes(r)} onChange={() => {
                          const next = toggle(u.roles, r)
                          if (!next.length) return toast('Нужна хотя бы одна роль', true)
                          patch(u.id, { roles: next }, `Роли ${u.login}: ${next.map((x: string) => ROLE_LABEL[x]).join(', ')}`)
                        }} />{ROLE_LABEL[r]}
                      </label>
                    ))}
                  </div>
                </td>
                <td className="small">{SOURCE[u.source] || u.source}</td>
                <td>
                  <button className="btn btn-ghost btn-sm" disabled={u.id === 'u-api'} onClick={() => patch(u.id, { active: !u.active }, u.active ? `${u.login} отключён` : `${u.login} включён`)}>{u.active ? 'Отключить' : 'Включить'}</button>
                </td>
                <td>
                  <button className="btn btn-ghost btn-sm" title="Задать новый пароль" onClick={() => {
                    const pw = prompt(`Новый пароль для ${u.login} (не меньше 8 символов, буква и цифра)`)
                    if (pw) patch(u.id, { password: pw }, `Пароль ${u.login} изменён`)
                  }}><KeyRound size={13} /> Пароль</button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="tiny muted">Нельзя убрать последнего активного администратора. Пароль демо-учётки admin стоит сменить перед работой с реальными данными.</p>
      </section>
      <section className="card card-pad">
        <h2 className="h3"><Plus size={15} style={{ verticalAlign: -2 }} /> Новый пользователь</h2>
        <form onSubmit={create} className="grid-2" style={{ gap: 10 }}>
          <div><label className="label">Логин</label><input className="field" value={draft.login} onChange={(e) => setDraft({ ...draft, login: e.target.value.toLowerCase() })} placeholder="ivan.petrov" /></div>
          <div><label className="label">Имя и фамилия</label><input className="field" value={draft.name} onChange={(e) => setDraft({ ...draft, name: e.target.value })} /></div>
          <div><label className="label">Почта</label><input className="field" type="email" value={draft.email} onChange={(e) => setDraft({ ...draft, email: e.target.value })} /></div>
          <div><label className="label">Пароль</label><input className="field" type="password" autoComplete="new-password" value={draft.password} onChange={(e) => setDraft({ ...draft, password: e.target.value })} /></div>
          <div style={{ gridColumn: '1 / -1' }}>
            <label className="label">Роли</label>
            <div className="row" style={{ gap: 6, flexWrap: 'wrap' }}>
              {ROLES.map((r) => <button type="button" key={r} className={`chip ${draft.roles.includes(r) ? 'chip-blue' : ''}`} onClick={() => setDraft({ ...draft, roles: toggle(draft.roles, r) })}>{ROLE_LABEL[r]}</button>)}
            </div>
          </div>
          <div><button className="btn btn-primary"><Plus size={15} /> Создать</button></div>
        </form>
      </section>
    </>
  )
}

function SettingsTab() {
  const toast = useToast()
  const [data, setData] = useState<{ groups: Record<string, string>; fields: any[] } | null>(null)
  const [vals, setVals] = useState<Record<string, any>>({})
  const [busy, setBusy] = useState(false)
  const load = () => api('/admin/settings').then((d) => { setData(d); setVals({}) }).catch((e) => toast(e.message, true))
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  const groups = useMemo(() => {
    const out: Record<string, any[]> = {}
    for (const f of data?.fields || []) (out[f.group] ||= []).push(f)
    return out
  }, [data])

  async function save(clear: string[] = []) {
    setBusy(true)
    try {
      const r = await api('/admin/settings', { method: 'PUT', json: { values: vals, clear } })
      setData(r); setVals({})
      toast(r.changed.length ? `Сохранено: ${r.changed.length}` : 'Изменений нет')
    } catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }
  async function ping() {
    try {
      const s = await api('/llm/status')
      toast(s.ok ? `Шлюз отвечает: ${s.model || ''}` : s.enabled ? `Шлюз недоступен: ${s.error || 'ошибка'}` : 'Генерация через модель выключена (режим fixtures или нет ключа)', !s.ok)
    } catch (e: any) { toast(e.message, true) }
  }

  if (!data) return <div className="card card-pad"><Spinner /></div>
  const dirty = Object.keys(vals).length > 0
  return (
    <>
      {Object.entries(groups).map(([g, fields]) => (
        <section key={g} className="card card-pad">
          <div className="row"><h2 className="h3" style={{ margin: 0 }}>{data.groups[g]}</h2><div className="grow" />
            {g === 'llm' && <button className="btn btn-ghost btn-sm" onClick={ping}>Проверить подключение</button>}
          </div>
          {g === 'sso' && <div className="callout small" style={{ marginTop: 8 }}>Вход через SSO предусмотрен: параметры сохраняются, кнопка на форме входа помечена «скоро». Подключение протокола OIDC/SAML — следующий шаг.</div>}
          {fields.map((f) => {
            const v = f.key in vals ? vals[f.key] : f.value
            const set = (x: any) => setVals({ ...vals, [f.key]: x })
            return (
              <div key={f.key} className="set-row">
                <div>
                  <b className="small">{f.label}</b>
                  <div className="tiny muted">{f.source === 'admin' ? 'задано администратором' : f.source === 'env' ? 'из окружения' : 'не задано'}</div>
                </div>
                <div>
                  {f.type === 'bool' ? (
                    <label className="row small" style={{ gap: 8 }}><input type="checkbox" checked={!!v} onChange={(e) => set(e.target.checked)} /> {v ? 'включено' : 'выключено'}</label>
                  ) : f.type === 'choice' ? (
                    <select className="field" value={v} onChange={(e) => set(e.target.value)}>{f.options.map((o: string) => <option key={o} value={o}>{ROLE_LABEL[o] || o}</option>)}</select>
                  ) : f.type === 'secret' ? (
                    <input className="field" type="password" autoComplete="new-password" placeholder={f.set ? `${f.value} — введите новый, чтобы заменить` : 'не задан'} value={vals[f.key] || ''} onChange={(e) => set(e.target.value)} />
                  ) : (
                    <input className="field" type={f.type === 'str' ? 'text' : 'number'} step={f.type === 'float' ? '0.1' : '1'} min={f.min ?? undefined} max={f.max ?? undefined} value={v ?? ''} onChange={(e) => set(e.target.value)} />
                  )}
                  {f.hint && <div className="tiny muted" style={{ marginTop: 4 }}>{f.hint}</div>}
                  {f.source === 'admin' && <button className="btn btn-ghost btn-sm" style={{ marginTop: 4 }} onClick={() => save([f.key])}><RotateCcw size={12} /> Вернуть значение окружения</button>}
                </div>
              </div>
            )
          })}
        </section>
      ))}
      <div className="card card-pad row" style={{ position: 'sticky', bottom: 12 }}>
        <span className="small muted grow">Ключи хранятся зашифрованными и не показываются целиком. Изменения действуют сразу, без перезапуска.</span>
        <button className="btn btn-primary" disabled={!dirty || busy} onClick={() => save()}>{busy ? <Spinner /> : <><Save size={15} /> Сохранить</>}</button>
      </div>
    </>
  )
}

function SkillsTab() {
  const toast = useToast()
  const [items, setItems] = useState<any[] | null>(null)
  const [open, setOpen] = useState('')
  const [edit, setEdit] = useState<Record<string, any>>({})
  const load = () => api('/admin/skills').then(setItems).catch((e) => toast(e.message, true))
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function save(name: string, body: any) {
    try {
      await api(`/admin/skills/${name}`, { method: 'PUT', json: body })
      toast(body.reset ? `Навык ${name} сброшен к SKILL.md` : `Навык ${name} сохранён`)
      setEdit({}); load()
    } catch (e: any) { toast(e.message, true) }
  }

  if (!items) return <div className="card card-pad"><Spinner /></div>
  return (
    <section className="card card-pad">
      <h2 className="h3">Навыки агента</h2>
      <p className="small muted">Каждый навык — папка с SKILL.md, схемой и кодом. Здесь меняются температура, лимит токенов, таймаут, число повторов и инструкция модели; исходный SKILL.md не трогается и восстанавливается кнопкой «Сбросить».</p>
      {items.map((s) => (
        <div key={s.name} style={{ borderTop: '1px solid var(--line)', padding: '10px 0' }}>
          <div className="row" style={{ cursor: 'pointer' }} onClick={() => { setOpen(open === s.name ? '' : s.name); setEdit({}) }}>
            <b>{s.name}</b><span className="small muted grow">{s.description}</span>
            {s.overridden.length > 0 && <span className="chip chip-warn">изменён: {s.overridden.join(', ')}</span>}
            <span className="chip">{s.model_role}</span>
          </div>
          {open === s.name && (
            <div style={{ marginTop: 10 }}>
              <div className="grid-2" style={{ gap: 10 }}>
                {(['temperature', 'max_tokens', 'timeout_s', 'retries'] as const).map((f) => (
                  <div key={f}>
                    <label className="label">{{ temperature: 'Температура', max_tokens: 'Лимит токенов ответа', timeout_s: 'Таймаут, с', retries: 'Повторов' }[f]} <span className="tiny muted">(в SKILL.md: {s.defaults[f]})</span></label>
                    <input className="field" type="number" step={f === 'temperature' ? '0.05' : '1'} value={f in edit ? edit[f] : s[f]} onChange={(e) => setEdit({ ...edit, [f]: Number(e.target.value) })} />
                  </div>
                ))}
              </div>
              <label className="label" style={{ marginTop: 10 }}>Инструкция модели</label>
              <textarea className="field" rows={10} value={'instruction' in edit ? edit.instruction : s.instruction} onChange={(e) => setEdit({ ...edit, instruction: e.target.value })} style={{ fontFamily: 'var(--mono, monospace)', fontSize: 12 }} />
              <div className="row" style={{ marginTop: 10, gap: 8 }}>
                <button className="btn btn-primary btn-sm" disabled={!Object.keys(edit).length} onClick={() => save(s.name, edit)}><Save size={13} /> Сохранить</button>
                {s.overridden.length > 0 && <button className="btn btn-ghost btn-sm" onClick={() => save(s.name, { reset: true })}><RotateCcw size={13} /> Сбросить к SKILL.md</button>}
              </div>
            </div>
          )}
        </div>
      ))}
    </section>
  )
}

function JournalTab() {
  const toast = useToast()
  const [items, setItems] = useState<any[] | null>(null)
  useEffect(() => { api('/admin/journal').then(setItems).catch((e) => toast(e.message, true)) }, []) // eslint-disable-line react-hooks/exhaustive-deps
  if (!items) return <div className="card card-pad"><Spinner /></div>
  return (
    <section className="card card-pad">
      <h2 className="h3">Журнал администрирования</h2>
      <p className="small muted">Регистрации, изменения пользователей, настроек, навыков, профиля и реестров. Значения ключей в журнал не попадают.</p>
      {items.length === 0 && <div className="small muted">Записей пока нет.</div>}
      {items.map((e, i) => (
        <div key={i} className="small" style={{ borderTop: i ? '1px solid var(--line)' : 0, padding: '8px 0' }}>
          <span className="tiny muted">{(e.at || '').replace('T', ' ').slice(0, 16)}</span> · <b>{e.actor_name || e.actor}</b> · {e.text}
        </div>
      ))}
    </section>
  )
}
