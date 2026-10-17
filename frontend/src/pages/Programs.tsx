import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ArrowRight, FileText, Paperclip, Plus, RefreshCw, Sparkles, Upload, X } from 'lucide-react'
import { api, getSession, STATUS_LABEL } from '../api'
import { Spinner, useToast } from '../components/ui'
import { FindingsList } from './ProgramTools'

export const EXAMPLES = [
  { t: 'Python для школьников · 16 ч', q: 'Нужна дополнительная общеразвивающая программа «Первые шаги в Python» для школьников 8 и 9 классов без опыта программирования. Объем 16 часов, занятия очно по 2 часа два раза в неделю. Практики должно быть не меньше половины всех часов. В конце каждый ученик защищает небольшой проект, например простую игру или чат-бота. Нужны итоговый тест на 10 вопросов и слайды для первых двух занятий.' },
  { t: 'ИИ в работе учителя · 36 ч', q: 'Программа повышения квалификации «Искусственный интеллект в работе учителя» для учителей школ Ингушетии, 36 часов, очно-заочно с применением дистанционных технологий. Учителя должны научиться готовить с помощью нейросетей планы уроков, задания и проверочные работы, а также понимать риски и правила безопасного использования ИИ в работе с детьми. Итоговая аттестация в форме зачёта по портфолио из трёх материалов, созданных с помощью ИИ. Использовать только сервисы, которые доступны в России.' },
  { t: 'Анализ данных на Python · 72 ч', q: 'Нужна программа повышения квалификации на 72 часа «Анализ данных на Python» для сотрудников региональных отделений банков, которые сейчас работают в Excel. Формат очно-заочный, срок 4 недели. Основные темы это pandas, визуализация, SQL для выгрузки данных и основы статистики. Итоговая аттестация в виде защиты проекта на обезличенных банковских данных. Слайды нужны для модуля про pandas.' },
  { t: 'Кибербезопасность · неполный', q: 'Сделайте курс по кибербезопасности для студентов колледжа, примерно на месяц, чтобы после него ребята могли пойти работать в эту сферу.' },
  { t: 'DevOps-стажировка · 256 ч', q: 'Нужна программа повышения квалификации в форме стажировки «DevOps-инженер от Linux до CI/CD» на 256 часов. Слушатели проходят стажировку в ИТ-компаниях региона, вся работа самостоятельная под руководством наставника от компании, аудиторных занятий нет. Итоговая аттестация занимает 2 часа и проходит в форме защиты отчёта о стажировке. Срок около двух месяцев, не больше 4 часов в день.' },
]

const STATUS_CHIP: Record<string, string> = { approved: 'chip-ok', kit_ready: 'chip-ok', on_approval: 'chip-blue', on_review: 'chip-blue', questions: 'chip-warn', returned: 'chip-warn', failed: 'chip-err' }

