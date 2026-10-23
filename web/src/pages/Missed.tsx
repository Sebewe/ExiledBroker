import { Activity, ArrowDownRight, ArrowUpRight, CandlestickChart, FlaskConical, Layers, Repeat, Tag, Timer, Waves } from 'lucide-react'
import { useEffect, useId, useRef, useState, type CSSProperties, type ReactNode } from 'react'
import { Link } from 'react-router'
import type { LiveLeague, MissedCard, MissedFlip, MissedWindow, Mover, Upcoming } from '../api/client'
import { useMissed, useServerNow, useStatus } from '../api/queries'
import { Select } from '../components/Controls'
import { FreshnessBanner } from '../components/Freshness'
import { Notice } from '../components/Notice'
import { PageHeader } from '../components/Section'
import { Empty, Meter, Opportunity, Pill, Route, loopRoute } from '../components/Opportunity'
import { signedPct, utcHour } from '../lib/format'
import { makeMoney, type Money } from '../lib/money'
import { queryFallback } from '../lib/queryFallback'
import { useLeague } from '../lib/useLeague'
import { useNumberParam } from '../lib/useParam'

// The landing page, Market recap: what traded in the latest published hours and what a
// player could look into next. Worded as options to check, not promises: the backtest
// (analysis/backtest.py, the Backtest page) found the hourly signals at best break even.
// The server sends all three look-backs at once (a few KB, cached per loaded hour), so
// the slider switches between them here without another request.

const LOOKBACKS = [1, 2, 3]
// Loops and cards shown before "Show all" (the server sends every one that paid).
const TOP = 3
// Went through at least this often recently: counted as likely in the options.
const LIKELY = 0.5
// An edge this big is usually one trade at an odd ratio, not a price anyone can repeat.
const ODD_EDGE = 0.5
// Hours of trades before the recap has much to say: the exchange is nearly empty at launch.
const EARLY_HOURS = 6

/** Published hours since the league's first one (0 before any trade). */
function hoursIn(l: LiveLeague) {
  if (!l.launched_at || !l.latest_hour) return 0
  return Math.round((Date.parse(l.latest_hour) - Date.parse(l.launched_at)) / 3_600_000) + 1
}

/** The current time, ticking every second (for countdowns). */
function useNow() {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), 1000)
    return () => clearInterval(id)
  }, [])
  return now
}

/** "1d 04:12:09" / "42:13" */
function clock(ms: number) {
  const total = Math.max(0, Math.floor(ms / 1000))
  const d = Math.floor(total / 86_400)
  const h = Math.floor((total % 86_400) / 3600)
  const m = Math.floor((total % 3600) / 60)
  const sec = total % 60
  const pad = (n: number) => String(n).padStart(2, '0')
  const hms = h || d ? `${pad(h)}:${pad(m)}:${pad(sec)}` : `${pad(m)}:${pad(sec)}`
  return d ? `${d}d ${hms}` : hms
}

const hourOf = (iso: string) => utcHour(iso).replace(/^.*, /, '')

/** The announced league: counting down to its launch, then to its first published hour.
 *  `compact` is the strip shown above the running league's recap before launch. */
function Countdown({ upcoming, compact = false }: { upcoming: Upcoming; compact?: boolean }) {
  const now = useNow()
  const start = Date.parse(upcoming.start_at)
  const first = Date.parse(upcoming.first_data_at)
  if (compact) {
    return (
      <Notice kind="info" title={`${upcoming.name} launches in ${clock(start - now)}`}>
        {utcHour(upcoming.start_at)}. Its first recap lands about an hour later, once GGG publishes the first hour of trades.
      </Notice>
    )
  }
  const launched = now >= start
  const due = first - now
  return (
    <section
      className="flex flex-col items-center gap-3 rounded-xl border border-accent/40 bg-gradient-to-br from-accent/10 via-surface to-surface px-5 py-10 text-center"
      aria-label="Countdown"
    >
      <Timer aria-hidden className="size-6 text-accent" />
      <p className="text-sm text-muted">{launched ? `${upcoming.name} is live. First trades published in about` : `${upcoming.name} launches in`}</p>
      <p className="num text-5xl font-semibold tracking-tight text-accent-strong sm:text-6xl" role="timer">
        {launched ? (due > 0 ? clock(due) : 'any minute') : clock(start - now)}
      </p>
      <p className="max-w-xl text-sm text-muted">
        {launched
          ? `GGG publishes each hour of exchange trades just after it ends, so the first hour (from ${hourOf(upcoming.start_at)}) shows up around ${hourOf(upcoming.first_data_at)}. Then this page fills in with what traded, hour by hour.`
          : `Launch: ${utcHour(upcoming.start_at)}. The first hour of trades shows up here around ${hourOf(upcoming.first_data_at)}, an estimate based on when GGG publishes each hour.`}
      </p>
    </section>
  )
}

