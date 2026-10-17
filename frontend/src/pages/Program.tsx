import { useCallback, useEffect, useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  AlertTriangle, ArrowLeft, ArrowRight, Check, CheckCircle2, ChevronRight, Clock, Coins, Download, FileSpreadsheet, FileText,
  GitBranch, History, MessageSquare, Presentation, RotateCcw, Send, Sparkles, Undo2, Users, X,
} from 'lucide-react'
import { api, download, getSession, STATUS_LABEL, waitJob } from '../api'
import { Avatar, Spinner, useToast } from '../components/ui'
import { REVIEW_LABEL } from './Reviews'
import { EditableText, TemplateSwitch, ToolsPanel } from './ProgramTools'

type Doc = any
const STEPS = ['Запрос', 'Вопросы', 'Каркас', 'Проверка', 'Комплект', 'Согласование']
const KINDS = ['lk', 'pr', 'lb', 'srs'] as const
const EXPERTS = [{ id: 'u-timur', name: 'Тимур А.' }, { id: 'u-olga', name: 'Ольга К.' }]
const TYPE_LABEL: Record<string, string> = { dpp_pk: 'ДПП повышения квалификации', dpp_pk_internship: 'ДПП ПК в форме стажировки', doop: 'Дополнительная общеразвивающая' }

function maxStep(s: string) {
  if (['draft', 'questions'].includes(s)) return 2
  if (['skeleton', 'returned'].includes(s)) return 4
  if (['skeleton_approved', 'generating', 'kit_ready'].includes(s)) return 5
  return 6
}
function defaultStep(s: string) {
  if (['draft', 'questions'].includes(s)) return 2
  if (['skeleton', 'returned'].includes(s)) return 3
  if (['skeleton_approved', 'generating', 'kit_ready'].includes(s)) return 5
  return 6
}

export default function Program() {
  const { id } = useParams()
  const [doc, setDoc] = useState<Doc | null>(null)
  const [step, setStep] = useState(0)
  const [sub, setSub] = useState<'report' | 'edit'>('report')
  const [editInit, setEditInit] = useState<{ target?: string; instruction?: string }>({})
  const [job, setJob] = useState<any>(null)
  const [user, setUser] = useState(getSession()?.user)
  const toast = useToast()

  const load = useCallback(async () => {
    try {
      const d = await api(`/programs/${id}`)
      setDoc(d)
      return d
    } catch (e: any) {
      toast(e.message, true)
    }
  }, [id, toast])

  useEffect(() => {
    const on = () => { setUser(getSession()?.user); load() }
    window.addEventListener('ma:user', on)
    return () => window.removeEventListener('ma:user', on)
  }, [load])

  useEffect(() => {
    load().then((d) => {
      if (!d) return
      setStep(defaultStep(d.status))
      const j = sessionStorage.getItem(`ma.job.${id}`)
      if (j) track(j)
    })
  }, [id]) // eslint-disable-line react-hooks/exhaustive-deps

  async function track(jobId: string) {
    sessionStorage.setItem(`ma.job.${id}`, jobId)
    setJob({ status: 'running', progress: {} })
    try {
      await waitJob(jobId, (p) => setJob({ status: 'running', progress: p || {} }))
      const d = await load()
      if (d) setStep(defaultStep(d.status))
    } catch (e: any) {
      toast(e.message, true)
    } finally {
      sessionStorage.removeItem(`ma.job.${id}`)
      setJob(null)
    }
  }

  if (!doc) return <div style={{ display: 'grid', gap: 12 }}><div className="skeleton" style={{ height: 60 }} /><div className="skeleton" style={{ height: 360 }} /></div>

  const role = user?.role
  const ms = maxStep(doc.status)
  const building = job && (doc.status === 'skeleton' || doc.status === 'draft') && !doc.modules?.length

  return (
    <div>
      <div className="row row-wrap" style={{ marginBottom: 14 }}>
        <Link to="/app" className="btn btn-ghost btn-sm"><ArrowLeft size={15} /> Программы</Link>
        <div className="grow">
          <h1 className="h1" style={{ fontSize: 24, margin: 0 }}>{doc.title || 'Новая программа'}</h1>
          <div className="small muted">{doc.template || TYPE_LABEL[doc.type] || 'тип определяется'}{doc.volume_h ? ` · ${doc.volume_h} ак. ч` : ''} · версия {doc.version}</div>
        </div>
        <span className="chip chip-ok">{STATUS_LABEL[doc.status] || doc.status}</span>
        {doc.usage?.calls > 0 && <span className="chip"><Coins size={13} /> {doc.usage.cost_rub.toFixed(2)} ₽ · {doc.usage.calls} вызовов</span>}
      </div>

      {role !== 'expert' && (
        <div className="stepper">
          {STEPS.map((s, i) => {
            const n = i + 1
            const progress = defaultStep(doc.status) + (doc.status === 'approved' ? 1 : 0)
            const done = n < progress
            const cls = n === step ? 'current' : done ? 'done' : ''
            return (
              <button key={s} className={`step ${cls}`} disabled={n > ms} onClick={() => setStep(n)}>
                <span className="num">{done && n !== step ? <Check size={14} /> : n}</span>{s}
              </button>
            )
          })}
        </div>
      )}

      {role === 'expert' ? <ExpertView doc={doc} reload={load} /> : (
        <div key={step + sub}>
          {building && <Building job={job} />}
          {!building && step === 1 && <RequestView doc={doc} onNext={() => setStep(defaultStep(doc.status))} />}
          {!building && step === 2 && <QuestionsView doc={doc} onJob={track} />}
          {!building && step === 3 && <SkeletonView doc={doc} setDoc={setDoc} onNext={() => setStep(4)} />}
          {!building && step === 4 && <CheckView doc={doc} setDoc={setDoc} reload={load} onJob={(j) => { setStep(5); track(j) }} />}
          {!building && step === 5 && (job || doc.status === 'generating' || doc.status === 'skeleton_approved'
            ? <Generation doc={doc} job={job} reload={load} />
            : sub === 'edit' ? <EditView doc={doc} setDoc={setDoc} init={editInit} back={() => setSub('report')} />
              : <ReportView doc={doc} onEdit={(target, instruction) => { setEditInit({ target, instruction }); setSub('edit') }} onNext={() => setStep(6)} />)}
          {!building && step === 6 && (role === 'head' ? <ApproveView doc={doc} reload={load} /> : <TeamView doc={doc} setDoc={setDoc} reload={load} />)}
        </div>
      )}
    </div>
  )
}

/* ---------------- Сборка каркаса ---------------- */
function Building({ job }: { job: any }) {
  const lines = ['Определяю тип программы и шаблон АЦР', 'Подбираю профстандарт из реестра', 'Формулирую цель и компетенции З/У/Н', 'Разбиваю на модули и темы', 'Раскладываю часы солвером', 'Проверяю каркас по правилам']
  const [i, setI] = useState(0)
  useEffect(() => { const t = setInterval(() => setI((x) => Math.min(lines.length - 1, x + 1)), 2200); return () => clearInterval(t) }, [lines.length])
  return (
    <div className="card card-pad" style={{ textAlign: 'center', padding: 50 }}>
      <div style={{ width: 84, height: 84, margin: '0 auto 18px', borderRadius: 24, background: 'linear-gradient(135deg, var(--accent), var(--blue))', display: 'grid', placeItems: 'center', animation: 'float 3s ease-in-out infinite', boxShadow: '0 20px 50px rgba(33,160,56,.35)' }}>
        <Sparkles color="#fff" size={34} />
      </div>
      <h2 className="h2">Собираю каркас</h2>
      <p className="muted">{job?.progress?.text || 'Обычно это занимает до трёх минут.'}</p>
      <div style={{ maxWidth: 420, margin: '20px auto 0', textAlign: 'left', display: 'grid', gap: 8 }}>
        {lines.map((l, k) => (
          <div key={l} className="row small" style={{ opacity: k <= i ? 1 : 0.35, transition: 'opacity .4s' }}>
            {k < i ? <CheckCircle2 size={16} color="var(--accent)" /> : k === i ? <Spinner /> : <Clock size={16} />} {l}
          </div>
        ))}
      </div>
    </div>
  )
}

