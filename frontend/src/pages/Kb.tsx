import { useEffect, useRef, useState } from 'react'
import { FileText, LibraryBig, Search, Trash2, Upload } from 'lucide-react'
import { api, getSession } from '../api'
import { Spinner, useToast } from '../components/ui'
import { FILE_ACCEPT, fileError } from '../validate'

const KINDS = [['template', 'Шаблон программы'], ['regulation', 'Положение'], ['other', 'Иной документ']]

/* База знаний организации (FR-09): администратор загружает документы, все ищут по ним */
export default function Kb() {
  const toast = useToast()
  const role = getSession()?.user.role
  const admin = role === 'admin'
  const [docs, setDocs] = useState<any[] | null>(null)
  const [kind, setKind] = useState('regulation')
  const [busy, setBusy] = useState(false)
  const [q, setQ] = useState('')
  const [hits, setHits] = useState<any[] | null>(null)
  const input = useRef<HTMLInputElement>(null)

  const load = () => api('/kb/documents').then(setDocs).catch((e) => { setDocs([]); toast(e.message, true) })
  useEffect(() => { load() }, []) // eslint-disable-line react-hooks/exhaustive-deps

  async function upload(f: File | undefined) {
    if (!f) return
    const err = fileError(f)
    if (err) { toast(err, true); return }
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', f)
      fd.append('kind', kind)
      const r = await api('/kb/documents', { method: 'POST', body: fd })
      toast(`«${r.name}» проиндексирован: ${r.chunks} фрагментов, ${r.indexed === 'embeddings' ? 'эмбеддинги Giga-Embeddings' : 'поиск по словам'}`)
      load()
    } catch (e: any) { toast(e.message, true) } finally { setBusy(false); if (input.current) input.current.value = '' }
  }
  async function remove(id: string) {
    if (!confirm('Удалить документ из базы знаний?')) return
    try { await api(`/kb/documents/${id}`, { method: 'DELETE' }); load() } catch (e: any) { toast(e.message, true) }
  }
  async function search() {
    if (q.trim().length < 2) return
    try { setHits(await api('/kb/search', { method: 'POST', json: { query: q, k: 6 } })) } catch (e: any) { toast(e.message, true) }
  }

  return (
    <div className="grid-main">
      <div className="col">
        <section className="card card-pad">
          <div className="row"><span className="avatar av-agent"><LibraryBig size={15} /></span><h1 className="h2" style={{ margin: 0 }}>База знаний организации</h1></div>
          <p className="muted">Шаблоны, положения и другие документы АЦР. В режиме «Документы организации» агент находит в них нужные фрагменты и ссылается на документ в нормативной базе программы.</p>
          {admin ? (
            <>
              <div className="seg" style={{ marginBottom: 10 }}>
                {KINDS.map(([k, l]) => <button key={k} className={`seg-btn ${kind === k ? 'active' : ''}`} onClick={() => setKind(k)}>{l}</button>)}
              </div>
              <div className="kb-drop" onClick={() => input.current?.click()}>{busy ? <><Spinner /> Индексирую…</> : <><Upload size={16} style={{ verticalAlign: -3 }} /> Загрузить .docx, .pdf или .txt до 20 МБ</>}</div>
              <input ref={input} type="file" hidden accept={FILE_ACCEPT} onChange={(e) => upload(e.target.files?.[0])} />
            </>
          ) : <div className="callout small">Загружает и удаляет документы администратор профиля. Искать по базе может любой сотрудник.</div>}
        </section>
        <NormBase />
        {admin && <OrgAdmin />}
        <section className="card card-pad">
          <h2 className="h2">Документы · {docs?.length ?? 0}</h2>
          {docs === null && <div className="skeleton" style={{ height: 90 }} />}
          {docs?.length === 0 && <p className="muted small">Пока пусто. {admin ? 'Загрузите первый документ выше.' : ''}</p>}
          <div style={{ display: 'grid', gap: 8 }}>
            {docs?.map((d) => (
              <div key={d.id} className="check-item">
                <FileText size={18} className="muted" />
                <div className="grow"><b>{d.name}</b><div className="tiny muted">{d.kind_label} · {d.chunks} фрагм. · {Math.round(d.chars / 1000)} тыс. знаков · {d.indexed === 'embeddings' ? 'эмбеддинги' : 'по словам'} · {(d.uploaded_at || '').slice(0, 10)}</div></div>
                {admin && <button className="btn btn-ghost btn-sm" onClick={() => remove(d.id)} aria-label="Удалить"><Trash2 size={14} /></button>}
              </div>
            ))}
          </div>
        </section>
      </div>
      <aside className="col col-16">
        <section className="card card-pad">
          <h3 className="h3">Поиск по базе</h3>
          <div className="row"><input className="field" placeholder="Например: итоговая аттестация" value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && search()} /><button className="btn btn-primary" onClick={search}><Search size={15} /></button></div>
          {hits && hits.length === 0 && <p className="small muted">Ничего не нашлось.</p>}
          <div style={{ display: 'grid', gap: 8, marginTop: 10 }}>
            {hits?.map((h, i) => (
              <div key={i} className="card" style={{ padding: 12 }}>
                <div className="tiny muted">{h.kind === 'norm' ? 'Нормативная база: ' : ''}{h.name} · фрагмент {h.chunk + 1} · сходство {h.score}</div>
                <div className="small" style={{ marginTop: 4 }}>{h.text}</div>
              </div>
            ))}
          </div>
        </section>
      </aside>
    </div>
  )
}