export default function Missed() {
  const status = useStatus()
  const serverNow = useServerNow()
  const names = status.data?.leagues.map((l) => l.name) ?? []
  const [league, setLeague] = useLeague(names)
  const info = status.data?.leagues.find((l) => l.name === league)
  const summary = useMissed(info?.latest_hour ? league : undefined)
  const [hoursParam, setHours] = useNumberParam('hours', 1)
  const hours = LOOKBACKS.includes(hoursParam) ? hoursParam : 1
  const w = summary.data?.find((x) => x.hours === hours)
  const money = makeMoney(info?.divine_chaos)

  const header = (
    <PageHeader title="Market recap">
      What traded on the exchange in the latest published hours, and a few things worth looking into. GGG publishes each hour just after it ends, so all of
      this has already happened: use it to decide what to check in-game, not as a forecast.
    </PageHeader>
  )
  const fallback = queryFallback(status)
  if (fallback)
    return (
      <>
        {header}
        {fallback}
      </>
    )
  // The announced league once it has started (or with nothing else to show): its
  // countdown is the page until its first hour is loaded.
  const upcoming = status.data!.upcoming
  const started = upcoming && Date.parse(upcoming.start_at) <= serverNow
  if (upcoming && (started || !info)) {
    return (
      <>
        {header}
        <Countdown upcoming={upcoming} />
      </>
    )
  }
  if (!info) {
    return (
      <>
        {header}
        <Notice kind="waiting" title="No league yet">
          The feed hasn't loaded a league. The recap appears about an hour after a league launches.
        </Notice>
      </>
    )
  }
  const early = hoursIn(info) < EARLY_HOURS
  const lastHour = summary.data?.find((x) => x.hours === 1)

  return (
    <>
      {lastHour && <Ticker items={lastHour.ticker} money={money} />}
      {header}
      {names.length > 1 && (
        <div>
          <Select label="League" value={league!} options={names} onChange={setLeague} />
        </div>
      )}
      {upcoming && <Countdown upcoming={upcoming} compact />}
      <FreshnessBanner league={info} now={serverNow} upcoming={upcoming} />
      {info.latest_hour && early && (
        <Notice kind="info" title="Looks like it's early in the league">
          The exchange fills up over the first hours, so these lists stay thin for now and get more useful with every published hour.
        </Notice>
      )}
      {info.latest_hour &&
        (queryFallback(summary, 4) ??
          (w ? (
            <>
              <Hero w={w} flips={lastHour?.flips ?? []} onHours={setHours} />
              <Options w={w} flips={lastHour?.flips ?? []} />
              <Flips flips={lastHour?.flips ?? []} money={money} />
              <Loops w={w} money={money} />
              <Cards w={w} money={money} />
              <KeyMovement w={w} money={money} />
            </>
          ) : (
            <Notice kind="info">Nothing to recap yet.</Notice>
          )))}
    </>
  )
}

function span(w: MissedWindow) {
  const end = new Date(Date.parse(w.latest_hour) + 3_600_000).toISOString()
  const start = new Date(Date.parse(w.latest_hour) - (w.hours - 1) * 3_600_000).toISOString()
  return `${utcHour(start)} – ${utcHour(end).replace(/^.*, /, '')}`
}

