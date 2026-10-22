import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Archive, ArrowRight, FileText, ListChecks, Paperclip, Plus, RefreshCw, Sparkles, Upload, X } from 'lucide-react'
import { api, getSession, STATUS_LABEL } from '../api'
import { Spinner, useToast } from '../components/ui'
import {
  buildRequestParams, EMPTY_REQUEST_FORM, FORM_ONLY_REQUEST, hasRequestParams,
  REQUEST_FORM_FINAL_OPTIONS, REQUEST_FORM_FORM_OPTIONS,
  REQUEST_FORM_TYPE_LABEL, VOLUME_PRESETS, type RequestFormFields, ARCHIVE_FILTER, canArchive, programsQuery,
} from '../kit'
import { FindingsList } from './ProgramTools'
import { FILE_ACCEPT, fileError, MAX_FILES } from '../validate'

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
  const [form, setForm] = useState<RequestFormFields>({ ...EMPTY_REQUEST_FORM })
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
  const [reloadKey, setReloadKey] = useState(0)
  const setField = (k: keyof RequestFormFields, v: string | number) => setForm((f) => ({ ...f, [k]: v }) as RequestFormFields)

  useEffect(() => {
    setList(null)
    api(`/programs${programsQuery(filter, since, until)}`).then(setList).catch((e) => { setList([]); toast(e.message, true) })
  }, [toast, filter, since, until, reloadKey])

  // SPEC-UI-34: убрать в архив прямо из строки списка (только методист)
  async function archive(e: React.MouseEvent, id: string) {
    e.preventDefault()
    e.stopPropagation()
    if (!confirm('Убрать программу в архив? Её можно вернуть из фильтра «Архив».')) return
    try {
      await api(`/programs/${id}/archive`, { method: 'POST' })
      toast('Программа убрана в архив')
      setReloadKey((k) => k + 1)
    } catch (err: any) { toast(err.message, true) }
  }

  /** Файл → вложение JSON-запроса: имя и base64 без префикса data: (бэкенд валидирует размер до декодирования). */
  function fileToAttachment(f: File): Promise<{ name: string; content_base64: string }> {
    return new Promise((resolve, reject) => {
      const r = new FileReader()
      r.onerror = () => reject(new Error(`Не удалось прочитать файл «${f.name}»`))
      r.onload = () => resolve({ name: f.name, content_base64: String(r.result).split(',')[1] || '' })
      r.readAsDataURL(f)
    })
  }

  async function create() {
    const params = buildRequestParams(form)
    const structured = hasRequestParams(params)
    const body = text.trim()
    // R09/MET-53: заполненные поля формы уходят структурой params в POST /programs —
    // бэкенд применяет их приоритетно над разбором текста и фиксирует расхождения в assumptions.
    // Свободный текст при этом не трогаем: без префикса, как написал методист.
    const request = structured && !body ? FORM_ONLY_REQUEST : body
    if (request.length < 5) return toast('Опишите программу хотя бы в одном предложении или заполните поля формы', true)
    setBusy(true)
    try {
      let r: any
      if (structured) {
        r = await api('/programs', {
          method: 'POST',
          json: { request, norm_mode: norm, params, attachments: await Promise.all(files.map(fileToAttachment)) },
        })
      } else {
        const fd = new FormData()
        fd.append('text', request)
        fd.append('norm_mode', norm)
        files.forEach((f) => fd.append('files', f))
        r = await api('/programs/upload', { method: 'POST', body: fd })
      }
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
    const picked = Array.from(fl)
    const bad = picked.map(fileError).filter(Boolean) as string[]
    const ok = picked.filter((f) => !fileError(f))
    const next = [...files, ...ok]
    if (next.length > MAX_FILES) bad.push(`Не больше ${MAX_FILES} файлов: не добавлены ${next.slice(MAX_FILES).map((f) => f.name).join(', ')}`)
    if (bad.length) toast(bad.join('; '), true)
    setFiles(next.slice(0, MAX_FILES))
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
            <RequestForm form={form} setField={setField} />
            <textarea className="field" value={text} onChange={(e) => setText(e.target.value)} placeholder="Например: программа повышения квалификации «Анализ данных на Python» на 72 часа для сотрудников банков, очно-заочно, 4 недели, итог — защита проекта" />
            <div className="row row-wrap" style={{ gap: 8, marginTop: 10 }}>
              <span className="small muted">Примеры кейса:</span>
              {EXAMPLES.map((e) => <button key={e.t} className="chip" style={{ cursor: 'pointer' }} onClick={() => { setText(e.q); setForm({ ...EMPTY_REQUEST_FORM }) }}>{e.t}</button>)}
            </div>
            <div className={`drop ${over ? 'over' : ''}`} style={{ marginTop: 14 }} onClick={() => input.current?.click()}
              onDragOver={(e) => { e.preventDefault(); setOver(true) }} onDragLeave={() => setOver(false)}
              onDrop={(e) => { e.preventDefault(); setOver(false); addFiles(e.dataTransfer.files) }}>
              <Upload size={18} style={{ verticalAlign: -4 }} /> Перетащите шаблон или прошлую программу (.docx, .pdf, .txt), до 5 файлов по 20 МБ
              <input ref={input} type="file" hidden multiple accept={FILE_ACCEPT} onChange={(e) => { addFiles(e.target.files); e.target.value = '' }} />
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
            {[['', 'Все'], ['on_approval', 'На утверждении'], ['approved', 'Утверждённые'], ['on_approval,approved', 'Оба статуса'], ['kit_ready', 'Комплект готов'],
              ...(role === 'methodist' ? [[ARCHIVE_FILTER, 'Архив']] : [])].map(([v, l]) => (
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
                {p.archived_at && <span className="chip chip-warn"><Archive size={13} /> В архиве</span>}
                {canArchive(role, p.status, p.archived_at) && (
                  <button className="icon-btn" title="Убрать в архив" aria-label="Убрать в архив" onClick={(e) => archive(e, p.id)}><Archive size={16} /></button>
                )}
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

/* Панель «Известные параметры» над свободным текстом: 8 необязательных полей (MET-15).
 * Заполненное уходит в POST /programs структурой params (R09/MET-53) — приоритетнее разбора текста,
 * пустое агент уточнит вопросами. */
function RequestForm({ form, setField }: { form: RequestFormFields; setField: (k: keyof RequestFormFields, v: string | number) => void }) {
  return (
    <details style={{ margin: '10px 0', border: '1px solid var(--line)', borderRadius: 14, padding: '10px 14px', background: 'var(--bg-2)' }}>
      <summary className="small" style={{ cursor: 'pointer', fontWeight: 700, userSelect: 'none' }}>
        <ListChecks size={15} style={{ verticalAlign: -3 }} /> Известные параметры — необязательно
      </summary>
      <p className="tiny muted" style={{ margin: '8px 0 12px' }}>
        Заполненные поля уйдут агенту структурированно и будут главнее текста запроса: если текст и поля расходятся, агент примет значение поля и отметит это в допущениях. Пустые оставьте — агент спросит или предложит сам.
      </p>
      <div className="grid-2" style={{ gap: 10 }}>
        <label className="label">Тема / название
          <input className="field" value={form.title} placeholder="Например: Анализ данных на Python" onChange={(e) => setField('title', e.target.value)} />
        </label>
        <label className="label">Тип программы
          <select className="field" value={form.program_type} onChange={(e) => setField('program_type', e.target.value)}>
            {Object.entries(REQUEST_FORM_TYPE_LABEL).map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
        </label>
        <label className="label">Для кого (аудитория)
          <input className="field" value={form.audience} placeholder="Например: учителя школ" onChange={(e) => setField('audience', e.target.value)} />
        </label>
        <label className="label">Что слушатели уже знают
          <input className="field" value={form.entry_level} placeholder="Например: работают в Excel" onChange={(e) => setField('entry_level', e.target.value)} />
        </label>
        <label className="label">Объём, ак. ч
          <span className="row row-wrap" style={{ gap: 6 }}>
            <input className="field" type="number" min={1} max={2000} style={{ width: 90 }} aria-label="Объём, ак. ч" value={form.volume_h}
              onChange={(e) => setField('volume_h', e.target.value ? Number(e.target.value) : '')} />
            {VOLUME_PRESETS.map((v) => (
              <button key={v} type="button" className={`chip ${form.volume_h === v ? 'chip-ok' : ''}`} style={{ cursor: 'pointer' }}
                onClick={() => setField('volume_h', form.volume_h === v ? '' : v)}>{v}</button>
            ))}
          </span>
        </label>
        <label className="label">Форма обучения
          <select className="field" value={form.form} onChange={(e) => setField('form', e.target.value)}>
            <option value="">Предложит агент</option>
            {REQUEST_FORM_FORM_OPTIONS.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
        <label className="label">Срок · примерный, агент уточнит график
          <span className="row" style={{ gap: 6 }}>
            <input className="field" type="number" min={1} style={{ width: 80 }} aria-label="Срок, число" value={form.duration_value}
              onChange={(e) => setField('duration_value', e.target.value ? Number(e.target.value) : '')} />
            <select className="field" style={{ width: 'auto' }} aria-label="Единица срока" value={form.duration_unit} onChange={(e) => setField('duration_unit', e.target.value)}>
              <option value="weeks">недель</option>
              <option value="months">месяцев</option>
            </select>
          </span>
        </label>
        <label className="label">Итоговая аттестация
          <select className="field" value={form.final_assessment} onChange={(e) => setField('final_assessment', e.target.value)}>
            <option value="">Предложит агент</option>
            {REQUEST_FORM_FINAL_OPTIONS.map((v) => <option key={v} value={v}>{v}</option>)}
          </select>
        </label>
      </div>
    </details>
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
    const err = fileError(f)
    if (err) { toast(err, true); return }
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
      <input ref={input} type="file" hidden accept={FILE_ACCEPT} onChange={(e) => { run(e.target.files?.[0]); e.target.value = '' }} />
      {res && (
        <div style={{ marginTop: 12 }}>
          <div className="tiny muted" style={{ marginBottom: 8 }}>{res.name} · {Math.round(res.chars / 1000)} тыс. знаков · находок {res.total}</div>
          <FindingsList items={res.findings} />
        </div>
      )}
    </div>
  )
}
