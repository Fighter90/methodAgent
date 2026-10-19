import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ArrowRight, BookOpenText, CheckCircle2, Copy, FlaskConical, GitCompare, History, Pencil, RefreshCw, RotateCcw, Wand2 } from 'lucide-react'
import { api, getSession } from '../api'
import { Spinner, useToast } from '../components/ui'

type Doc = any

export const TEMPLATES = [
  { id: 'dpp_pk', label: 'ДПП ПК', hint: 'повышение квалификации' },
  { id: 'dpp_pk_internship', label: 'ДПП ПК · стажировка', hint: 'без аудиторных часов' },
  { id: 'doop', label: 'ДООП', hint: 'общеразвивающая' },
]

/* Текст, который меняется по щелчку: Enter или уход фокуса сохраняет, Esc отменяет (FR-17) */
export function EditableText({ value, onSave, disabled, multiline }: { value: string; onSave: (v: string) => Promise<void> | void; disabled?: boolean; multiline?: boolean }) {
  const [edit, setEdit] = useState(false)
  const [v, setV] = useState(value)
  const [busy, setBusy] = useState(false)
  useEffect(() => setV(value), [value])
  if (disabled) return <span>{value}</span>
  async function commit() {
    setEdit(false)
    const t = v.trim()
    if (!t || t === value) { setV(value); return }
    setBusy(true)
    try { await onSave(t) } finally { setBusy(false) }
  }
  if (!edit) {
    return (
      <span className="editable" role="button" tabIndex={0} title="Нажмите, чтобы изменить" onClick={(e) => { e.preventDefault(); e.stopPropagation(); setEdit(true) }}
        onKeyDown={(e) => { if (e.key === 'Enter') setEdit(true) }}>
        {value}{busy ? <Spinner /> : <Pencil size={12} className="editable-pen" />}
      </span>
    )
  }
  const props = {
    className: 'field field-inline', autoFocus: true, value: v,
    onChange: (e: any) => setV(e.target.value), onBlur: commit,
    onClick: (e: any) => e.stopPropagation(),
    onKeyDown: (e: any) => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); commit() } if (e.key === 'Escape') { setV(value); setEdit(false) } },
  }
  return multiline ? <textarea {...props} rows={2} /> : <input {...props} />
}

/* Смена шаблона до утверждения каркаса (FR-06) */
export function TemplateSwitch({ doc, setDoc }: { doc: Doc; setDoc: (d: Doc) => void }) {
  const toast = useToast()
  const [busy, setBusy] = useState('')
  async function choose(id: string) {
    if (id === doc.type) return
    setBusy(id)
    try {
      const r = await api(`/programs/${doc.id}/template`, { method: 'POST', json: { program_type: id } })
      const full = await api(`/programs/${doc.id}`)
      setDoc(full || r.program)
      toast('Шаблон сменён: часы, разделы и документ пересчитаны')
    } catch (e: any) { toast(e.message, true) } finally { setBusy('') }
  }
  return (
    <div>
      <div className="tiny muted" style={{ marginBottom: 6 }}>Шаблон АЦР · можно сменить до утверждения</div>
      <div className="seg">
        {TEMPLATES.map((t) => (
          <button key={t.id} className={`seg-btn ${doc.type === t.id ? 'active' : ''}`} disabled={!!busy} onClick={() => choose(t.id)} title={t.hint}>
            {busy === t.id ? <Spinner /> : t.label}
          </button>
        ))}
      </div>
    </div>
  )
}

const TOOL_TABS = [
  { id: 'text', label: 'Текст программы', icon: BookOpenText },
  { id: 'versions', label: 'Версии', icon: History },
  { id: 'actual', label: 'Актуализация', icon: RefreshCw },
  { id: 'sandbox', label: 'Песочница кода', icon: FlaskConical },
  { id: 'adapt', label: 'Адаптация', icon: Copy },
]