const lastHours = (n: number) => (n === 1 ? 'the last hour' : `the last ${n} hours`)

/** A news-style strip of the last hour's movers, scrolling right to left. Two copies of
 *  the row make the loop seamless; the second is hidden from screen readers. */
function Ticker({ items, money }: { items: Mover[]; money: Money }) {
  if (!items.length) return null
  const row = (copy: boolean) => (
    <ul className="flex shrink-0 items-center gap-8 pr-8" aria-hidden={copy || undefined}>
      {items.map((m) => {
        const up = m.change > 0
        return (
          <li key={m.item_id} className="flex shrink-0 items-baseline gap-2 text-sm whitespace-nowrap">
            <span className="text-text">{m.name}</span>
            <span className="num text-xs text-faint">{money(m.price)}</span>
            <span className={`num font-medium ${up ? 'text-positive' : 'text-negative'}`}>
              {up ? '▲' : '▼'} {signedPct(m.change, 0)}
            </span>
          </li>
        )
      })}
    </ul>
  )
  return (
    <section
      aria-label="Price changes in the last published hour"
      className="ticker -mt-2 overflow-hidden rounded-lg border border-border bg-surface py-2"
      tabIndex={0}
    >
      {/* About 3 seconds an item, whatever the count. */}
      <div className="ticker-track flex w-max" style={{ '--ticker-duration': `${items.length * 3}s` } as CSSProperties}>
        {row(false)}
        {row(true)}
      </div>
    </section>
  )
}

function Hero({ w, flips, onHours }: { w: MissedWindow; flips: MissedFlip[]; onHours: (h: number) => void }) {
  const mover = [...w.rising, ...w.falling].sort((a, b) => Math.abs(b.change) - Math.abs(a.change))[0]
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-accent/40 bg-gradient-to-br from-accent/10 via-surface to-surface p-5" aria-label="Recap">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted">Trades in {lastHours(w.hours)}</p>
          <p className="num text-2xl font-semibold tracking-tight sm:text-3xl">{span(w)}</p>
        </div>
        <label className="flex w-full max-w-56 flex-col gap-1.5 text-xs font-medium text-muted">
          <span className="flex justify-between">
            Look back <span className="num text-text">{w.hours}h</span>
          </span>
          <input
            type="range"
            min={1}
            max={3}
            step={1}
            value={w.hours}
            onChange={(e) => onHours(Number(e.target.value))}
            className="w-full cursor-pointer accent-[var(--color-accent)]"
            aria-valuetext={`${w.hours} hours`}
          />
          <span className="flex justify-between text-[11px] text-faint">
            {LOOKBACKS.map((h) => (
              <span key={h}>{h}h</span>
            ))}
          </span>
        </label>
      </div>
      <dl className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Fact label="Volatile flips" value={String(flips.length)} note="liquid items that traded across a wide range" />
        <Fact label="Loops that paid" value={String(w.loops_paid)} note="beat a 2% edge at the hour's worst prices" />
        <Fact label="Card turn-ins that paid" value={String(w.cards_paid)} note="a full set cost less than its reward" />
        <Fact
          label="Biggest move"
          value={mover ? signedPct(mover.change, 0) : '–'}
          note={mover ? mover.name : 'nothing liquid moved'}
          tone={mover ? (mover.change > 0 ? 'text-positive' : 'text-negative') : 'text-muted'}
        />
      </dl>
    </section>
  )
}

function Fact({ label, value, note, tone = 'text-text' }: { label: string; value: string; note: string; tone?: string }) {
  return (
    <div className="rounded-lg border border-border bg-surface/60 px-3 py-2">
      <dt className="text-xs text-muted">{label}</dt>
      <dd className={`num text-xl font-semibold ${tone}`}>{value}</dd>
      <dd className="truncate text-[11px] text-faint" title={note}>
        {note}
      </dd>
    </div>
  )
}