/* ---------------- 1. Запрос ---------------- */
function paramRows(doc: Doc): [string, string][] {
  const p = doc.params || {}
  const m = p.materials || {}
  const slides = m.slides_lessons?.length ? `занятия ${m.slides_lessons.join(', ')}` : m.slides_topic_hint ? `модуль «${m.slides_topic_hint}»` : m.slides_modules?.length ? `модули ${m.slides_modules.join(', ')}` : '—'
  return [
    ['Тип', TYPE_LABEL[doc.type] || '—'],
    ['Документ', doc.issued_document || '—'],
    ['Объём', p.volume_h ? `${p.volume_h} ак. ч` : '—'],
    ['Аудитория', p.audience || '—'],
    ['Форма', [p.form, p.distance ? 'ЭО и ДОТ' : ''].filter(Boolean).join(', ') || '—'],
    ['Срок', p.duration_weeks ? `${p.duration_weeks} нед.` : '—'],
    ['Режим', p.sessions_per_week ? `${p.sessions_per_week} раза в неделю по ${p.session_hours} ч` : p.max_hours_per_day ? `не больше ${p.max_hours_per_day} ч в день` : '—'],
    ['Аттестация', p.final_assessment_form || '—'],
    ['Профстандарт', doc.profstandard ? `${doc.profstandard.code} · ${doc.profstandard.confirmed ? 'из реестра' : 'сверить'}` : doc.type === 'doop' ? 'не требуется' : '—'],
    ['Тест', m.test_questions ? `${m.test_questions} вопросов` : '—'],
    ['Слайды', slides],
    ['Ограничения', (p.constraints || []).join('; ') || '—'],
  ]
}

function RequestView({ doc, onNext }: { doc: Doc; onNext: () => void }) {
  const rows = paramRows(doc)
  const filled = rows.filter(([, v]) => v !== '—').length
  return (
    <div className="grid-main">
      <div className="card card-pad stagger">
        <h2 className="h2">Запрос методиста</h2>
        <div className="row" style={{ alignItems: 'flex-start', gap: 12, marginBottom: 14 }}>
          <Avatar name="Мадина" role="methodist" />
          <div className="agent-msg" style={{ background: 'var(--card)', flex: 1 }}>{doc.request}</div>
        </div>
        {doc.references?.map((r: any) => (
          <div key={r.name} className="chip chip-blue" style={{ marginRight: 8, marginBottom: 8 }}><FileText size={13} /> {r.name} · {Math.round(r.chars / 1000)} тыс. знаков · разобран</div>
        ))}
        {doc.agent_notes?.map((n: string, i: number) => (
          <div key={i} className="agent-msg"><span className="avatar av-agent"><Sparkles size={14} /></span><div>{n}</div></div>
        ))}
        {doc.assumptions?.length > 0 && (
          <div className="agent-msg" style={{ background: 'var(--amber-soft)', borderColor: 'var(--amber-line)' }}>
            <AlertTriangle size={18} color="var(--amber)" />
            <div><b style={{ color: 'var(--amber)' }}>Допущения:</b> {doc.assumptions.map((a: any) => `${a.field} = ${typeof a.value === 'object' ? JSON.stringify(a.value) : a.value} (${a.source})`).join('; ')}</div>
          </div>
        )}
        <div style={{ marginTop: 16 }} className="small muted">Нормативная база: {doc.norm_mode === 'org' ? 'документы организации и реестр' : 'госстандарты из реестра'} · {doc.norm_base?.map((s: any) => s.bibl.split(' «')[0]).join(', ')}</div>
      </div>
      <aside className="card card-pad">
        <h3 className="h3">Распознанные параметры</h3>
        {rows.map(([k, v]) => <div className="param" key={k}><span className="k">{k}</span><span className="v">{v}</span></div>)}
        <div className="progress" style={{ margin: '14px 0 6px' }}><i style={{ width: `${(filled / rows.length) * 100}%` }} /></div>
        <div className="tiny muted">{filled} из {rows.length} параметров заполнены</div>
        <p className="tiny muted">Ссылки на акты и профстандарты — только из нормативной базы. Всё остальное получает пометку «не подтверждено».</p>
        <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }} onClick={onNext}>Дальше <ArrowRight size={16} /></button>
      </aside>
    </div>
  )
}

/* ---------------- 2. Вопросы ---------------- */
function QuestionsView({ doc, onJob }: { doc: Doc; onJob: (j: string) => void }) {
  const [ans, setAns] = useState<Record<string, string>>(() => Object.fromEntries((doc.questions || []).filter((q: any) => q.answer).map((q: any) => [q.id, q.answer])))
  const [busy, setBusy] = useState(false)
  const toast = useToast()
  const qs = doc.questions || []
  const editable = doc.status === 'questions'

  async function send(all?: boolean) {
    setBusy(true)
    try {
      const body = all ? Object.fromEntries(qs.map((q: any) => [q.id, ans[q.id] || 'На ваше усмотрение'])) : ans
      const r = await api(`/programs/${doc.id}/answers`, { method: 'POST', json: { answers: body } })
      onJob(r.job_id)
    } catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }

  if (!qs.length) return <div className="card empty"><CheckCircle2 size={34} color="var(--accent)" /><p>Все обязательные параметры есть, уточнять нечего.</p></div>
  return (
    <div className="grid-main">
      <div className="card card-pad">
        <div className="row"><h2 className="h2 grow" style={{ margin: 0 }}>Уточняющие вопросы</h2><span className="chip">Отвечено {Object.keys(ans).length} из {qs.length}</span></div>
        <p className="muted">Чтобы не додумывать, агенту не хватает {qs.length} сведений. Выберите вариант или напишите свой.</p>
        <div className="stagger col col-16">
          {qs.map((q: any, i: number) => (
            <div key={q.id} style={{ padding: 16, borderRadius: 16, border: '1px solid var(--line)', background: ans[q.id] ? 'var(--accent-soft)' : 'var(--card)', transition: 'background .3s' }}>
              <b>{i + 1}. {q.text}</b>
              <div className="row row-wrap" style={{ gap: 8, marginTop: 10 }}>
                {q.options.map((o: string) => (
                  <button key={o} disabled={!editable} className={`option-btn ${ans[q.id] === o ? 'sel' : ''}`} onClick={() => setAns({ ...ans, [q.id]: o })}>{o}</button>
                ))}
                <button disabled={!editable} className={`option-btn ${ans[q.id] === 'На ваше усмотрение' ? 'sel' : ''}`} onClick={() => setAns({ ...ans, [q.id]: 'На ваше усмотрение' })}>На ваше усмотрение</button>
              </div>
              {q.allow_custom && editable && (
                <input className="field" style={{ marginTop: 10 }} placeholder="Свой ответ" value={ans[q.id] && !q.options.includes(ans[q.id]) && ans[q.id] !== 'На ваше усмотрение' ? ans[q.id] : ''}
                  onChange={(e) => setAns({ ...ans, [q.id]: e.target.value })} />
              )}
            </div>
          ))}
        </div>
        {editable && (
          <div className="row" style={{ marginTop: 18 }}>
            <button className="btn btn-primary btn-lg" disabled={busy || Object.keys(ans).length < qs.length} onClick={() => send()}>{busy ? <Spinner /> : <>Ответить и собрать каркас <ArrowRight size={16} /></>}</button>
            <button className="btn btn-ghost" disabled={busy} onClick={() => send(true)}>Остальное — на ваше усмотрение</button>
          </div>
        )}
      </div>
      <aside className="card card-pad">
        <h3 className="h3">Правила вопросов</h3>
        <ul className="small" style={{ paddingLeft: 18, lineHeight: 1.7, color: 'var(--ink-2)' }}>
          <li>Не больше пяти, только по пустым обязательным полям</li>
          <li>Без технического жаргона, с вариантами ответа</li>
          <li>«На ваше усмотрение» — агент берёт значения профиля АЦР и показывает их в каркасе</li>
        </ul>
        <div className="agent-msg small"><span className="avatar av-agent"><Sparkles size={14} /></span>{doc.request}</div>
      </aside>
    </div>
  )
}