export function ToolsPanel({ doc, onEdit, only, title = 'Инструменты методиста' }: { doc: Doc; onEdit?: (target: string, instruction: string) => void; only?: string[]; title?: string }) {
  const tabs = TOOL_TABS.filter((t) => !only || only.includes(t.id))
  const [tab, setTab] = useState(tabs[0].id)
  return (
    <section className="card card-pad">
      <div className="row row-wrap" style={{ marginBottom: 6 }}>
        <h2 className="h2 grow" style={{ margin: 0 }}>{title}</h2>
      </div>
      <div className="tabs">
        {tabs.map((t) => <button key={t.id} className={`tab ${tab === t.id ? 'active' : ''}`} onClick={() => setTab(t.id)}><t.icon size={14} style={{ verticalAlign: -2 }} /> {t.label}</button>)}
      </div>
      <div key={tab} className="page-enter">
        {tab === 'text' && <SectionsView doc={doc} />}
        {tab === 'versions' && <VersionsView doc={doc} />}
        {tab === 'actual' && <ActualizeView doc={doc} onEdit={onEdit} />}
        {tab === 'sandbox' && <SandboxView doc={doc} />}
        {tab === 'adapt' && <AdaptView doc={doc} />}
      </div>
    </section>
  )
}

function SectionsView({ doc }: { doc: Doc }) {
  const [rows, setRows] = useState<any[] | null>(null)
  useEffect(() => { api(`/programs/${doc.id}/sections`).then(setRows).catch(() => setRows([])) }, [doc.id, doc.version])
  if (!rows) return <div className="skeleton" style={{ height: 200 }} />
  return (
    <div className="doc-preview">
      <p className="tiny muted" style={{ marginTop: 0 }}>Разделы в порядке выгрузки .docx по шаблону АЦР. Таблицы учебного плана, УТП и графика — в файле.</p>
      {rows.map((r) => (
        <div key={r.key} className={`doc-sec lvl-${r.level}`}>
          <div className="doc-h">{r.title}</div>
          {r.text && r.text.split('\n').map((line: string, i: number) => <p key={i} className={line.startsWith('— ') ? 'doc-li' : ''}>{line.replace(/^— /, '')}</p>)}
        </div>
      ))}
    </div>
  )
}

function VersionsView({ doc }: { doc: Doc }) {
  const toast = useToast()
  const [list, setList] = useState<any[] | null>(null)
  const [a, setA] = useState<number | null>(null)
  const [b, setB] = useState<number | null>(null)
  const [diff, setDiff] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    api(`/programs/${doc.id}/versions`).then((v) => { setList(v); if (v.length > 1) { setB(v[0].version); setA(v[1].version) } }).catch((e) => { setList([]); toast(e.message, true) })
  }, [doc.id, doc.version, toast])
  useEffect(() => {
    if (a == null || b == null || a === b) { setDiff(null); return }
    setBusy(true)
    api(`/programs/${doc.id}/versions/${a}/diff/${b}`).then(setDiff).catch((e) => toast(e.message, true)).finally(() => setBusy(false))
  }, [a, b, doc.id, toast])
  async function restore(v: number) {
    if (!confirm(`Откатить программу к версии ${v}? Текущая версия сохранится в истории.`)) return
    try { await api(`/programs/${doc.id}/versions/${v}/restore`, { method: 'POST' }); toast(`Откат к версии ${v} выполнен`); setTimeout(() => location.reload(), 600) } catch (e: any) { toast(e.message, true) }
  }
  if (!list) return <div className="skeleton" style={{ height: 160 }} />
  if (list.length < 2) return <p className="muted small">Пока одна версия. Каждая правка, утверждение и откат создают новую.</p>
  return (
    <div className="grid-main versions-grid">
      <div className="col" style={{ gap: 6 }}>
        {list.map((v) => (
          <div key={v.version} className={`ver-row ${v.version === a || v.version === b ? 'sel' : ''}`}>
            <div className="grow"><b>v{v.version}</b> <span className="small">{v.reason || 'сохранение'}</span><div className="tiny muted">{(v.at || '').slice(0, 16).replace('T', ' ')}</div></div>
            <button className="btn btn-ghost btn-sm" title="Сравнить как «было»" onClick={() => setA(v.version)}>A</button>
            <button className="btn btn-ghost btn-sm" title="Сравнить как «стало»" onClick={() => setB(v.version)}>B</button>
            {v.version !== doc.version && getSession()?.user.role === 'methodist' && <button className="btn btn-ghost btn-sm" title="Откатить" onClick={() => restore(v.version)}><RotateCcw size={13} /></button>}
          </div>
        ))}
      </div>
      <div>
        <div className="row" style={{ marginBottom: 8 }}><GitCompare size={16} /><b>v{a} → v{b}</b>{busy && <Spinner />}</div>
        {diff && (
          <>
            <div className="row row-wrap" style={{ gap: 6, marginBottom: 10 }}>
              <span className="chip">{diff.changes.length} изменений в программе</span>
              <span className="chip chip-blue">комплект: изменено {diff.summary.kit_changed}, добавлено {diff.summary.kit_added}, удалено {diff.summary.kit_removed}</span>
              <span className="chip">блокирующие {diff.summary.blocking_a} → {diff.summary.blocking_b}</span>
            </div>
            {diff.changes.length === 0 && <p className="small muted">Поля программы не менялись.</p>}
            <table className="table small">
              <thead><tr><th>Что</th><th>Было</th><th>Стало</th></tr></thead>
              <tbody>{diff.changes.slice(0, 80).map((c: any, i: number) => (
                <tr key={i}><td><b>{c.label}</b></td><td className="diff-del">{c.before}</td><td className="diff-add">{c.after}</td></tr>
              ))}</tbody>
            </table>
          </>
        )}
      </div>
    </div>
  )
}