/** Things a player could do with the recap, each with what the backtest saw. No promises. */
function Options({ w, flips: flipList }: { w: MissedWindow; flips: MissedFlip[] }) {
  const likely = (xs: { chance?: number | null }[]) => xs.filter((x) => (x.chance ?? 0) >= LIKELY).length
  const loops = likely(w.loops)
  const cards = likely(w.cards)
  const flips = likely(flipList)
  return (
    <section aria-label="Options" className="flex flex-col gap-3">
      <h2 className="text-lg font-semibold">Things you could look into</h2>
      <ol className="grid gap-3 md:grid-cols-2">
        <Option icon={CandlestickChart} title="Holding for a few days" to="/launch" link="Launch market →">
          Early-league picks held for about ten days were the one tool that came out ahead at the worst prices in every past league we replayed. Past leagues
          don't promise the next one.
        </Option>
        <Option icon={Activity} title="A volatile flip" href="#flips" link="See the flips ↓">
          {flips ? `${flips} of the items below went through at least half the time recently. ` : ''}
          Bid low in the hour's range, list high and lower the ask a little each hour until it sells. A bid that doesn't fill costs nothing: cancel it. It
          needs a busy market, so it should work best in a league's first days.
        </Option>
        <Option icon={Repeat} title="A loop with limit orders" href="#loops" link="See the loops ↓">
          {loops ? `${loops} of the loops below went through at least half the time recently. ` : ''}
          In our replays, loops caught at the worst prices lost; limit orders priced from the last hour's range came out ahead when they filled. Check both
          prices in-game first.
        </Option>
        <Option icon={Layers} title="A card turn-in with limit orders" href="#cards" link="See the cards ↓">
          {cards ? `${cards} of the cards below went through at least half the time recently. ` : ''}
          Bidding at the hour's low and asking the reward's average paid in our replays when the orders filled, but card orders fill less often than loops,
          so expect many to sit unfilled.
        </Option>
      </ol>
      <p className="flex items-center gap-1.5 text-xs text-faint">
        <FlaskConical aria-hidden className="size-3.5 text-accent" />
        <span>
          What we replayed, and how:{' '}
          <Link to="/backtest" className="text-accent hover:text-accent-strong">
            Backtest
          </Link>
        </span>
      </p>
    </section>
  )
}

function Option({
  icon: Icon,
  title,
  children,
  link,
  href,
  to,
}: {
  icon: typeof Waves
  title: string
  children: ReactNode
  link: string
  href?: string
  to?: string
}) {
  const cls = 'mt-auto text-sm text-accent hover:text-accent-strong'
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4">
      <h3 className="flex items-center gap-2 font-semibold">
        <Icon aria-hidden className="size-4 text-accent" />
        {title}
      </h3>
      <p className="text-sm text-muted">{children}</p>
      {to ? (
        <Link to={to} className={cls}>
          {link}
        </Link>
      ) : (
        <a href={href} className={cls}>
          {link}
        </a>
      )}
    </li>
  )
}

function Block({
  id,
  title,
  icon: Icon,
  note,
  children,
  more,
}: {
  id?: string
  title: string
  icon: typeof Waves
  note?: string
  children: ReactNode
  more?: ReactNode
}) {
  return (
    <section id={id} className="flex scroll-mt-20 flex-col gap-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <Icon aria-hidden className="size-4 text-accent" />
          {title}
        </h2>
        {more}
      </div>
      {note && <p className="-mt-1 max-w-3xl text-sm text-muted">{note}</p>}
      {children}
    </section>
  )
}

function KeyMovement({ w, money }: { w: MissedWindow; money: Money }) {
  return (
    <Block
      title="What moved"
      icon={Waves}
      note="Context for what you check, not a tip: by the time an hour is published the move has happened, and in our replays buying the risers an hour later lost money."
    >
      <div className="grid gap-3 md:grid-cols-2">
        <Column title="Rising" hint={`Price now against ${w.hours}h before`}>
          {w.rising.length ? w.rising.map((m) => <MoverRow key={m.item_id} m={m} money={money} />) : <Empty>Nothing liquid rose.</Empty>}
        </Column>
        <Column title="Falling" hint={`Price now against ${w.hours}h before`}>
          {w.falling.length ? w.falling.map((m) => <MoverRow key={m.item_id} m={m} money={money} />) : <Empty>Nothing liquid fell.</Empty>}
        </Column>
      </div>
    </Block>
  )
}