/* ---------------- 3. Каркас ---------------- */
function HoursTable({ doc, editable, onChange, onPatch }: { doc: Doc; editable: boolean; onChange?: (mid: string, k: string, v: number) => void; onPatch?: (patch: any) => Promise<void> }) {
  const [open, setOpen] = useState<Record<string, boolean>>({})
  const tot = doc.totals || {}
  const fa = doc.final_assessment || {}
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="table">
        <thead><tr><th>№</th><th>Модуль / тема</th><th className="num">Всего</th><th className="num">ЛК</th><th className="num">ПР</th><th className="num">ЛБ</th><th className="num">СРС</th><th>Контроль</th></tr></thead>
        <tbody>
          {doc.modules.map((m: any) => {
            const sum = KINDS.reduce((s, k) => s + (m.hours[k] || 0), 0)
            return [
              <tr key={m.id}>
                <td><b>{m.n}</b></td>
                <td><button onClick={() => setOpen({ ...open, [m.id]: !open[m.id] })} style={{ border: 0, background: 'none', padding: 0, color: 'inherit', fontWeight: 700, textAlign: 'left' }}>
                  <ChevronRight size={14} style={{ transform: open[m.id] ? 'rotate(90deg)' : '', transition: 'transform .2s', verticalAlign: -2 }} /> </button>
                  <b><EditableText value={m.title} disabled={!editable || !onPatch} onSave={(v) => onPatch!({ modules: [{ id: m.id, title: v }] })} /></b></td>
                <td className="num"><b style={{ color: sum !== m.hours.total ? 'var(--red)' : undefined }}>{sum}</b></td>
                {KINDS.map((k) => (
                  <td key={k} className="num">{editable ? <input className="hours-input" type="number" min={0} value={m.hours[k]} onChange={(e) => onChange?.(m.id, k, Number(e.target.value))} /> : m.hours[k]}</td>
                ))}
                <td className="small">{m.control}</td>
              </tr>,
              ...(open[m.id] ? m.topics.map((t: any) => (
                <tr key={t.id} className="sub"><td>{t.n}</td><td><EditableText value={t.title} disabled={!editable || !onPatch} onSave={(v) => onPatch!({ modules: [{ id: m.id, topics: [{ id: t.id, title: v }] }] })} /></td><td className="num">{t.hours.total}</td>{KINDS.map((k) => <td key={k} className="num">{t.hours[k]}</td>)}<td /></tr>
              )) : []),
            ]
          })}
          <tr><td /><td>Итоговая аттестация</td><td className="num">{fa.hours}</td>{[0, 1, 2].map((i) => <td key={i} className="num">{doc.type === 'dpp_pk_internship' ? 0 : '—'}</td>)}<td className="num">—</td><td className="small">{fa.form}</td></tr>
          <tr className="total"><td /><td>Итого</td><td className="num">{(tot.total || 0) + (fa.hours || 0)}</td>{KINDS.map((k) => <td key={k} className="num">{tot[k]}</td>)}<td /></tr>
        </tbody>
      </table>
    </div>
  )
}

function SkeletonView({ doc, setDoc, onNext }: { doc: Doc; setDoc: (d: Doc) => void; onNext: () => void }) {
  const editable = ['skeleton', 'returned'].includes(doc.status)
  const toast = useToast()
  const [saving, setSaving] = useState(false)
  const all = (doc.totals?.total || 0) + (doc.final_assessment?.hours || 0)
  const ok = all === doc.volume_h

  async function patch(body: any) {
    setSaving(true)
    try {
      const r = await api(`/programs/${doc.id}/skeleton`, { method: 'PATCH', json: body })
      setDoc({ ...r.program, totals: r.totals, readiness: doc.readiness })
    } catch (e: any) { toast(e.message, true) } finally { setSaving(false) }
  }

  async function change(mid: string, k: string, v: number) {
    const local = structuredClone(doc)
    const m = local.modules.find((x: any) => x.id === mid)
    m.hours[k] = v
    setDoc(local)
    setSaving(true)
    try {
      const r = await api(`/programs/${doc.id}/skeleton`, { method: 'PATCH', json: { modules: [{ id: mid, hours: { [k]: v } }] } })
      setDoc({ ...r.program, totals: r.totals, readiness: doc.readiness })
    } catch (e: any) { toast(e.message, true) } finally { setSaving(false) }
  }

  const cal = doc.calendar || {}
  return (
    <div className="grid-main">
      <div className="col">
        <section className="card card-pad">
          <div className="row"><h2 className="h2 grow" style={{ margin: 0 }}>Учебный план</h2>{saving && <span className="small muted row"><Spinner /> пересчитываю</span>}<span className={`chip ${ok ? 'chip-ok' : 'chip-err'}`}>{all} из {doc.volume_h} ч</span></div>
          <p className="small muted">{editable ? 'Часы в полях и названия модулей и тем можно менять: итоги и проверки пересчитываются сразу. Стрелка раскрывает темы.' : 'Каркас утверждён: часы меняются только точечной правкой.'}</p>
          <HoursTable doc={doc} editable={editable} onChange={change} onPatch={patch} />
          {!ok && <div className="callout warn small" style={{ marginTop: 12 }}>Сначала исправьте часы: сумма с аттестацией должна быть {doc.volume_h} ч.</div>}
        </section>
        <section className="card card-pad">
          <h2 className="h2">Календарный график</h2>
          <div className="row row-wrap" style={{ gap: 8 }}>
            <span className="chip chip-blue"><Clock size={13} /> {cal.weeks} нед.</span>
            {cal.sessions ? <span className="chip">{cal.sessions} занятий по {cal.session_hours} ч</span> : <span className="chip">{cal.work_days} учебных дней · до {cal.hours_per_day} ч/день · {cal.days_per_week} дн/нед</span>}
            {cal.chosen_option && <span className="chip chip-ok">вариант выбран</span>}
          </div>
          {cal.conflict && <div className="callout warn small">{cal.conflict}</div>}
          <div className="row row-wrap" style={{ gap: 6, marginTop: 12 }}>
            {(cal.schedule || []).map((w: any) => (
              <div key={w.week} title={w.items?.join('; ')} style={{ minWidth: 56, padding: '8px 6px', borderRadius: 10, background: 'var(--accent-soft)', textAlign: 'center' }}>
                <div className="tiny muted">нед. {w.week}</div><b>{w.hours} ч</b>
              </div>
            ))}
          </div>
        </section>
      </div>
      <aside className="col col-16">
        {editable && <section className="card card-pad"><TemplateSwitch doc={doc} setDoc={setDoc} /></section>}
        <section className="card card-pad">
          <h3 className="h3">Цель и компетенции</h3>
          <p className="small" style={{ color: 'var(--ink-2)' }}><EditableText multiline value={doc.goal} disabled={!editable} onSave={(v) => patch({ goal: v })} /></p>
          {doc.profstandard && (
            <div className="callout small" style={{ margin: '10px 0' }}>Профстандарт <b>{doc.profstandard.code}</b> «{doc.profstandard.title}», {doc.profstandard.order} · {doc.profstandard.confirmed ? 'из реестра' : 'коды ТФ сверить с реестром Минтруда'}</div>
          )}
          <div style={{ display: 'grid', gap: 8 }}>
            {doc.competencies.map((c: any) => {
              const cnt = (k: string) => c.indicators.filter((i: any) => i.kind === k).reduce((s: number, i: any) => s + i.outcomes.length, 0)
              return (
                <details key={c.id} style={{ border: '1px solid var(--line)', borderRadius: 12, padding: '8px 12px' }}>
                  <summary style={{ cursor: 'pointer', fontWeight: 700, fontSize: 14 }}>{c.code} <EditableText value={c.title} disabled={!editable} onSave={(v) => patch({ competencies: [{ id: c.id, title: v }] })} /> <span className="tiny muted">З {cnt('know')} · У {cnt('can')} · Н {cnt('own')}</span></summary>
                  {c.tf_codes?.length > 0 && <div className="tiny muted" style={{ marginTop: 6 }}>ТФ {c.tf_codes.join(', ')}</div>}
                  <ul className="small" style={{ paddingLeft: 18, margin: '6px 0 0', color: 'var(--ink-2)' }}>
                    {c.indicators.flatMap((i: any) => i.outcomes.map((o: any) => <li key={o.id}><b>{o.code}</b> <EditableText value={o.text} disabled={!editable} onSave={(v) => patch({ outcomes: [{ id: o.id, text: v }] })} /></li>))}
                  </ul>
                </details>
              )
            })}
          </div>
        </section>
        <section className="card card-pad">
          <p className="small muted" style={{ marginTop: 0 }}>Дальше агент проверит каркас: часы, шаблон, профстандарт, связь компетенций с темами и проверкой. Утверждаете каркас вы, на следующем шаге.</p>
          <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }} disabled={!ok} onClick={onNext}>Перейти к проверке каркаса <ArrowRight size={16} /></button>
          <p className="tiny muted" style={{ marginBottom: 0 }}>Пока каркас не утверждён, содержание не генерируется.</p>
        </section>
      </aside>
    </div>
  )
}