const KIND_LABEL: Record<string, [string, string]> = {
  construct: ['Устаревшая конструкция', 'chip-err'], version: ['Снято с поддержки', 'chip-err'], update: ['Есть новая версия', 'chip-blue'],
  service: ['Недоступно в России', 'chip-warn'], source: ['Старый источник', 'chip-warn'],
}

export function FindingsList({ items, onEdit }: { items: any[]; onEdit?: (target: string, instruction: string) => void }) {
  if (!items.length) return <div className="callout small"><CheckCircle2 size={15} style={{ verticalAlign: -3 }} /> Устаревших тем, инструментов и версий по реестру не найдено.</div>
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {items.map((f, i) => (
        <div key={i} className="check-item">
          <span className={`chip ${KIND_LABEL[f.kind]?.[1] || ''}`}>{KIND_LABEL[f.kind]?.[0] || f.kind}</span>
          <div className="grow">
            <b>{f.found}</b>{f.where && <span className="tiny muted"> · {f.where}</span>}
            <div className="small">{f.message}{f.replacement && <> → <b style={{ color: 'var(--accent-deep)' }}>{f.replacement}</b></>}</div>
          </div>
          {onEdit && f.node_id && <button className="btn btn-ghost btn-sm" onClick={() => onEdit(f.node_id, `Актуализировать: ${f.message}${f.replacement ? `; заменить на ${f.replacement}` : ''}`)}><Wand2 size={13} /> Поправить</button>}
        </div>
      ))}
    </div>
  )
}

function ActualizeView({ doc, onEdit }: { doc: Doc; onEdit?: (target: string, instruction: string) => void }) {
  const [r, setR] = useState<any>(null)
  useEffect(() => { api(`/programs/${doc.id}/actualize`).then(setR).catch(() => setR({ findings: [] })) }, [doc.id, doc.version])
  if (!r) return <div className="skeleton" style={{ height: 120 }} />
  return (
    <div>
      <p className="small muted" style={{ marginTop: 0 }}>Темы, лекции, задания, вопросы и источники сверены с реестром версий{r.registry_checked_at ? ` от ${r.registry_checked_at}` : ''}: устаревшие конструкции, версии ниже поддерживаемых, сервисы, недоступные в России, источники старше 10 лет.</p>
      <FindingsList items={r.findings} onEdit={onEdit} />
    </div>
  )
}