function Column({ title, hint, children }: { title: string; hint?: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-3">
      <h3 className="text-xs font-semibold tracking-wide text-muted uppercase" title={hint}>
        {title}
      </h3>
      <ul className="flex flex-col gap-2">{children}</ul>
    </div>
  )
}

/** How a mover got here: hours running in one direction, or a turn in the last hour. */
function trendNote(m: Mover) {
  const s = m.streak ?? 0
  if (m.change > 0 && s >= 2) return { text: `up ${s}h running`, cls: 'text-positive' }
  if (m.change > 0 && s < 0) return { text: 'cooling off last hour', cls: 'text-muted' }
  if (m.change < 0 && s <= -2) return { text: `down ${-s}h running`, cls: 'text-negative' }
  if (m.change < 0 && s > 0) return { text: 'bouncing back last hour', cls: 'text-muted' }
  return null
}

function MoverRow({ m, money }: { m: Mover; money: Money }) {
  const up = m.change > 0
  const Arrow = up ? ArrowUpRight : ArrowDownRight
  const note = trendNote(m)
  return (
    <li className="flex items-center gap-3">
      <span className={`grid size-9 shrink-0 place-items-center rounded-md ${up ? 'bg-positive/10 text-positive' : 'bg-negative/10 text-negative'}`}>
        <Arrow aria-hidden className="size-5" />
      </span>
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm font-medium" title={m.name}>
          {m.name}
        </div>
        <div className="num truncate text-xs text-muted">
          {money(m.before, Math.max(m.before, m.price))} → {money(m.price, Math.max(m.before, m.price))}
        </div>
        {note && <div className={`truncate text-[11px] ${note.cls}`}>{note.text}</div>}
      </div>
      <span className={`num text-lg font-semibold ${up ? 'text-positive' : 'text-negative'}`}>{signedPct(m.change, 0)}</span>
    </li>
  )
}

function Steady({ paid, hours }: { paid: number; hours: number }) {
  if (hours === 1) return null
  return paid === hours ? (
    <span className="text-positive">paid every hour</span>
  ) : (
    <span>
      paid {paid} of {hours}h
    </span>
  )
}

/** A price in the currency it's quoted in: Chaos as money (Divines once it's worth one),
 *  Divines to three significant figures. */
function quoted(x: number | null | undefined, currency: string | null | undefined, money: Money) {
  if (x == null) return '–'
  return currency === 'divine' ? `${x >= 10 ? x.toFixed(1) : x.toPrecision(3)} div` : money(x)
}

/** The orders the backtest's best option would place this hour, worded as an option. */
function Orders({ steps, ok, skip, missing }: { steps: ReactNode[]; ok: boolean | null | undefined; skip: string; missing: boolean }) {
  return (
    <div className="flex flex-col gap-1 rounded-md border border-border bg-bg/40 px-2.5 py-2 text-xs">
      <span className="text-[11px] font-medium tracking-wide text-faint uppercase">Orders for this hour</span>
      {missing ? (
        <span className="text-muted">Didn't trade in the latest hour, so there's no price to order from.</span>
      ) : (
        <>
          <ol className="flex flex-col gap-0.5 text-muted">
            {steps.map((s, i) => (
              <li key={i}>{s}</li>
            ))}
          </ol>
          {ok === false && <span className="text-warning">{skip}</span>}
        </>
      )}
    </div>
  )
}

/** A price range (by default the last 24 hours'): lowest to highest trade, the average,
 *  and where the order sits. */