/* ---------------- 4. Проверка каркаса ---------------- */
function RuleList({ rules }: { rules: any[] }) {
  const groups = useMemo(() => {
    const g: Record<string, any[]> = {}
    rules.forEach((r) => { const k = r.check ? `${r.check}` : 'w'; (g[k] ||= []).push(r) })
    return g
  }, [rules])
  const TITLES: Record<string, string> = { 1: 'Арифметика часов', 2: 'Полнота шаблона', 3: 'Календарная выполнимость', 4: 'Поля для людей', 5: 'Покрытие компетенций', 6: 'Привязка оценивания к РО', 7: 'Источники', 8: 'Оригинальность', 9: 'Измеримость заданий', 10: 'Точечная правка без регрессий', w: 'Предупреждения' }
  return (
    <div className="stagger" style={{ display: 'grid', gap: 8 }}>
      {Object.entries(groups).map(([k, rs]) => {
        const st = rs.some((r) => r.status === 'fail') ? 'fail' : rs.some((r) => r.status === 'warn') ? 'warn' : rs.every((r) => r.status === 'skip') ? 'skip' : 'pass'
        const msgs = rs.flatMap((r) => r.messages.map((m: string) => `${r.id}: ${m}`))
        return (
          <div key={k} className="check-item">
            <span className={`check-icon ci-${st === 'skip' ? 'pass' : st}`}>{st === 'fail' ? '✕' : st === 'warn' ? '!' : '✓'}</span>
            <div className="grow">
              <b>{k !== 'w' ? `${k}. ` : ''}{TITLES[k]}</b>
              <div className="small muted">{msgs.length ? msgs.slice(0, 3).join(' · ') : st === 'skip' ? 'проверяется на этапе комплекта' : rs.map((r) => r.id).join(', ') + ' — в порядке'}</div>
            </div>
          </div>
        )
      })}
    </div>
  )
}

function Coverage({ rows }: { rows: any[] }) {
  if (!rows?.length) return null
  const cols = Array.from(new Set(rows.flatMap((r) => Object.keys(r.cells || {}))))
  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="table">
        <thead><tr><th>Результат обучения</th><th>Темы</th>{cols.map((c) => <th key={c} className="num">{c}</th>)}<th className="num">Всего</th></tr></thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.lo_id}>
              <td><b>{r.lo}</b> <span className="small muted">{r.text}</span></td>
              <td className="small">{r.topics?.join(', ')}</td>
              {cols.map((c) => { const v = r.cells?.[c] || 0; return <td key={c} className="num">{v ? <span className={`cover-cell cover-${Math.min(3, v)}`} style={{ display: 'inline-block', padding: '2px 6px' }}>{v}</span> : ''}</td> })}
              <td className="num"><span className={`chip ${r.means >= 2 ? 'chip-ok' : 'chip-err'}`}>{r.means}</span></td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="tiny muted">Число в ячейке — сколько заданий этого средства проверяют результат. Нужно минимум 2 средства в строке.</p>
    </div>
  )
}

function CheckView({ doc, setDoc, reload, onJob }: { doc: Doc; setDoc: (d: Doc) => void; reload: () => void; onJob: (j: string) => void }) {
  const rep = doc.report || { rules: [], proposals: [] }
  const toast = useToast()
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState('')
  const editable = ['skeleton', 'returned'].includes(doc.status)
  const fails = rep.rules.filter((r: any) => r.status === 'fail').length
  const pending = rep.proposals.filter((p: any) => !p.decided)

  async function decide(p: any, decision: 'accept' | 'keep') {
    setBusy(p.rule_id + p.option_id)
    try {
      const r = await api(`/programs/${doc.id}/skeleton/decisions`, { method: 'POST', json: { rule_id: p.rule_id, decision, node: p.node || '', proposal: p.proposal || '', option_id: p.option_id || '' } })
      setDoc({ ...r.program, totals: doc.totals })
      reload()
      toast(decision === 'accept' ? 'Предложение принято' : 'Оставлено как есть')
    } catch (e: any) { toast(e.message, true) } finally { setBusy('') }
  }
  async function approve(decision: 'approve' | 'return') {
    setBusy(decision)
    try {
      const r = await api(`/programs/${doc.id}/skeleton/approve`, { method: 'POST', json: { decision, comment } })
      toast(decision === 'approve' ? 'Каркас утверждён. Собираю комплект' : 'Каркас возвращён агенту')
      onJob(r.job_id)
    } catch (e: any) { toast(e.message, true) } finally { setBusy('') }
  }

  return (
    <div className="grid-main">
      <div className="col">
        <section className="card card-pad">
          <div className="row"><h2 className="h2 grow" style={{ margin: 0 }}>Проверка каркаса</h2><span className={`chip ${fails ? 'chip-err' : 'chip-ok'}`}>{rep.blocking_passed} из {rep.blocking_total} проверок</span></div>
          <p className="small muted">Агент проверил каркас до генерации содержания. Решение принимаете вы. ✓ всё в порядке · ! нужно ваше решение · ✕ ошибка, утвердить нельзя</p>
          <RuleList rules={rep.rules} />
        </section>
        <section className="card card-pad">
          <h2 className="h2">Что изучают и чем проверяют</h2>
          {doc.profstandard && <p className="small muted">Профстандарт {doc.profstandard.code}, {doc.profstandard.order}</p>}
          <Coverage rows={rep.coverage} />
        </section>
      </div>
      <aside className="col col-16">
        {pending.length > 0 && (
          <section className="card card-pad" style={{ borderColor: 'var(--amber-line)', background: 'var(--amber-soft)' }}>
            <h3 className="h3" style={{ color: 'var(--amber)' }}>! Нужно ваше решение</h3>
            {pending.map((p: any, i: number) => (
              <div key={i} style={{ padding: '10px 0', borderTop: i ? '1px solid var(--amber-line)' : 0 }}>
                <div className="small"><b>{p.rule_id}</b> {p.title}</div>
                <div className="small" style={{ margin: '6px 0' }}>Агент предлагает: «{p.proposal}»</div>
                {editable && (
                  <div className="row" style={{ gap: 6 }}>
                    <button className="btn btn-primary btn-sm" disabled={!!busy} onClick={() => decide(p, 'accept')}>{busy === p.rule_id + p.option_id ? <Spinner /> : 'Принять'}</button>
                    {!p.option_id && <button className="btn btn-ghost btn-sm" disabled={!!busy} onClick={() => decide(p, 'keep')}>Оставить как есть</button>}
                  </div>
                )}
              </div>
            ))}
          </section>
        )}
        <section className="card card-pad">
          <h3 className="h3">Решение по каркасу</h3>
          {editable ? (
            <>
              <textarea className="field" style={{ minHeight: 80 }} placeholder="Комментарий агенту, если нужно" value={comment} onChange={(e) => setComment(e.target.value)} />
              <div className="row row-wrap" style={{ marginTop: 10 }}>
                <button className="btn btn-primary" disabled={!!busy || fails > 0} onClick={() => approve('approve')}>{busy === 'approve' ? <Spinner /> : <><Check size={16} /> Утвердить каркас</>}</button>
                <button className="btn btn-ghost" disabled={!!busy || !comment.trim()} onClick={() => approve('return')}><Undo2 size={16} /> Вернуть с комментарием</button>
              </div>
              <p className="tiny muted">После утверждения агент соберёт программу, тесты, задания, лекции и слайды. Каркас можно будет поменять точечной правкой.</p>
              {fails > 0 && <p className="small" style={{ color: 'var(--red)' }}>Есть ошибки ✕ — сначала исправьте их.</p>}
            </>
          ) : <p className="small muted">Каркас утверждён. Агент собрал комплект по этому каркасу.</p>}
        </section>
      </aside>
    </div>
  )
}

/* ---------------- 5. Сборка комплекта ---------------- */
function Generation({ doc, job, reload }: { doc: Doc; job: any; reload: () => void }) {
  const p = job?.progress || {}
  const mods = p.modules || doc.modules.map((m: any) => ({ n: m.n, title: m.title, status: 'ждёт', parts: '' }))
  const done = mods.filter((m: any) => m.status === 'готово').length
  useEffect(() => { if (!job) { const t = setInterval(reload, 3000); return () => clearInterval(t) } }, [job, reload])
  return (
    <div className="grid-main">
      <section className="card card-pad">
        <div className="row"><h2 className="h2 grow" style={{ margin: 0 }}>Собираю комплект по модулям</h2><span className="chip chip-blue"><Spinner /> {done} из {mods.length} готово</span></div>
        <div className="progress" style={{ margin: '16px 0' }}><i style={{ width: `${mods.length ? (done / mods.length) * 100 : 5}%` }} /></div>
        <div className="stagger" style={{ display: 'grid', gap: 8 }}>
          {mods.map((m: any) => (
            <div key={m.n} className="check-item">
              <span className={`check-icon ${m.status === 'готово' ? 'ci-pass' : 'ci-warn'}`}>{m.status === 'готово' ? '✓' : m.status === 'идёт' ? <Spinner /> : m.n}</span>
              <div className="grow"><b>Модуль {m.n}. {m.title}</b><div className="small muted">{m.parts || m.status}</div></div>
            </div>
          ))}
        </div>
      </section>
      <aside className="col col-16">
        <section className="card card-pad">
          <h3 className="h3">Что делает агент</h3>
          <div className="timeline small">
            {(p.feed || [{ t: '', text: 'Готовлю задания для модулей' }]).map((f: any, i: number, a: any[]) => (
              <div key={i} className={`tl-item ${i < a.length - 1 ? 'done' : 'now'}`}>{f.text}<div className="tiny muted">{f.t}</div></div>
            ))}
            <div className="tl-item">validate · после всех модулей</div>
          </div>
        </section>
        <section className="card card-pad">
          <div className="param"><span className="k">Время</span><span className="v">{p.elapsed_s ? `${Math.round(p.elapsed_s)} с` : '—'} · лимит ТЗ 20 мин</span></div>
          <div className="param"><span className="k">Осталось</span><span className="v">{p.eta_s != null ? `≈ ${Math.max(1, Math.round(p.eta_s))} с` : 'оцениваю'}</span></div>
          <div className="param"><span className="k">Потоков</span><span className="v">{p.workers || 6} модулей параллельно</span></div>
          <div className="param"><span className="k">Токены</span><span className="v">{p.usage?.tokens ?? 0}</span></div>
          <div className="param"><span className="k">Стоимость</span><span className="v">{p.usage?.cost_rub ?? 0} ₽ по тарифу Cloud.ru</span></div>
          <p className="tiny muted">GigaChat 3 Pro собирает содержание, код проверяет часы и 23 правила из 27.</p>
        </section>
      </aside>
    </div>
  )
}