const REG_KINDS = [['ps', 'Профстандарты'], ['npa', 'НПА'], ['literature', 'Литература'], ['tools', 'Версии инструментов']]
const DEFAULT_FIELDS: [string, string][] = [['volume_h', 'Объём, ч'], ['audience', 'Аудитория'], ['form', 'Форма обучения'], ['final_assessment_form', 'Итоговая аттестация'], ['questions_per_test', 'Вопросов в тесте']]

/* Профиль организации и реестры (администратор, FR-08…FR-10, FR-13) */
function OrgAdmin() {
  const toast = useToast()
  const [prof, setProf] = useState<any>(null)
  const [kind, setKind] = useState('ps')
  const [reg, setReg] = useState('')
  const [busy, setBusy] = useState('')
  useEffect(() => { api('/org/profile').then(setProf).catch((e) => toast(e.message, true)) }, [toast])
  useEffect(() => { api(`/org/registry?kind=${kind}`).then((r) => setReg(JSON.stringify(r, null, 1))).catch((e) => toast(e.message, true)) }, [kind, toast])
  if (!prof) return <div className="skeleton" style={{ height: 120 }} />
  const d = prof.defaults || {}

  async function saveProfile() {
    setBusy('profile')
    try {
      const r = await api('/org/profile', { method: 'PUT', json: { defaults: prof.defaults, experts: prof.experts, notify_email: !!prof.notify_email, norm_mode: prof.norm_mode } })
      setProf(r); toast('Профиль сохранён: новые программы берут эти значения по умолчанию')
    } catch (e: any) { toast(e.message, true) } finally { setBusy('') }
  }
  async function saveRegistry() {
    setBusy('reg')
    try {
      const items = JSON.parse(reg)
      const r = await api('/org/registry', { method: 'PUT', json: { kind, items } })
      toast(`Реестр обновлён: ${r.items} записей, дата проверки — сегодня`)
      api(`/org/registry?kind=${kind}`).then((x) => setReg(JSON.stringify(x, null, 1)))
    } catch (e: any) { toast(e instanceof SyntaxError ? 'Реестр должен быть корректным JSON' : e.message, true) } finally { setBusy('') }
  }
  let count = 0, checked = ''
  try { const r = JSON.parse(reg); count = Array.isArray(r) ? r.length : Object.keys(r.current || {}).length; checked = Array.isArray(r) ? (r.map((x: any) => x.checked_at).filter(Boolean).sort()[0] || '') : r.checked_at || '' } catch { /* редактируется */ }

  return (
    <>
      <section className="card card-pad">
        <h2 className="h2">Профиль организации</h2>
        <p className="small muted">Значения по умолчанию подставляются, когда методист отвечает «На ваше усмотрение» или программа собирается в режиме auto; в каркасе и отчёте они помечены «принято агентом». Проверено: {prof.checked_at || '—'}.</p>
        <div className="grid-2">
          <label className="small">Тип программы
            <select className="field" value={d.program_type || 'dpp_pk'} onChange={(e) => setProf({ ...prof, defaults: { ...d, program_type: e.target.value } })}>
              <option value="dpp_pk">ДПП ПК</option><option value="dpp_pk_internship">ДПП ПК (стажировка)</option><option value="doop">ДООП</option>
            </select>
          </label>
          {DEFAULT_FIELDS.map(([k, l]) => (
            <label key={k} className="small">{l}
              <input className="field" value={d[k] ?? ''} type={['volume_h', 'questions_per_test'].includes(k) ? 'number' : 'text'}
                onChange={(e) => setProf({ ...prof, defaults: { ...d, [k]: ['volume_h', 'questions_per_test'].includes(k) ? Number(e.target.value) : e.target.value } })} />
            </label>
          ))}
          <label className="small">Нормативная база по умолчанию
            <select className="field" value={prof.norm_mode || 'gos'} onChange={(e) => setProf({ ...prof, norm_mode: e.target.value })}>
              <option value="gos">Госстандарты</option><option value="org">Документы организации</option>
            </select>
          </label>
        </div>
        <label className="row small" style={{ marginTop: 10, gap: 8 }}><input type="checkbox" checked={!!prof.notify_email} onChange={(e) => setProf({ ...prof, notify_email: e.target.checked })} /> Дублировать уведомления на почту (SMTP из профиля, пароль — в окружении сервера)</label>
        <h3 className="h3" style={{ marginTop: 14 }}>Эксперты и их компетенции</h3>
        <p className="tiny muted">По навыкам агент подсказывает методисту эксперта для модуля.</p>
        {(prof.experts || []).map((e: any, i: number) => (
          <div key={e.id} className="row" style={{ gap: 8, marginBottom: 6 }}>
            <b className="small" style={{ minWidth: 120 }}>{e.name}</b>
            <input className="field" value={(e.skills || []).join(', ')} placeholder="python, pandas, sql" onChange={(ev) => {
              const experts = [...prof.experts]; experts[i] = { ...e, skills: ev.target.value.split(',').map((x) => x.trim()).filter(Boolean) }; setProf({ ...prof, experts })
            }} />
          </div>
        ))}
        <button className="btn btn-primary" style={{ marginTop: 10 }} disabled={!!busy} onClick={saveProfile}>{busy === 'profile' ? <Spinner /> : 'Сохранить профиль'}</button>
      </section>
      <section className="card card-pad">
        <h2 className="h2">Реестры</h2>
        <div className="seg" style={{ marginBottom: 10 }}>
          {REG_KINDS.map(([k, l]) => <button key={k} className={`seg-btn ${kind === k ? 'active' : ''}`} onClick={() => setKind(k)}>{l}</button>)}
        </div>
        <p className="small muted">Записей: {count} · самая давняя проверка: {checked || '—'}. Агент ссылается только на коды и документы из реестра, остальное помечает «не подтверждено».</p>
        <textarea className="field" spellCheck={false} style={{ minHeight: 220, fontFamily: 'ui-monospace, monospace', fontSize: 12 }} value={reg} onChange={(e) => setReg(e.target.value)} aria-label="Реестр в JSON" />
        <button className="btn btn-primary" style={{ marginTop: 10 }} disabled={!!busy} onClick={saveRegistry}>{busy === 'reg' ? <Spinner /> : 'Сохранить реестр'}</button>
      </section>
    </>
  )
}