function RangeBar({
  low,
  avg,
  high,
  hours,
  mark,
  markLabel,
  money,
  label = '24h',
}: {
  low: number | null | undefined
  avg: number | null | undefined
  high: number | null | undefined
  hours: number | null | undefined
  mark?: number | null
  markLabel?: string
  money: Money
  label?: string
}) {
  if (low == null || high == null || !hours) return null
  const at = (x: number) => (high > low ? Math.min(100, Math.max(0, ((x - low) / (high - low)) * 100)) : 50)
  return (
    <div className="flex flex-col gap-1" title={`${label === '24h' ? `Last 24 hours (${hours} traded)` : label}: low ${money(low, high)}, average ${money(avg, high)}, high ${money(high, high)}`}>
      <div className="relative h-2 rounded-full bg-surface-2">
        {avg != null && <span className="absolute top-0 h-2 w-0.5 -translate-x-1/2 bg-muted" style={{ left: `${at(avg)}%` }} />}
        {mark != null && (
          <span
            aria-label={markLabel}
            className="absolute top-1/2 size-2.5 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg bg-accent"
            style={{ left: `${at(mark)}%` }}
          />
        )}
      </div>
      <div className="num flex justify-between text-[11px] text-faint">
        <span>
          {label} low {money(low, high)}
        </span>
        <span>avg {money(avg, high)}</span>
        <span>high {money(high, high)}</span>
      </div>
    </div>
  )
}

function ShowAll({ all, total, onToggle }: { all: boolean; total: number; onToggle: () => void }) {
  if (total <= TOP) return null
  return (
    <button type="button" onClick={onToggle} className="cursor-pointer text-sm text-accent hover:text-accent-strong">
      {all ? 'Show the top 3' : `Show all ${total}`}
    </button>
  )
}

/** "Show rates": the orders sit behind a button. Hovering (or focusing) it shows them;
 *  clicking pins them open until a click anywhere else, or Escape. */
function Rates({ label, children }: { label: string; children: ReactNode }) {
  const [hover, setHover] = useState(false)
  const [pinned, setPinned] = useState(false)
  const box = useRef<HTMLDivElement>(null)
  const id = useId()
  useEffect(() => {
    if (!pinned) return
    const away = (e: PointerEvent) => {
      if (!box.current?.contains(e.target as Node)) setPinned(false)
    }
    const escape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setPinned(false)
    }
    document.addEventListener('pointerdown', away)
    document.addEventListener('keydown', escape)
    return () => {
      document.removeEventListener('pointerdown', away)
      document.removeEventListener('keydown', escape)
    }
  }, [pinned])
  const open = hover || pinned
  return (
    <div ref={box} className="relative" onMouseEnter={() => setHover(true)} onMouseLeave={() => setHover(false)}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setPinned(!pinned)}
        onFocus={() => setHover(true)}
        onBlur={() => setHover(false)}
        className={`flex min-h-8 cursor-pointer items-center gap-1.5 rounded-md border px-2.5 text-xs font-medium transition-colors ${
          pinned ? 'border-accent/60 bg-accent/15 text-accent-strong' : 'border-border text-muted hover:border-accent/50 hover:text-accent'
        }`}
      >
        <Tag aria-hidden className="size-3.5" />
        {pinned ? 'Rates pinned' : 'Show rates'}
      </button>
      {open && (
        // The padding bridges the gap to the button, so moving onto the popup keeps it open.
        <div id={id} role="dialog" aria-label={label} className="absolute top-full left-0 z-30 w-[min(20rem,80vw)] pt-2">
          <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface-2 p-3 shadow-xl shadow-black/40">{children}</div>
        </div>
      )}
    </div>
  )
}

/** How often the same orders went through in the last 3 days (optimistic fills). */
function Chance({
  tries,
  through,
  chance,
  sell = 'sold if the hour after traded past the ask',
}: {
  tries?: number | null
  through?: number | null
  chance?: number | null
  sell?: string
}) {
  if (chance == null) return <p className="text-xs text-faint">Too few tries in the last 3 days to say how often its orders go through.</p>
  return (
    <div className="flex flex-col gap-0.5">
      <Meter
        label="Went through"
        value={chance}
        hint={`The same orders priced from each of the last 72 hours: bought if the next hour traded past the bid, ${sell}. That counts a fill whenever one trade crossed the price, so real fills are likely lower.`}
      />
      <span className="text-[11px] text-faint">
        {through} of {tries} tries in the last 3 days, by the optimistic fill rule
      </span>
    </div>
  )
}