export default function Programs() {
  const [list, setList] = useState<any[] | null>(null)
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [norm, setNorm] = useState<'gos' | 'org'>('gos')
  const [busy, setBusy] = useState(false)
  const [over, setOver] = useState(false)
  const input = useRef<HTMLInputElement>(null)
  const nav = useNavigate()
  const toast = useToast()
  const role = getSession()?.user.role
  const [filter, setFilter] = useState(role === 'head' ? 'on_approval,approved' : '')
  const [since, setSince] = useState('')
  const [until, setUntil] = useState('')

  useEffect(() => {
    const q = new URLSearchParams()
    if (filter) q.set('status', filter)
    if (since) q.set('since', since)
    if (until) q.set('until', until)
    setList(null)
    api(`/programs${q.toString() ? `?${q}` : ''}`).then(setList).catch((e) => { setList([]); toast(e.message, true) })
  }, [toast, filter, since, until])

  async function create() {
    if (text.trim().length < 5) return toast('Опишите программу хотя бы в одном предложении', true)
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('text', text)
      fd.append('norm_mode', norm)
      files.forEach((f) => fd.append('files', f))
      const r = await api('/programs/upload', { method: 'POST', body: fd })
      if (r.job_id) sessionStorage.setItem(`ma.job.${r.program_id}`, r.job_id)
      nav(`/app/p/${r.program_id}`)
    } catch (e: any) {
      toast(e.message, true)
    } finally {
      setBusy(false)
    }
  }

  const addFiles = (fl: FileList | null) => {
    if (!fl) return
    setFiles((x) => [...x, ...Array.from(fl)].slice(0, 5))
  }

  return (
    <div className="grid-main">
      <div>
        {role === 'methodist' && (
          <section className="card card-pad" style={{ marginBottom: 20, position: 'relative', overflow: 'hidden' }}>
            <div style={{ position: 'absolute', right: -80, top: -80, width: 260, height: 260, borderRadius: '50%', background: 'radial-gradient(circle, rgba(33,160,56,.18), transparent 65%)', pointerEvents: 'none' }} />
            <div className="row" style={{ marginBottom: 6 }}>
              <span className="avatar av-agent"><Sparkles size={15} /></span>
              <h1 className="h2" style={{ margin: 0 }}>Новая программа</h1>
            </div>
            <p className="muted" style={{ marginTop: 4 }}>Опишите программу своими словами: для кого, сколько часов, в каком формате, чем завершается. Агент сам определит тип и шаблон АЦР.</p>
            <textarea className="field" value={text} onChange={(e) => setText(e.target.value)} placeholder="Например: программа повышения квалификации «Анализ данных на Python» на 72 часа для сотрудников банков, очно-заочно, 4 недели, итог — защита проекта" />
            <div className="row row-wrap" style={{ gap: 8, marginTop: 10 }}>
              <span className="small muted">Примеры кейса:</span>
              {EXAMPLES.map((e) => <button key={e.t} className="chip" style={{ cursor: 'pointer' }} onClick={() => setText(e.q)}>{e.t}</button>)}
            </div>
            <div className={`drop ${over ? 'over' : ''}`} style={{ marginTop: 14 }} onClick={() => input.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); addFiles(e.dataTransfer.files) }}>
              <Upload size={18} style={{ verticalAlign: -4 }} /> Перетащите шаблон или прошлую программу (.docx, .pdf, .txt), до 5 файлов по 20 МБ
              <input ref={input} type="file" hidden multiple accept=".docx,.pdf,.txt" onChange={(e) => addFiles(e.target.files)} />
            </div>
            {files.length > 0 && (
              <div className="row row-wrap" style={{ gap: 8, marginTop: 10 }}>
                {files.map((f, i) => (
                  <span key={i} className="chip chip-blue"><Paperclip size={13} />{f.name} · {Math.ceil(f.size / 1024)} КБ
                    <X size={13} style={{ cursor: 'pointer' }} onClick={() => setFiles((x) => x.filter((_, j) => j !== i))} /></span>
                ))}
              </div>
            )}
            <div className="row row-wrap" style={{ marginTop: 16 }}>
              <div className="roles">
                <button className={`role-pill ${norm === 'gos' ? 'active' : ''}`} style={{ paddingLeft: 12 }} onClick={() => setNorm('gos')}>Госстандарты</button>
                <button className={`role-pill ${norm === 'org' ? 'active' : ''}`} style={{ paddingLeft: 12 }} onClick={() => setNorm('org')}>Документы организации</button>
              </div>
              <div className="grow" />
              <button className="btn btn-primary btn-lg" onClick={create} disabled={busy}>{busy ? <><Spinner /> Разбираю запрос</> : <>Отправить агенту <ArrowRight size={18} /></>}</button>
            </div>
          </section>
        )}

        <section>
          <div className="row" style={{ marginBottom: 12 }}>
            <h2 className="h2" style={{ margin: 0 }}>{role === 'head' ? 'Программы организации' : 'Мои программы'}</h2>
            <span className="chip">{list?.length ?? 0}</span>
          </div>
          <div className="filters">
            {[['', 'Все'], ['on_approval', 'На утверждении'], ['approved', 'Утверждённые'], ['on_approval,approved', 'Оба статуса'], ['kit_ready', 'Комплект готов']].map(([v, l]) => (
              <button key={v} className={`chip ${filter === v ? 'chip-ok' : ''}`} style={{ cursor: 'pointer' }} onClick={() => setFilter(v)}>{l}</button>
            ))}
            <span className="grow" />
            <span className="tiny muted">за период</span>
            <input type="date" className="field" style={{ width: 'auto', padding: '6px 10px' }} value={since} onChange={(e) => setSince(e.target.value)} aria-label="С даты" />
            <input type="date" className="field" style={{ width: 'auto', padding: '6px 10px' }} value={until} onChange={(e) => setUntil(e.target.value)} aria-label="По дату" />
          </div>
          {list === null && <div style={{ display: 'grid', gap: 10 }}>{[0, 1, 2].map((i) => <div key={i} className="skeleton" style={{ height: 74 }} />)}</div>}
          {list && list.length === 0 && (
            <div className="card empty"><FileText size={34} /><p>Программ пока нет. {role === 'methodist' ? 'Опишите первую в форме выше.' : 'Методист ещё не создал ни одной.'}</p></div>
          )}
          <div className="stagger" style={{ display: 'grid', gap: 10 }}>
            {list?.map((p) => (
              <Link key={p.id} to={`/app/p/${p.id}`} className="card card-pad card-hover row" style={{ padding: 16 }}>
                <span className="glass-icon" style={{ background: 'var(--accent-soft)', color: 'var(--accent)', borderColor: 'transparent', width: 42, height: 42 }}><FileText size={19} /></span>
                <div className="grow">
                  <b>{p.title || 'Программа без названия'}</b>
                  <div className="tiny muted">{p.template ? `${p.template} · ` : ''}{p.volume_h ? `${p.volume_h} ч · ` : ''}версия {p.version} · обновлена {(p.updated_at || '').slice(0, 16).replace('T', ' ')}{p.blocking != null ? ` · проверки ${p.blocking}/10` : ''}</div>
                </div>
                <span className={`chip ${STATUS_CHIP[p.status] || ''}`}>{STATUS_LABEL[p.status] || p.status}</span>
                <ArrowRight size={18} className="muted" />
              </Link>
            ))}
          </div>
        </section>
      </div>

      <aside className="col col-16">
        <div className="card card-pad">
          <h3 className="h3">Как это работает</h3>
          <div className="timeline small">
            {['Запрос и вложения', 'До 5 уточняющих вопросов', 'Каркас с часами за 3 минуты', 'Проверка и ваше утверждение', 'Комплект и отчёт проверки', 'Вычитка и утверждение'].map((s, i) => (
              <div key={s} className={`tl-item ${i === 0 ? 'now' : ''}`}>{i + 1}. {s}</div>
            ))}
          </div>
          <Link to="/help" className="btn btn-ghost btn-sm" style={{ marginTop: 6 }}><Plus size={14} /> Подробнее в справке</Link>
        </div>
        {role === 'methodist' && <ActualizeCard />}
        <div className="card card-pad" style={{ background: 'linear-gradient(135deg, var(--accent-soft), var(--blue-soft))', border: 0 }}>
          <h3 className="h3">Гарантии</h3>
          <ul className="small" style={{ margin: 0, paddingLeft: 18, lineHeight: 1.7, color: 'var(--ink-2)' }}>
            <li>Часы сходятся на всех уровнях</li>
            <li>Каждый РО проверяется ≥ 2 средствами</li>
            <li>ПС и НПА только из реестра</li>
            <li>Реквизиты и подписи — за людьми</li>
          </ul>
        </div>
      </aside>
    </div>
  )
}