const EXPORTS = [
  { fmt: 'docx', label: 'Программа .docx', icon: FileText },
  { fmt: 'pptx', label: 'Слайды .pptx', icon: Presentation },
  { fmt: 'moodle_xml', label: 'Тесты Moodle XML', icon: FileSpreadsheet },
  { fmt: 'gift', label: 'Тесты GIFT', icon: FileSpreadsheet },
  { fmt: 'json', label: 'JSON', icon: FileText },
  { fmt: 'lectures_docx', label: 'Лекции .docx', icon: FileText },
  { fmt: 'order_draft', label: 'Проект приказа', icon: FileText },
]

function ExportBlock({ doc }: { doc: Doc }) {
  const toast = useToast()
  const [busy, setBusy] = useState('')
  return (
    <div style={{ display: 'grid', gap: 8 }}>
      {EXPORTS.map((e) => (
        <button key={e.fmt} className="btn btn-ghost" style={{ justifyContent: 'flex-start' }} disabled={!!busy}
          onClick={async () => { setBusy(e.fmt); try { await download(doc.id, e.fmt) } catch (er: any) { toast(er.message, true) } finally { setBusy('') } }}>
          {busy === e.fmt ? <Spinner /> : <e.icon size={16} />} {e.label}<span className="grow" /><Download size={15} className="muted" />
        </button>
      ))}
    </div>
  )
}

function ModuleContent({ doc, module }: { doc: Doc; module: any }) {
  const [tab, setTab] = useState('program')
  const kit = doc.kit || {}
  const mp = kit.module_programs?.find((x: any) => x.module_id === module.id)
  const qs = kit.questions?.filter((q: any) => q.module_id === module.id) || []
  const ts = kit.tasks?.filter((t: any) => t.module_id === module.id) || []
  const lecs = kit.lectures?.filter((l: any) => l.module_id === module.id) || []
  return (
    <div>
      <div className="tabs">
        {[['program', 'Программа модуля'], ['lectures', `Лекции · ${lecs.length}`], ['test', `Тест · ${qs.length}`], ['tasks', `Задания · ${ts.length}`]].map(([k, l]) => (
          <button key={k} className={`tab ${tab === k ? 'active' : ''}`} onClick={() => setTab(k)}>{l}</button>
        ))}
      </div>
      <div key={tab} className="page-enter">
        {tab === 'program' && (
          <div>
            {mp?.annotation && <p style={{ color: 'var(--ink-2)' }}>{mp.annotation}</p>}
            {module.topics.map((t: any) => (
              <div key={t.id} style={{ marginBottom: 10 }}>
                <b>Тема {t.n}. {t.title}</b> <span className="tiny muted">{t.hours.total} ч · ЛК {t.hours.lk} · ПР {t.hours.pr} · СРС {t.hours.srs}</span>
                <div className="small" style={{ color: 'var(--ink-2)' }}>{mp?.content?.find((c: any) => c.topic_id === t.id)?.text || t.description}</div>
              </div>
            ))}
          </div>
        )}
        {tab === 'lectures' && (lecs.length ? lecs.map((l: any) => (
          <details key={l.id} style={{ border: '1px solid var(--line)', borderRadius: 14, padding: '10px 14px', marginBottom: 10 }}>
            <summary style={{ cursor: 'pointer', fontWeight: 700 }}>{l.title} <span className="tiny muted">{l.duration_min} мин{l.slides?.length ? ` · ${l.slides.length} слайдов` : ''}</span></summary>
            <ul className="small">{l.plan.map((s: any, i: number) => <li key={i}>{s.min} мин — {s.text}</li>)}</ul>
            {l.code_examples?.map((c: string, i: number) => <pre key={i} style={{ background: '#0D1114', color: '#D7F5DF', padding: 12, borderRadius: 10, overflow: 'auto', fontSize: 12 }}>{c}</pre>)}
            {l.slides?.length > 0 && (
              <div className="row row-wrap" style={{ gap: 10, marginTop: 8 }}>
                {l.slides.map((s: any) => (
                  <div key={s.id} style={{ width: 200, aspectRatio: '16/9', borderRadius: 10, border: '1px solid var(--line)', padding: 10, background: 'var(--card)', borderTop: '4px solid var(--accent)', overflow: 'hidden' }}>
                    <div style={{ fontWeight: 800, fontSize: 12 }}>{s.title}</div>
                    <ul style={{ margin: '4px 0 0', paddingLeft: 14, fontSize: 10, color: 'var(--ink-2)' }}>{s.bullets.slice(0, 4).map((b: string, i: number) => <li key={i}>{b}</li>)}</ul>
                  </div>
                ))}
              </div>
            )}
          </details>
        )) : <p className="muted small">Лекций в этом модуле нет (например, стажировка без аудиторных занятий).</p>)}
        {tab === 'test' && (qs.length ? qs.map((q: any, i: number) => (
          <div key={q.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--line)' }}>
            <b>{i + 1}. {q.stem}</b> <span className="tiny muted">РО {q.lo_ids.join(', ')}</span>
            <div className="row row-wrap" style={{ gap: 6, marginTop: 6 }}>{q.options.map((o: string, j: number) => <span key={j} className={`chip ${j === q.key ? 'chip-ok' : ''}`}>{j === q.key && <Check size={12} />}{o}</span>)}</div>
          </div>
        )) : <p className="muted small">Вопросов в модуле нет.</p>)}
        {tab === 'tasks' && (ts.length ? ts.map((t: any) => (
          <div key={t.id} style={{ padding: '10px 0', borderBottom: '1px solid var(--line)' }}>
            <b>{t.title}</b> <span className="tiny muted">РО {t.lo_ids.join(', ')}</span>
            <p className="small" style={{ margin: '6px 0', color: 'var(--ink-2)' }}>{t.statement}</p>
            {t.expected_result && <div className="small"><b>Ожидаемый результат:</b> {t.expected_result}</div>}
            <div className="row row-wrap" style={{ gap: 6, marginTop: 6 }}>{t.criteria.map((c: any, i: number) => <span key={i} className="chip">{c.text} · {c.points} б.</span>)}</div>
          </div>
        )) : <p className="muted small">Заданий в модуле нет.</p>)}
      </div>
    </div>
  )
}