function SandboxView({ doc }: { doc: Doc }) {
  const [r, setR] = useState<any>(null)
  const [busy, setBusy] = useState(false)
  const run = () => { setBusy(true); api(`/programs/${doc.id}/sandbox`).then(setR).catch(() => setR({ items: [] })).finally(() => setBusy(false)) }
  useEffect(run, [doc.id, doc.version])
  if (!r) return <div className="row small muted"><Spinner /> Запускаю примеры кода в песочнице без сети…</div>
  if (!r.items.length) return <p className="small muted">В лекциях нет примеров кода.</p>
  return (
    <div>
      <div className="row row-wrap" style={{ gap: 6, marginBottom: 10 }}>
        <span className="chip">Python {r.python}</span>
        <span className={`chip ${r.failed ? 'chip-err' : 'chip-ok'}`}>{r.checked - r.failed} из {r.checked} примеров без ошибок</span>
        {r.outdated > 0 && <span className="chip chip-warn">{r.outdated} устаревших конструкций</span>}
        <span className="grow" />
        <button className="btn btn-ghost btn-sm" disabled={busy} onClick={run}>{busy ? <Spinner /> : <RefreshCw size={13} />} Запустить снова</button>
      </div>
      <div style={{ display: 'grid', gap: 10 }}>
        {r.items.map((x: any, i: number) => (
          <details key={i} className="sandbox-item" open={!x.ok || x.outdated.length > 0}>
            <summary>
              <span className={`check-icon ${x.ok ? 'ci-pass' : 'ci-fail'}`}>{x.ok ? '✓' : '!'}</span>
              <b>{x.lecture}</b> <span className="tiny muted">пример {x.n} · {x.mode === 'run' ? 'выполнен' : x.mode === 'syntax' ? 'проверен синтаксис' : 'не запускался'} · {x.seconds} с</span>
              {x.libs.map((l: any) => <span key={l.name} className="chip" style={{ marginLeft: 6 }}>{l.name}{l.version ? ` ${l.version}` : ''}</span>)}
            </summary>
            <pre className="code">{x.code}</pre>
            {x.stdout && <pre className="code code-out">{x.stdout}</pre>}
            {x.error && <div className="callout warn small">{x.error}</div>}
            {x.outdated.map((f: any, j: number) => <div key={j} className="callout warn small">{f.message}{f.replacement && <> → <b>{f.replacement}</b></>}</div>)}
          </details>
        ))}
      </div>
    </div>
  )
}

function AdaptView({ doc }: { doc: Doc }) {
  const toast = useToast()
  const nav = useNavigate()
  const [volume, setVolume] = useState<number | ''>('')
  const [audience, setAudience] = useState('')
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  async function go() {
    setBusy(true)
    try {
      const r = await api(`/programs/${doc.id}/adapt`, { method: 'POST', json: { volume_h: volume || null, audience, title } })
      toast('Новая программа создана: проверьте каркас')
      nav(`/app/p/${r.program_id}`)
    } catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }
  return (
    <div className="grid-2">
      <div>
        <p className="small muted" style={{ marginTop: 0 }}>Новая программа на основе этой: компетенции, индикаторы и РО сохраняются, часы модулей и тем пересчитывает солвер, комплект собирается заново после утверждения каркаса.</p>
        <label className="label">Новый объём, ч</label>
        <input className="field" type="number" min={8} max={2000} placeholder={`сейчас ${doc.volume_h}`} value={volume} onChange={(e) => setVolume(e.target.value ? Number(e.target.value) : '')} />
        <label className="label" style={{ marginTop: 10 }}>Новая аудитория</label>
        <input className="field" placeholder={doc.params?.audience || 'например, руководители отделов'} value={audience} onChange={(e) => setAudience(e.target.value)} />
        <label className="label" style={{ marginTop: 10 }}>Название (необязательно)</label>
        <input className="field" placeholder={doc.title} value={title} onChange={(e) => setTitle(e.target.value)} />
        <button className="btn btn-primary" style={{ marginTop: 14 }} disabled={busy || (!volume && !audience.trim())} onClick={go}>{busy ? <Spinner /> : <>Адаптировать <ArrowRight size={16} /></>}</button>
      </div>
      <div className="card" style={{ padding: 14, background: 'var(--bg-2)' }}>
        <div className="tiny muted">Сохранится</div>
        <ul className="small" style={{ paddingLeft: 18 }}>
          <li>{doc.competencies?.length || 0} компетенций и их РО</li>
          <li>{doc.modules?.length || 0} модулей и темы с весами</li>
          <li>Шаблон «{doc.template}» и нормативная база</li>
        </ul>
        <div className="tiny muted">Пересчитается</div>
        <ul className="small" style={{ paddingLeft: 18 }}>
          <li>Часы по видам работы и итоговая аттестация</li>
          <li>Календарный график</li>
          <li>Комплект: тесты, задания, лекции</li>
        </ul>
      </div>
    </div>
  )
}
