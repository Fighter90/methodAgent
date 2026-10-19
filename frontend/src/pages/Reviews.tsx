import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ArrowRight, ClipboardCheck } from 'lucide-react'
import { api, getSession } from '../api'
import { useToast } from '../components/ui'

export const REVIEW_LABEL: Record<string, [string, string]> = {
  not_started: ['Не начата', ''],
  in_review: ['На вычитке', 'chip-blue'],
  question: ['Есть вопрос', 'chip-warn'],
  returned: ['Возвращён', 'chip-err'],
  accepted: ['Принят', 'chip-ok'],
}

export default function Reviews() {
  const [items, setItems] = useState<any[] | null>(null)
  const toast = useToast()
  const user = getSession()?.user

  useEffect(() => {
    if (user?.role !== 'expert') { setItems([]); return }
    api('/reviews').then(setItems).catch((e) => { setItems([]); toast(e.message, true) })
  }, [user?.id, user?.role, toast])

  return (
    <div>
      <h1 className="h1">Вычитка модулей</h1>
      <p className="muted">Здесь модули, которые методист назначил вам. Вы видите только их: лекции, тесты, задания и пометки агента.</p>
      {items === null && <div className="skeleton" style={{ height: 120 }} />}
      {items && items.length === 0 && (
        <div className="card empty"><ClipboardCheck size={34} /><p>Назначенных модулей пока нет.{user?.role !== 'expert' && ' Раздел доступен эксперту.'}</p></div>
      )}
      <div className="stagger" style={{ display: 'grid', gap: 10 }}>
        {items?.map((m) => (
          <Link key={`${m.program_id}-${m.module_id}`} to={`/app/p/${m.program_id}`} className="card card-pad card-hover row" style={{ padding: 16 }}>
            <span className="avatar av-expert" style={{ width: 40, height: 40 }}>{m.n}</span>
            <div className="grow">
              <b>Модуль {m.n}. {m.title}</b>
              <div className="tiny muted">{m.program} · {m.hours} ч</div>
            </div>
            <span className={`chip ${REVIEW_LABEL[m.status]?.[1] || ''}`}>{REVIEW_LABEL[m.status]?.[0] || m.status}</span>
            <ArrowRight size={18} className="muted" />
          </Link>
        ))}
      </div>
    </div>
  )
}
