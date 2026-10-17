import { useEffect, useRef, useState } from 'react'
import { FileText, LibraryBig, Search, Trash2, Upload } from 'lucide-react'
import { api, getSession } from '../api'
import { Spinner, useToast } from '../components/ui'

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
              <input ref={input} type="file" hidden accept=".docx,.pdf,.txt" onChange={(e) => upload(e.target.files?.[0])} />
            </>
          ) : <div className="callout small">Загружает и удаляет документы администратор профиля. Искать по базе может любой сотрудник.</div>}
        </section>
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
                <div className="tiny muted">{h.name} · фрагмент {h.chunk + 1} · сходство {h.score}</div>
                <div className="small" style={{ marginTop: 4 }}>{h.text}</div>
              </div>
            ))}
          </div>
        </section>
      </aside>
    </div>
  )
}