/* Актуализация старой программы из файла (FR-61) */
function ActualizeCard() {
  const toast = useToast()
  const input = useRef<HTMLInputElement>(null)
  const [busy, setBusy] = useState(false)
  const [res, setRes] = useState<any>(null)
  async function run(f: File | undefined) {
    if (!f) return
    setBusy(true)
    try {
      const fd = new FormData()
      fd.append('file', f)
      setRes(await api('/actualize', { method: 'POST', body: fd }))
    } catch (e: any) { toast(e.message, true) } finally { setBusy(false) }
  }
  return (
    <div className="card card-pad">
      <h3 className="h3"><RefreshCw size={16} style={{ verticalAlign: -3 }} /> Актуализация старой программы</h3>
      <p className="small muted" style={{ marginTop: 0 }}>Загрузите прошлую программу: агент найдёт устаревшие инструменты, версии, сервисы и источники по реестру 2026 года и предложит замену.</p>
      <div className="kb-drop" onClick={() => input.current?.click()}>{busy ? <Spinner /> : <Upload size={16} style={{ verticalAlign: -3 }} />} Выбрать .docx, .pdf или .txt</div>
      <input ref={input} type="file" hidden accept=".docx,.pdf,.txt" onChange={(e) => run(e.target.files?.[0])} />
      {res && (
        <div style={{ marginTop: 12 }}>
          <div className="tiny muted" style={{ marginBottom: 8 }}>{res.name} · {Math.round(res.chars / 1000)} тыс. знаков · находок {res.total}</div>
          <FindingsList items={res.findings} />
        </div>
      )}
    </div>
  )
}