function Loops({ w, money }: { w: MissedWindow; money: Money }) {
  const [all, setAll] = useState(false)
  const shown = all ? w.loops : w.loops.slice(0, TOP)
  return (
    <Block
      id="loops"
      title="Loops that paid"
      icon={Repeat}
      note="Chaos → item → Divine → Chaos (or the other way round), priced at the hour's worst prices, in markets where enough traded to act on. Likeliest to go through first. The orders that did best in the backtest (a bid halfway up the latest hour's range, an ask three quarters up the other currency's) are behind Show rates."
      more={<ShowAll all={all} total={w.loops.length} onToggle={() => setAll(!all)} />}
    >
      {w.loops.length === 0 ? (
        <Empty>No loop with enough volume beat a 2% edge in {lastHours(w.hours)}.</Empty>
      ) : (
        <ol className="grid gap-3 md:grid-cols-3">
          {shown.map((l) => {
            const chaosFirst = l.direction === 'chaos_first'
            const other = l.bid_in === 'divine' ? 'chaos' : 'divine'
            return (
              <Opportunity
                key={l.item_id}
                title={l.name}
                amount={signedPct(l.best_edge, 0)}
                label="best edge, worst prices"
                footer={
                  <>
                    <Steady paid={l.hours_paid} hours={w.hours} />
                    <span>
                      <span className="num text-text">{money(l.volume)}</span> traded through both markets an hour
                    </span>
                    {l.best_edge > ODD_EDGE && <span className="text-warning">unusually large: likely one odd trade</span>}
                  </>
                }
              >
                <Route steps={loopRoute(l.name, l.direction)} item={l.name} />
                <Chance tries={l.tries} through={l.through} chance={l.chance} />
                <Rates label={`Rates for ${l.name}`}>
                  <Orders
                    missing={l.bid == null}
                    ok={l.order_ok}
                    skip="From this bid it wouldn't pay at the hour's worst sale: skip it this hour."
                    steps={[
                      <>
                        Bid <span className="num text-text">{quoted(l.bid, l.bid_in, money)}</span> each, in {l.bid_in === 'divine' ? 'Divines' : 'Chaos'}
                      </>,
                      <>
                        Ask <span className="num text-text">{quoted(l.ask, other, money)}</span> each, in {other === 'divine' ? 'Divines' : 'Chaos'}
                      </>,
                    ]}
                  />
                  <RangeBar
                    low={l.range_low}
                    avg={l.range_avg}
                    high={l.range_high}
                    hours={l.range_hours}
                    mark={chaosFirst ? l.bid : l.ask}
                    markLabel={chaosFirst ? 'your bid' : 'your ask'}
                    money={money}
                  />
                </Rates>
              </Opportunity>
            )
          })}
        </ol>
      )}
    </Block>
  )
}

function Cards({ w, money }: { w: MissedWindow; money: Money }) {
  const [all, setAll] = useState(false)
  const shown = all ? w.cards : w.cards.slice(0, TOP)
  return (
    <Block
      id="cards"
      title="Card turn-ins that paid"
      icon={Layers}
      note="A full set cost less than its reward at the hour's average prices, with at least a full set traded. Likeliest to go through first. The orders that did best in the backtest (a bid at the card's lowest price from the latest hour, an ask at the reward's average) are behind Show rates."
      more={<ShowAll all={all} total={w.cards.length} onToggle={() => setAll(!all)} />}
    >
      {w.cards.length === 0 ? (
        <Empty>No card turn-in paid in {lastHours(w.hours)}.</Empty>
      ) : (
        <ol className="grid gap-3 md:grid-cols-3">
          {shown.map((c: MissedCard) => (
            <Opportunity
              key={c.item_id}
              title={c.name}
              amount={`+${money(c.margin)}`}
              label="a set, average prices"
              footer={
                <>
                  <span>set costs {money(c.set_cost)}</span>
                  <span>
                    <span className="num text-text">{c.sets.toFixed(c.sets >= 10 ? 0 : 1)}</span> sets traded
                  </span>
                  <Steady paid={c.hours_paid} hours={w.hours} />
                </>
              }
            >
              <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted">
                a full set turns into <Pill accent>{c.reward}</Pill>
              </div>
              <Chance tries={c.tries} through={c.through} chance={c.chance} />
              <Rates label={`Rates for ${c.name}`}>
                <Orders
                  missing={c.bid == null}
                  ok={c.order_ok}
                  skip="A set wouldn't pay from this bid at the reward's lowest price: skip it this hour."
                  steps={[
                    <>
                      Bid <span className="num text-text">{money(c.bid, c.range_high ?? c.bid)}</span> a card
                    </>,
                    <>
                      {/* In Chaos: a reward is often a Divine Orb itself. */}
                      Ask <span className="num text-text">{money(c.ask, 0)}</span> for each reward
                    </>,
                  ]}
                />
                <RangeBar low={c.range_low} avg={c.range_avg} high={c.range_high} hours={c.range_hours} mark={c.bid} markLabel="your bid" money={money} />
              </Rates>
            </Opportunity>
          ))}
        </ol>
      )}
    </Block>
  )
}