function ReportView({ doc, onEdit, onNext }: { doc: Doc; onEdit: (target?: string, instruction?: string) => void; onNext: () => void }) {
  const rep = doc.report || { rules: [] }
  const [mod, setMod] = useState(doc.modules[0]?.id)
  const unconfirmed = (doc.sources || []).filter((s: any) => !s.confirmed)
  const m = doc.modules.find((x: any) => x.id === mod)
  return (
    <div className="col">
      <div className="grid-main">
        <section className="card card-pad">
          <div className="row"><h2 className="h2 grow" style={{ margin: 0 }}>Отчёт автопроверки комплекта</h2>
            <span className={`chip ${rep.blocking_passed === rep.blocking_total ? 'chip-ok' : 'chip-err'}`}>{rep.blocking_passed} из {rep.blocking_total} блокирующих</span></div>
          <div style={{ marginTop: 14 }}><RuleList rules={rep.rules} /></div>
          {unconfirmed.length > 0 && <div className="callout warn small">Для методиста: {unconfirmed.length} источн. не найдено в реестре и помечено «не подтверждено» в списке литературы. Проверьте вручную или замените.</div>}
          {(doc.kit?.drafts || []).length > 0 && <div className="callout warn small">Модель не ответила для модулей {doc.modules.filter((x: any) => doc.kit.drafts.includes(x.id)).map((x: any) => x.n).join(', ')}: их содержание собрано по шаблону из каркаса. Пересоберите модуль точечной правкой или передайте эксперту.</div>}
        </section>
        <aside className="col col-16">
          <section className="card card-pad">
            <h3 className="h3">Выгрузка</h3>
            <ExportBlock doc={doc} />
          </section>
          <section className="card card-pad">
            <div className="param"><span className="k">Время сборки</span><span className="v">{Math.round(doc.timing_s?.kit || 0)} с</span></div>
            <div className="param"><span className="k">Вызовов модели</span><span className="v">{doc.usage?.calls}</span></div>
            <div className="param"><span className="k">Стоимость</span><span className="v">{(doc.usage?.cost_rub || 0).toFixed(2)} ₽</span></div>
          </section>
        </aside>
      </div>
      <section className="card card-pad">
        <h2 className="h2">Покрытие результатов обучения</h2>
        <Coverage rows={rep.coverage} />
      </section>
      <section className="card card-pad">
        <div className="row row-wrap"><h2 className="h2 grow" style={{ margin: 0 }}>Содержание комплекта</h2>
          <select className="field" style={{ width: 'auto' }} value={mod} onChange={(e) => setMod(e.target.value)}>
            {doc.modules.map((x: any) => <option key={x.id} value={x.id}>Модуль {x.n}. {x.title}</option>)}
          </select></div>
        <div style={{ marginTop: 12 }}>{m && <ModuleContent doc={doc} module={m} />}</div>
      </section>
      <ToolsPanel doc={doc} onEdit={(t, i) => onEdit(t, i)} />
      <section className="card card-pad row row-wrap">
        <div className="grow"><b>Нужно поменять тему, тест или задание?</b><div className="small muted">Агент пересоберёт только связанные части.</div></div>
        <button className="btn btn-ghost" onClick={() => onEdit()}><GitBranch size={16} /> Точечная правка</button>
        <button className="btn btn-primary" onClick={onNext}>Перейти к согласованию <ArrowRight size={16} /></button>
      </section>
    </div>
  )
}

/* ---------------- Точечная правка ---------------- */
function EditView({ doc, setDoc, back, init }: { doc: Doc; setDoc: (d: Doc) => void; back: () => void; init?: { target?: string; instruction?: string } }) {
  const toast = useToast()
  const targets = useMemo(() => [
    ...doc.modules.flatMap((m: any) => m.topics.map((t: any) => ({ id: t.id, label: `Тема ${t.n}. ${t.title}`, kind: 'topic', title: t.title, desc: t.description, hours: t.hours }))),
    ...(doc.kit?.tasks || []).map((t: any) => ({ id: t.id, label: `Задание: ${t.title}`, kind: 'task' })),
    ...(doc.kit?.questions || []).slice(0, 60).map((q: any) => ({ id: q.id, label: `Вопрос: ${q.stem.slice(0, 70)}`, kind: 'question' })),
  ], [doc])
  const [target, setTarget] = useState(init?.target && targets.some((x: any) => x.id === init.target) ? init.target : targets[0]?.id)
  const [title, setTitle] = useState('')
  const [instr, setInstr] = useState(init?.instruction || '')
  const [plan, setPlan] = useState<any>(null)
  const [result, setResult] = useState<any>(null)
  const [busy, setBusy] = useState('')
  const t = targets.find((x: any) => x.id === target)

  useEffect(() => { setPlan(null); setResult(null); setTitle('') ; if (!target) return
    api(`/programs/${doc.id}/edits`, { method: 'POST', json: { target, dry_run: true } }).then((r) => setPlan(r.plan)).catch(() => {})
  }, [target, doc.id])

  async function apply() {
    setBusy('apply')
    try {
      const r = await api(`/programs/${doc.id}/edits`, { method: 'POST', json: { target, instruction: instr, new_title: title } })
      setResult(r)
      setDoc({ ...r.program, totals: doc.totals, readiness: doc.readiness })
      toast(`Правка применена: пересобрано ${r.changed?.length || 0} элементов`)
    } catch (e: any) { toast(e.message, true) } finally { setBusy('') }
  }

  return (
    <div className="grid-main">
      <section className="card card-pad">
        <button className="btn btn-ghost btn-sm" onClick={back}><ArrowLeft size={14} /> К отчёту автопроверки</button>
        <h2 className="h2" style={{ marginTop: 14 }}>Точечная правка</h2>
        <label className="label">Что изменить</label>
        <select className="field" value={target} onChange={(e) => setTarget(e.target.value)}>{targets.map((x: any) => <option key={x.id} value={x.id}>{x.label}</option>)}</select>
        {t?.kind === 'topic' && (
          <div className="grid-2" style={{ marginTop: 14 }}>
            <div className="card" style={{ padding: 14, background: 'var(--bg-2)' }}>
              <div className="tiny muted">Было</div><b>{t.title}</b><div className="small muted">{t.desc}</div>
              <div className="tiny muted" style={{ marginTop: 6 }}>{t.hours.total} ч: ЛК {t.hours.lk}, ПР {t.hours.pr}</div>
            </div>
            <div className="card" style={{ padding: 14, borderColor: 'var(--accent)' }}>
              <div className="tiny muted">Станет</div>
              <input className="field" placeholder="Новое название темы" value={title} onChange={(e) => setTitle(e.target.value)} />
              <div className="tiny muted" style={{ marginTop: 6 }}>Часы модуля не меняются.</div>
            </div>
          </div>
        )}
        <label className="label" style={{ marginTop: 14 }}>Инструкция агенту</label>
        <textarea className="field" style={{ minHeight: 90 }} value={instr} onChange={(e) => setInstr(e.target.value)} placeholder="Например: заменить на даты и временные ряды на данных о платежах" />
        <div className="row" style={{ marginTop: 14 }}>
          <button className="btn btn-primary" disabled={!!busy || (!instr.trim() && !title.trim())} onClick={apply}>{busy ? <Spinner /> : <><GitBranch size={16} /> Применить правку</>}</button>
          <button className="btn btn-ghost" onClick={back}>Отмена</button>
        </div>
        {result && (
          <div className="callout small" style={{ marginTop: 14 }}>
            Правка применена: пересобрано {result.changed?.length || 0} элементов, проверка {result.check_ok ? 'пройдена' : 'нашла замечания'} заново, остальной комплект не изменился.
          </div>
        )}
      </section>
      <aside className="card card-pad">
        <h3 className="h3">Что затронет правка</h3>
        <p className="small muted">По графу связей: только потомки выбранного узла.</p>
        {!plan ? <div className="skeleton" style={{ height: 120 }} /> : (
          <>
            <div className="small" style={{ fontWeight: 800, color: 'var(--accent-deep)' }}>Пересоберу · {plan.nodes?.length || 0}</div>
            <ul className="small" style={{ paddingLeft: 18 }}>{plan.rebuild?.map((x: string) => <li key={x}>{x}</li>)}</ul>
            <div className="small" style={{ fontWeight: 800 }}>Не меняется</div>
            <ul className="small muted" style={{ paddingLeft: 18 }}>{plan.keep?.map((x: string) => <li key={x}>{x}</li>)}</ul>
          </>
        )}
      </aside>
    </div>
  )
}

