import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  ArrowRight, BookOpenCheck, Calculator, FileDown, GitBranch, LifeBuoy, Menu, Network, ShieldCheck, Sparkles, Users, Wand2, Workflow, X,
} from 'lucide-react'
import { CountUp, Logo, Reveal, spotlight, useMouseParallax, useScrollY } from '../components/ui'

const FEATURES = [
  { icon: Calculator, title: 'Часы сходятся всегда', text: 'Модель предлагает структуру, а часы по модулям, темам и видам работы раскладывает детерминированный солвер. Итог с аттестацией равен запрошенному объёму до часа.', cls: 'wide' },
  { icon: ShieldCheck, title: '27 правил проверки', text: '10 блокирующих проверок: арифметика часов, шаблон, календарь, покрытие результатов, реестры ПС и НПА.' },
  { icon: Network, title: 'Граф связей', text: 'Компетенция → индикатор → РО → тема → вопрос и задание. Каждый результат проверяется минимум двумя средствами.' },
  { icon: GitBranch, title: 'Точечная правка', text: 'Меняете тему — агент пересобирает только её потомков и заново проходит проверку. Остальной комплект не трогается.', cls: 'half' },
  { icon: FileDown, title: 'Выгрузка в один клик', text: 'Программа .docx по шаблону АЦР, слайды .pptx, тесты Moodle XML и GIFT, JSON и проект приказа.', cls: 'half' },
  { icon: BookOpenCheck, title: 'Только проверенные источники', text: 'Профстандарты с кодами ТФ, НПА и литература из реестра. Всё остальное получает пометку «не подтверждено».' },
  { icon: Users, title: 'Три роли, одно место', text: 'Методист собирает, эксперт вычитывает свои модули, руководитель утверждает. Реквизиты заполняют люди.' },
  { icon: Wand2, title: 'Вопросы без жаргона', text: 'Если сведений не хватает, агент задаёт до пяти понятных вопросов с вариантами ответа, а не додумывает.' },
]

const FLOW = [
  ['01', 'Запрос', 'Свободный текст и референсы. Агент распознаёт тип, объём, аудиторию и форму.'],
  ['02', 'Вопросы', 'До пяти вопросов только по пустым обязательным полям, с вариантами.'],
  ['03', 'Каркас', 'Цель, компетенции З/У/Н, профстандарт, модули и темы с часами — до 3 минут.'],
  ['04', 'Проверка', 'Правила, матрица покрытия и решения методиста по пунктам «!».'],
  ['05', 'Комплект', 'Программы модулей, тесты, задания, лекции и слайды параллельно по модулям.'],
  ['06', 'Согласование', 'Эксперты принимают модули, руководитель утверждает программу.'],
]

const FORMATS = ['ДПП ПК', 'Стажировка', 'ДООП', '273-ФЗ', 'Приказ № 266', 'Приказ № 629', 'Профстандарты', '.docx', '.pptx', 'Moodle XML', 'GIFT', 'JSON', 'GigaChat 3 Pro', 'Cloud.ru']