/* Нормативная база знаний: выжимки НПА, ФГОС и рекомендаций из официальных источников, на которые опирается агент */
function NormBase() {
  const [data, setData] = useState<{ documents: any[]; counts: Record<string, number> } | null>(null)
  const [open, setOpen] = useState(false)
  useEffect(() => { api('/kb/norms').then(setData).catch(() => setData({ documents: [], counts: {} })) }, [])
  if (!data) return null
  const c = data.counts
  return (
    <section className="card card-pad">
      <h2 className="h3" style={{ marginTop: 0 }}>Нормативная база агента</h2>
      <p className="small muted">Собрана из открытых правовых источников (КонсультантПлюс, ГАРАНТ, тексты профстандартов Минтруда, fgosvo.ru, fgos.ru) с датой проверки и ссылкой на каждый документ; утратившие силу акты (приказы № 499 и № 816, СП 2.4.3648-20) заменены действующими. Агент подбирает из неё акты и выдержки под запрос и передаёт их в генерацию каркаса и комплекта; в программу попадают только реквизиты из реестра.</p>
      <div className="row" style={{ gap: 8, flexWrap: 'wrap' }}>
        <span className="chip chip-blue">НПА: {c.npa ?? 0}</span>
        <span className="chip chip-blue">Профстандарты: {c.ps ?? 0}</span>
        <span className="chip chip-blue">ФГОС: {c.fgos ?? 0}</span>
        <span className="chip chip-blue">Источники литературы: {c.literature ?? 0}</span>
        <span className="chip chip-ok">Выжимки актов: {data.documents.length}</span>
      </div>
      {data.documents.length > 0 && <button className="btn btn-ghost btn-sm" style={{ marginTop: 10 }} onClick={() => setOpen((x) => !x)}>{open ? 'Скрыть выжимки' : 'Показать выжимки'}</button>}
      {open && data.documents.map((d) => (
        <div key={d.id} className="small" style={{ borderTop: '1px solid var(--line)', padding: '8px 0' }}>
          <b>{d.title}</b>
          <div className="tiny muted">{d.source}{d.url && <> · <a href={d.url} target="_blank" rel="noreferrer" style={{ color: 'var(--accent)' }}>источник</a></>}{d.checked_at && <> · проверено {d.checked_at}</>}</div>
        </div>
      ))}
    </section>
  )
}