/* ---------------- 6. Согласование (методист) ---------------- */
function TeamView({ doc, setDoc, reload }: { doc: Doc; setDoc: (d: Doc) => void; reload: () => void }) {
  const toast = useToast()
  const [events, setEvents] = useState<any[]>([])
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [busy, setBusy] = useState('')
  const rd = doc.readiness || {}
  const tot = (doc.totals?.total || 0) + (doc.final_assessment?.hours || 0)
  const accepted = doc.modules.filter((m: any) => m.review_status === 'accepted').length
  const canSubmit = rd.blocking === 10 && accepted === doc.modules.length && !['on_approval', 'approved'].includes(doc.status)
  useEffect(() => { api(`/programs/${doc.id}/events`).then(setEvents).catch(() => {}) }, [doc.id, doc.version])

  async function assign(mid: string, expert: string, quiet = false) {
    try {
      const r = await api(`/programs/${doc.id}/modules/${mid}/expert`, { method: 'PUT', json: { expert_id: expert } })
      setDoc({ ...r.program, totals: doc.totals, readiness: doc.readiness })
      if (!quiet) toast('Эксперт назначен, уведомление отправлено')
    } catch (e: any) { toast(e.message, true) }
  }
  async function assignAll() {
    let n = 0
    for (const [i, m] of doc.modules.entries()) if (!m.expert_id) { await assign(m.id, EXPERTS[i % 2].id, true); n++ }
    toast(`Назначено модулей: ${n}. Эксперты получили уведомления`)
    reload()
  }
  async function answer(c: any, apply: boolean) {
    setBusy(c.id)
    try {
      await api(`/programs/${doc.id}/comments/answer`, { method: 'POST', json: { comment_id: c.id, answer: answers[c.id] || '', apply_proposal: apply } })
      toast(apply ? 'Агент внёс правку и заново прошёл проверку' : 'Ответ отправлен эксперту'); reload()
    } catch (e: any) { toast(e.message, true) } finally { setBusy('') }
  }
  async function submit() {
    setBusy('submit')
    try { await api(`/programs/${doc.id}/submit`, { method: 'POST' }); toast('Программа отправлена руководителю'); reload() } catch (e: any) { toast(e.message, true) } finally { setBusy('') }
  }

  const name = (id: string) => EXPERTS.find((e) => e.id === id)?.name || '—'
  const open = (doc.comments || []).filter((c: any) => c.status === 'open')
  return (
    <div className="grid-main">
      <div className="col">
        <section className="card card-pad">
          <h2 className="h2">Согласование комплекта</h2>
          <p className="small muted">Каждый эксперт видит только свои модули и вычитывает содержание. Когда все модули приняты, программа уходит руководителю.</p>
          <div className="row row-wrap" style={{ gap: 8, marginBottom: 14 }}>
            <span className={`chip ${rd.blocking === 10 ? 'chip-ok' : 'chip-err'}`}>✓ Блокирующие проверки {rd.blocking} из 10</span>
            <span className={`chip ${tot === doc.volume_h ? 'chip-ok' : 'chip-err'}`}>✓ Часы {tot} из {doc.volume_h}</span>
            <span className="chip chip-blue">Модули {accepted} из {doc.modules.length} приняты</span>
            <div className="grow" />
            {doc.modules.some((m: any) => !m.expert_id) && <button className="btn btn-soft btn-sm" onClick={assignAll}><Users size={14} /> Назначить всех</button>}
          </div>
          <div style={{ overflowX: 'auto' }}>
            <table className="table">
              <thead><tr><th>№</th><th>Модуль</th><th className="num">Часы</th><th>Эксперт</th><th>Статус</th></tr></thead>
              <tbody>
                {doc.modules.map((m: any) => (
                  <tr key={m.id}>
                    <td><b>{m.n}</b></td><td>{m.title}</td><td className="num">{m.hours.total}</td>
                    <td>
                      <select className="field" style={{ padding: '6px 10px', width: 150 }} value={m.expert_id || ''} onChange={(e) => assign(m.id, e.target.value)} disabled={['on_approval', 'approved'].includes(doc.status)}>
                        <option value="" disabled>Назначить</option>
                        {EXPERTS.map((e) => <option key={e.id} value={e.id}>{e.name}</option>)}
                      </select>
                    </td>
                    <td><span className={`chip ${REVIEW_LABEL[m.review_status]?.[1] || ''}`}>{REVIEW_LABEL[m.review_status]?.[0]}</span></td>
                  </tr>
                ))}
                <tr className="total"><td /><td>Итого с аттестацией</td><td className="num">{tot}</td><td colSpan={2} className="small">Аттестация — {doc.final_assessment?.form?.toLowerCase()}</td></tr>
              </tbody>
            </table>
          </div>
        </section>
        {open.map((c: any) => (
          <section key={c.id} className="card card-pad" style={{ borderColor: 'var(--blue)' }}>
            <div className="row"><Avatar name={name(c.author)} role="expert" /><b className="grow">Вопрос эксперта · {name(c.author)}</b><span className="tiny muted">{(c.at || '').slice(11, 16)}</span></div>
            <p>«{c.text}»</p>
            {c.agent_proposal && <div className="agent-msg small"><span className="avatar av-agent"><Sparkles size={14} /></span><div>Агент предлагает: {c.agent_proposal}</div></div>}
            <textarea className="field" style={{ minHeight: 60, marginTop: 10 }} placeholder="Ответ эксперту" value={answers[c.id] || ''} onChange={(e) => setAnswers({ ...answers, [c.id]: e.target.value })} />
            <div className="row" style={{ marginTop: 10 }}>
              {c.agent_proposal && c.node_id && <button className="btn btn-primary btn-sm" disabled={!!busy} onClick={() => answer(c, true)}><Sparkles size={14} /> Передать агенту</button>}
              <button className="btn btn-ghost btn-sm" disabled={!!busy || !answers[c.id]} onClick={() => answer(c, false)}><MessageSquare size={14} /> Ответить</button>
            </div>
          </section>
        ))}
      </div>
      <aside className="col col-16">
        <section className="card card-pad">
          <h3 className="h3">Маршрут программы</h3>
          <div className="timeline small">
            <div className="tl-item done"><b>Мадина собрала комплект</b><div className="tiny muted">Блокирующие проверки {rd.blocking} из 10</div></div>
            <div className={`tl-item ${accepted === doc.modules.length ? 'done' : 'now'}`}><b>Эксперты вычитывают модули</b><div className="tiny muted">Принято {accepted} из {doc.modules.length}</div></div>
            <div className={`tl-item ${doc.status === 'approved' ? 'done' : doc.status === 'on_approval' ? 'now' : ''}`}><b>Руководитель утверждает</b><div className="tiny muted">Видит готовность, решения людей, срок и затраты</div></div>
            <div className="tl-item"><b>Проект приказа</b><div className="tiny muted">Номер, дату, ФИО и подписи заполняют люди</div></div>
          </div>
          <button className="btn btn-primary" style={{ width: '100%', justifyContent: 'center' }} disabled={!canSubmit || !!busy} onClick={submit}>{busy === 'submit' ? <Spinner /> : <><Send size={16} /> Отправить на утверждение</>}</button>
          {!canSubmit && !['on_approval', 'approved'].includes(doc.status) && <p className="tiny muted">Станет доступна, когда все {doc.modules.length} модулей приняты и пройдены 10 из 10 проверок.</p>}
        </section>
        <section className="card card-pad">
          <h3 className="h3"><History size={16} style={{ verticalAlign: -3 }} /> Журнал</h3>
          <div style={{ maxHeight: 320, overflow: 'auto' }}>
            {events.slice(0, 30).map((e, i) => (
              <div key={i} className="small" style={{ padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
                <span className="tiny muted">{(e.at || '').slice(11, 16)}</span> {e.text || e.action}
              </div>
            ))}
          </div>
        </section>
      </aside>
    </div>
  )
}

/* ---------------- Утверждение (руководитель) ---------------- */
function ApproveView({ doc, reload }: { doc: Doc; reload: () => void }) {
  const toast = useToast()
  const [comment, setComment] = useState('')
  const [busy, setBusy] = useState('')
  const rd = doc.readiness || {}
  const tot = (doc.totals?.total || 0) + (doc.final_assessment?.hours || 0)
  const rep = doc.report || { rules: [], coverage: [] }
  const covered = rep.coverage?.filter((r: any) => r.means >= 2).length || 0
  async function decide(decision: 'approve' | 'return') {
    setBusy(decision)
    try {
      await api(`/programs/${doc.id}/approval`, { method: 'POST', json: { decision, comment } })
      toast(decision === 'approve' ? 'Программа утверждена. Проект приказа передан методисту' : 'Программа возвращена методисту'); reload()
    } catch (e: any) { toast(e.message, true) } finally { setBusy('') }
  }
  const people = (doc.approvals || []).slice(-8)
  return (
    <div className="col">
    <div className="grid-main">
      <div className="col">
        <section className="card card-pad row row-wrap" style={{ gap: 24 }}>
          <div className="ring" style={{ ['--p' as any]: rd.index || 0 }}><span>{rd.index || 0}%</span></div>
          <div className="grow">
            <h2 className="h2" style={{ marginBottom: 6 }}>Утверждение программы</h2>
            <div className="small muted">{doc.template} «{doc.title}» · {doc.volume_h} ч</div>
            <div className="row row-wrap" style={{ gap: 8, marginTop: 10 }}>
              <span className={`chip ${rd.blocking === 10 ? 'chip-ok' : 'chip-err'}`}>Комплект · {rd.blocking} из 10 проверок</span>
              <span className={`chip ${rd.modules_accepted === rd.modules_total ? 'chip-ok' : 'chip-warn'}`}>Вычитка · {rd.modules_accepted} из {rd.modules_total} модулей</span>
              <span className="chip chip-blue">{STATUS_LABEL[doc.status]}</span>
            </div>
          </div>
        </section>
        <section className="card card-pad">
          <h3 className="h3">Решения людей</h3>
          {people.length === 0 && <p className="small muted">Решений пока нет.</p>}
          {people.map((a: any, i: number) => (
            <div key={i} className="row small" style={{ padding: '6px 0', borderBottom: '1px solid var(--line)' }}>
              {a.decision === 'approve' ? <CheckCircle2 size={16} color="var(--accent)" /> : <RotateCcw size={16} color="var(--amber)" />}
              <span className="grow">{a.stage === 'module' ? `Модуль ${a.module_id}` : a.stage === 'skeleton' ? 'Каркас' : 'Программа'} — {a.decision === 'approve' ? 'принят' : 'возвращён'}{a.comment ? `: ${a.comment}` : ''}</span>
              <span className="tiny muted">{a.actor}</span>
            </div>
          ))}
          {rd.open?.length > 0 && <div className="callout warn small">Открыто: {rd.open.map((o: any) => o.title).join('; ')}</div>}
        </section>
        <section className="card card-pad">
          <h3 className="h3">Качество комплекта</h3>
          <div className="grid-2">
            <div className="param"><span className="k">Часы</span><span className="v">{tot} из {doc.volume_h}</span></div>
            <div className="param"><span className="k">Блокирующие проверки</span><span className="v">{rep.blocking_passed} из {rep.blocking_total}</span></div>
            <div className="param"><span className="k">РО с ≥ 2 средствами</span><span className="v">{covered} из {rep.coverage?.length || 0}</span></div>
            <div className="param"><span className="k">Источники без подтверждения</span><span className="v">{(doc.sources || []).filter((s: any) => !s.confirmed).length}</span></div>
          </div>
        </section>
      </div>
      <aside className="col col-16">
        <section className="card card-pad">
          <h3 className="h3">Срок и затраты</h3>
          <div className="param"><span className="k">Каркас</span><span className="v">{Math.round(doc.timing_s?.skeleton || 0)} с</span></div>
          <div className="param"><span className="k">Комплект</span><span className="v">{Math.round(doc.timing_s?.kit || 0)} с</span></div>
          <div className="param"><span className="k">Модель</span><span className="v">{(doc.usage?.cost_rub || 0).toFixed(2)} ₽ · {doc.usage?.calls} вызовов</span></div>
          <div className="param"><span className="k">Токены</span><span className="v">{(doc.usage?.tokens_in || 0) + (doc.usage?.tokens_out || 0)}</span></div>
        </section>
        <section className="card card-pad">
          <h3 className="h3">Заполняется при подписании</h3>
          <div className="small muted">№ и дата приказа: ____<br />ФИО преподавателей: ____<br />Подписи: ____</div>
          <p className="tiny muted">Агент их не заполняет: финальный документ выпускают люди.</p>
          {doc.status === 'on_approval' ? (
            <>
              <textarea className="field" style={{ minHeight: 70 }} placeholder="Что исправить (для возврата)" value={comment} onChange={(e) => setComment(e.target.value)} />
              <div style={{ display: 'grid', gap: 8, marginTop: 10 }}>
                <button className="btn btn-primary" style={{ justifyContent: 'center' }} disabled={!!busy || (rd.index || 0) < 100} onClick={() => decide('approve')}>{busy === 'approve' ? <Spinner /> : <><Check size={16} /> Утвердить и подготовить проект приказа</>}</button>
                <button className="btn btn-ghost" style={{ justifyContent: 'center' }} disabled={!!busy || !comment.trim()} onClick={() => decide('return')}><Undo2 size={16} /> Вернуть с комментарием</button>
              </div>
            </>
          ) : doc.status === 'approved' ? (
            <div className="callout small">Программа утверждена. Проект приказа и программа .docx переданы методисту для регистрации.</div>
          ) : <p className="small muted">Программа ещё не отправлена на утверждение.</p>}
        </section>
        <section className="card card-pad"><h3 className="h3">Документы</h3><ExportBlock doc={doc} /></section>
      </aside>
    </div>
    <ToolsPanel doc={doc} only={['text', 'versions', 'actual']} />
    </div>
  )
}

/* ---------------- Вычитка эксперта ---------------- */
function ExpertView({ doc, reload }: { doc: Doc; reload: () => void }) {
  const toast = useToast()
  const [mid, setMid] = useState(doc.modules[0]?.id)
  const [text, setText] = useState('')
  const [node, setNode] = useState('')
  const [busy, setBusy] = useState('')
  useEffect(() => { if (!doc.modules.find((m: any) => m.id === mid)) setMid(doc.modules[0]?.id) }, [doc.modules, mid])
  const m = doc.modules.find((x: any) => x.id === mid)
  if (!doc.modules.length) return <div className="card empty"><Users size={34} /><p>В этой программе вам пока не назначено ни одного модуля.</p></div>

  async function decision(d: 'accept' | 'return') {
    setBusy(d)
    try {
      await api(`/programs/${doc.id}/reviews/decision`, { method: 'POST', json: { module_id: mid, decision: d, comment: text } })
      toast(d === 'accept' ? 'Модуль принят' : 'Модуль возвращён методисту'); setText(''); reload()
    } catch (e: any) { toast(e.message, true) } finally { setBusy('') }
  }
  async function ask(agent: boolean) {
    setBusy('ask')
    try {
      await api(`/programs/${doc.id}/comments`, { method: 'POST', json: { module_id: mid, text, node_id: node, ask_agent: agent } })
      toast(agent ? 'Вопрос передан, агент подготовил предложение для методиста' : 'Вопрос отправлен методисту'); setText(''); reload()
    } catch (e: any) { toast(e.message, true) } finally { setBusy('') }
  }
  const nodes = [...(doc.kit?.tasks || []), ...(doc.kit?.questions || [])].filter((x: any) => x.module_id === mid)
  return (
    <div className="grid-main">
      <section className="card card-pad">
        <div className="row row-wrap">
          <h2 className="h2 grow" style={{ margin: 0 }}>Вычитка: модуль {m?.n}. {m?.title}</h2>
          {doc.modules.length > 1 && <select className="field" style={{ width: 'auto' }} value={mid} onChange={(e) => setMid(e.target.value)}>{doc.modules.map((x: any) => <option key={x.id} value={x.id}>Модуль {x.n}</option>)}</select>}
          <span className={`chip ${REVIEW_LABEL[m?.review_status]?.[1] || ''}`}>{REVIEW_LABEL[m?.review_status]?.[0]}</span>
        </div>
        <p className="small muted">Вы видите только назначенные вам модули. Код в лекциях уже выполнен в песочнице, вопросы привязаны к результатам обучения.</p>
        {m && <ModuleContent doc={doc} module={m} />}
      </section>
      <aside className="col col-16">
        <section className="card card-pad">
          <h3 className="h3">Ваше решение</h3>
          <label className="label">К какому элементу (необязательно)</label>
          <select className="field" value={node} onChange={(e) => setNode(e.target.value)}>
            <option value="">Модуль целиком</option>
            {nodes.map((x: any) => <option key={x.id} value={x.id}>{x.title || x.stem?.slice(0, 60)}</option>)}
          </select>
          <textarea className="field" style={{ minHeight: 90, marginTop: 10 }} placeholder="Замечание или вопрос" value={text} onChange={(e) => setText(e.target.value)} />
          <div style={{ display: 'grid', gap: 8, marginTop: 10 }}>
            <button className="btn btn-primary" style={{ justifyContent: 'center' }} disabled={!!busy} onClick={() => decision('accept')}>{busy === 'accept' ? <Spinner /> : <><Check size={16} /> Принять модуль</>}</button>
            <button className="btn btn-soft" style={{ justifyContent: 'center' }} disabled={!!busy || !text.trim()} onClick={() => ask(true)}><Sparkles size={16} /> Попросить агента о правке</button>
            <button className="btn btn-ghost" style={{ justifyContent: 'center' }} disabled={!!busy || !text.trim()} onClick={() => ask(false)}><MessageSquare size={16} /> Задать вопрос методисту</button>
            <button className="btn btn-danger" style={{ justifyContent: 'center' }} disabled={!!busy || !text.trim()} onClick={() => decision('return')}><X size={16} /> Вернуть с комментарием</button>
          </div>
        </section>
        <section className="card card-pad">
          <h3 className="h3">Мои вопросы</h3>
          {(doc.comments || []).filter((c: any) => c.module_id === mid).map((c: any) => (
            <div key={c.id} className="small" style={{ padding: '8px 0', borderBottom: '1px solid var(--line)' }}>
              «{c.text}» <span className={`chip ${c.status === 'open' ? 'chip-warn' : 'chip-ok'}`}>{c.status === 'open' ? 'ждёт ответа' : c.status === 'applied' ? 'правка внесена' : 'отвечено'}</span>
              {c.answer && <div className="muted">Ответ: {c.answer}</div>}
            </div>
          ))}
        </section>
      </aside>
    </div>
  )
}