export default function Landing() {
  const m = useMouseParallax(1)
  const y = useScrollY()
  const [glow, setGlow] = useState({ x: -999, y: -999 })
  const [menu, setMenu] = useState(false)
  useEffect(() => {
    const on = (e: MouseEvent) => setGlow({ x: e.clientX, y: e.clientY })
    window.addEventListener('mousemove', on)
    document.documentElement.setAttribute('data-theme', 'dark')
    return () => {
      window.removeEventListener('mousemove', on)
      try { document.documentElement.setAttribute('data-theme', localStorage.getItem('ma.theme') || 'light') } catch { /* ignore */ }
    }
  }, [])
  const layer = (depth: number, extraY = 0) => ({ transform: `translate3d(${m.x * depth}px, ${m.y * depth + y * extraY}px, 0)` })
  const tilt = { transform: `rotateY(${m.x * 10}deg) rotateX(${-m.y * 8}deg)` }

  return (
    <div className="night">
      <div className="cursor-glow" style={{ left: glow.x, top: glow.y }} />
      <nav className={`night-nav ${y > 20 ? 'scrolled' : ''}`}>
        <Logo light />
        <div className="grow" />
        <div className={`nn-links ${menu ? 'open' : ''}`} onClick={() => setMenu(false)}>
          <a className="nl" href="#features">Возможности</a>
          <a className="nl" href="#flow">Как работает</a>
          <a className="nl" href="#roles">Роли</a>
          <Link className="nl" to="/help">Справка</Link>
        </div>
        <Link className="btn btn-glass btn-sm nn-login" to="/auth">Войти</Link>
        <button className="nn-burger" aria-label={menu ? 'Закрыть меню' : 'Открыть меню'} aria-expanded={menu} onClick={() => setMenu((x) => !x)}>{menu ? <X size={20} /> : <Menu size={20} />}</button>
      </nav>

      <header className="hero">
        <div className="hero-bg">
          <div className="orb o1" style={layer(-60, 0.25)} />
          <div className="orb o2" style={layer(50, -0.15)} />
          <div className="orb o3" style={layer(-90, 0.1)} />
          <div className="grid-floor" style={{ transform: `translateY(${y * 0.3}px)` }} />
          <div className="noise" />
        </div>
        <div className="hero-inner">
          <div className="stagger" style={{ transform: `translateY(${y * -0.15}px)`, opacity: Math.max(0, 1 - y / 700) }}>
            <span className="eyebrow"><span className="dot" />Агент методиста · АЦР · GigaCowork · Cloud.ru</span>
            <h1 className="display">Программа обучения<br /><span className="grad-text">за день, а не за месяц</span></h1>
            <p className="lead">
              МетодАгент по запросу свободным текстом собирает программу повышения квалификации, стажировку или общеразвивающую программу по шаблону Академии цифрового развития. Вместе с ней он готовит полный комплект: компетенции, учебный план, тесты с ключами, задания семинаров, лекции и слайды. Перед выдачей комплект проходит автопроверку.
            </p>
            <div className="row row-wrap" style={{ marginTop: 30, gap: 14 }}>
              <Link to="/auth" className="btn btn-lg btn-glow">Попробовать <ArrowRight size={18} /></Link>
              <Link to="/help" className="btn btn-lg btn-glass"><LifeBuoy size={18} /> Как это работает</Link>
            </div>
            <div className="row row-wrap tiny" style={{ marginTop: 26, color: '#7d8792', gap: 18 }}>
              <span>✓ 16–500 академических часов</span><span>✓ Каркас до 3 минут</span><span>✓ 10 из 10 блокирующих проверок</span>
            </div>
          </div>

          <div className="hero-visual" style={{ ...tilt, transformStyle: 'preserve-3d' }}>
            <div className="float-card fc-plan" style={layer(-26, -0.08)}>
              <h5>Учебный план · 72 ч</h5>
              <div className="mini-row" style={{ color: '#7d8792' }}><span>Модуль</span><span>ЛК</span><span>ПР</span><span>СРС</span><span>Σ</span></div>
              {[['Основы Python для аналитика', 4, 6, 2, 12], ['pandas: обработка данных', 6, 9, 3, 18], ['Визуализация', 4, 6, 2, 12], ['SQL для выгрузки', 3, 5, 2, 10], ['Основы статистики', 4, 5, 3, 12], ['Итоговый проект', 0, 2, 2, 4]].map((r) => (
                <div className="mini-row" key={r[0] as string}><span>{r[0]}</span><span>{r[1]}</span><span>{r[2]}</span><span>{r[3]}</span><span>{r[4]}</span></div>
              ))}
              <div className="mini-row"><span>Итоговая аттестация</span><span></span><span></span><span></span><span>4</span></div>
              <div className="mini-row t"><span>Итого с аттестацией</span><span>21</span><span>33</span><span>14</span><span>72</span></div>
            </div>
            <div className="float-card fc-agent" style={{ ...layer(34, -0.18), animation: 'float 6s ease-in-out infinite' }}>
              <div className="row" style={{ gap: 10 }}>
                <span className="avatar av-agent"><Sparkles size={14} /></span>
                <div className="tiny" style={{ color: '#cfd6dd', lineHeight: 1.45 }}>Беру шаблон ДПП ПК и ПС 06.042 из реестра. Часы сходятся: 72 из 72.</div>
              </div>
            </div>
            <div className="float-card fc-check" style={layer(42, -0.22)}>
              <h5>Автопроверка</h5>
              {['Арифметика часов', 'Полнота шаблона', 'Календарь выполним', 'Покрытие РО ≥ 2', 'ПС и НПА из реестра'].map((t) => (
                <div className="mini-check" key={t}><i>✓</i>{t}</div>
              ))}
              <div style={{ marginTop: 10, fontWeight: 800, color: '#5DD879' }}>10 из 10 блокирующих</div>
            </div>
            <div className="float-card fc-test" style={layer(-38, -0.12)}>
              <h5>Тест · модуль 2 · РО 1.2</h5>
              <div className="tiny" style={{ color: '#e6eaee', marginBottom: 6 }}>Какой метод удалит дубликаты строк в DataFrame?</div>
              <div className="mini-opt">df.dropna()</div>
              <div className="mini-opt ok">df.drop_duplicates()</div>
              <div className="mini-opt">df.fillna(0)</div>
            </div>
          </div>
        </div>
        <div className="scroll-hint"><i />листайте</div>
      </header>

      <div className="marquee">
        <div className="marquee-track">
          {[...FORMATS, ...FORMATS].map((f, i) => <span key={i}><b>✦</b>{f}</span>)}
        </div>
      </div>

      <section className="section" id="features">
        <Reveal><span className="kicker">Возможности</span></Reveal>
        <Reveal delay={80}><h2 className="section-title">Всё, что методист собирает<br />неделями, — в одном агенте</h2></Reveal>
        <Reveal delay={160}><p className="lead">Агент не пишет программу одним промптом. Структура, содержание и проверка разнесены по 11 навыкам, а всё, что можно посчитать, считает код.</p></Reveal>
        <div className="bento">
          {FEATURES.map((f, i) => (
            <Reveal key={f.title} delay={i * 60} className={f.cls || ''}>
              <div className="glass" onMouseMove={spotlight} style={{ height: '100%' }}>
                <span className="glass-icon"><f.icon size={22} /></span>
                <h3>{f.title}</h3>
                <p>{f.text}</p>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      <section className="section" id="flow">
        <Reveal><span className="kicker">Как работает</span></Reveal>
        <Reveal delay={80}><h2 className="section-title">Шесть шагов от запроса<br />до утверждённой программы</h2></Reveal>
        <Reveal delay={160}><p className="lead">Человек утверждает цель, компетенции и часы до того, как агент начнёт писать содержание. Итоговое решение всегда остаётся за людьми.</p></Reveal>
        <div className="flow">
          {FLOW.map(([n, t, d], i) => (
            <Reveal key={n} delay={i * 90}>
              <div className="flow-step" style={{ height: '100%' }}>
                <span className="n">{n}</span>
                <h4>{t}</h4>
                <p>{d}</p>
              </div>
            </Reveal>
          ))}
        </div>
        <div className="stats">
          <Reveal><div className="stat"><b><CountUp to={44} /><span className="unit">ч</span></b><span>экономия методиста на программе 72 ч, оценка по нормам</span></div></Reveal>
          <Reveal delay={80}><div className="stat"><b><CountUp to={21} /><span className="unit">с</span></b><span>каркас программы 72 ч на стенде (норма кейса — 3 мин)</span></div></Reveal>
          <Reveal delay={160}><div className="stat"><b><CountUp to={27} /></b><span>правил автопроверки, 10 блокирующих</span></div></Reveal>
          <Reveal delay={240}><div className="stat"><b><CountUp to={180} /><span className="unit">с</span></b><span>предел на сборку каркаса</span></div></Reveal>
        </div>
      </section>

      <section className="section" id="roles">
        <Reveal><span className="kicker">Роли</span></Reveal>
        <Reveal delay={80}><h2 className="section-title">Каждый отвечает за своё</h2></Reveal>
        <div className="roles-night">
          {[
            { n: 'М', who: 'Мадина · методист', c: '#21A038', items: ['ставит задачу и отвечает на вопросы', 'утверждает каркас и часы', 'назначает экспертов на модули', 'отправляет программу на утверждение'] },
            { n: 'Т', who: 'Тимур · эксперт', c: '#0A87C9', items: ['видит только свои модули', 'вычитывает лекции, тесты и задания', 'просит агента о правке в один клик', 'принимает модуль или возвращает'] },
            { n: 'А', who: 'Ахмед · руководитель', c: '#C77700', items: ['видит готовность и решения людей', 'видит срок и затраты на модели', 'утверждает или возвращает с комментарием', 'получает проект приказа с пустыми реквизитами'] },
          ].map((r, i) => (
            <Reveal key={r.n} delay={i * 100}>
              <div className="role-card" style={{ height: '100%' }}>
                <span className="avatar" style={{ background: r.c, width: 44, height: 44, fontSize: 18 }}>{r.n}</span>
                <h3 style={{ margin: '16px 0 0', fontSize: 20 }}>{r.who}</h3>
                <ul>{r.items.map((x) => <li key={x}>{x}</li>)}</ul>
                <span className="big" style={{ color: r.c }}>{r.n}</span>
              </div>
            </Reveal>
          ))}
        </div>
      </section>

      <section className="section" style={{ paddingTop: 40 }}>
        <Reveal>
          <div className="cta">
            <div className="grid-floor" style={{ opacity: .6 }} />
            <span className="kicker" style={{ position: 'relative' }}>Демо</span>
            <h2 className="section-title" style={{ position: 'relative' }}>Соберите первую программу<br />прямо сейчас</h2>
            <p className="lead" style={{ margin: '0 auto 28px', position: 'relative' }}>Войдите как методист Мадина, вставьте запрос или выберите один из пяти примеров кейса — и через пару минут увидите каркас с проверенными часами.</p>
            <div className="row" style={{ justifyContent: 'center', position: 'relative', gap: 14 }}>
              <Link to="/auth" className="btn btn-lg btn-glow"><Workflow size={18} /> Открыть рабочее место</Link>
              <a href="/docs" className="btn btn-lg btn-glass">API и автопрогон</a>
            </div>
          </div>
        </Reveal>
      </section>

      <footer className="footer">
        <span>МетодАгент · продуктовый хакатон «Точка сборки» · кейс АЦР и GigaCowork</span>
        <span className="row" style={{ gap: 18 }}><Link to="/help">Справка</Link><a href="/docs">API</a><a href="/health">Статус</a></span>
      </footer>
    </div>
  )
}