/** The ask after `hours` hours of cuts, for the schedule in the rates popup. */
const cutAsk = (f: MissedFlip, hours: number) => f.ask * (1 - f.cut) ** hours

/** The latest hour's flips: the same whatever the look-back (sent with the 1-hour one). */
function Flips({ flips, money }: { flips: MissedFlip[]; money: Money }) {
  const [all, setAll] = useState(false)
  const shown = all ? flips : flips.slice(0, TOP)
  return (
    <Block
      id="flips"
      title="Volatile flips"
      icon={Activity}
      note="Liquid items whose latest hour traded across a wide range (at least 10k Chaos traded, a range of at most 50%: wider is usually one odd trade). Likeliest to go through first. The orders, behind Show rates, are the ones the backtest tested: bid low in the hour's range, list high, cut the ask a little each hour until it sells. A bid that doesn't fill costs nothing: cancel it."
      more={<ShowAll all={all} total={flips.length} onToggle={() => setAll(!all)} />}
    >
      {flips.length === 0 ? (
        <Empty>No liquid item traded across a wide enough range in the latest hour.</Empty>
      ) : (
        <ol className="grid gap-3 md:grid-cols-3">
          {shown.map((f) => (
            <Opportunity
              key={f.item_id}
              title={f.name}
              amount={`${Math.round(f.range * 100)}%`}
              label="the latest hour's range"
              muted
              footer={
                <>
                  <span>
                    <span className="num text-text">{money(f.volume)}</span> traded that hour
                  </span>
                  <span>average {money(f.price, f.high)}</span>
                </>
              }
            >
              <Chance tries={f.tries} through={f.through} chance={f.chance} sell="sold within 6 hours at the ask" />
              <Rates label={`Rates for ${f.name}`}>
                <div className="flex flex-col gap-1 rounded-md border border-border bg-bg/40 px-2.5 py-2 text-xs">
                  <span className="text-[11px] font-medium tracking-wide text-faint uppercase">Orders for this hour</span>
                  <ol className="flex flex-col gap-0.5 text-muted">
                    <li>
                      Bid <span className="num text-text">{money(f.bid, f.high)}</span> each; cancel it if it hasn't filled by the end of the hour
                    </li>
                    <li>
                      Then list at <span className="num text-text">{money(f.ask, f.high)}</span>, {Math.round(f.cut * 100)}% lower each hour it doesn't sell:
                      <span className="num text-text"> {money(cutAsk(f, 6), f.high)}</span> after 6 hours,
                      <span className="num text-text"> {money(cutAsk(f, 24), f.high)}</span> after a day
                    </li>
                  </ol>
                </div>
                <RangeBar low={f.low} avg={f.price} high={f.high} hours={1} mark={f.bid} markLabel="your bid" money={money} label="latest hour" />
              </Rates>
            </Opportunity>
          ))}
        </ol>
      )}
    </Block>
  )
}
