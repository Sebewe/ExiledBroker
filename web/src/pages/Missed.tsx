import { ArrowDownRight, ArrowRight, ArrowUpRight, Layers, Repeat, Waves } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { MissedCard, MissedLoop, MissedWindow, Mover, Volatile } from '../api/client'
import { useMissed, useStatus } from '../api/queries'
import { Select } from '../components/Controls'
import { FreshnessBanner } from '../components/Freshness'
import { Notice } from '../components/Notice'
import { PageHeader } from '../components/Section'
import { inUnit, price, signedPct, utcHour } from '../lib/format'
import { queryFallback } from '../lib/queryFallback'
import { useLeague } from '../lib/useLeague'
import { useNumberParam } from '../lib/useParam'

// The landing page: a short recap of what the latest published hours offered. The
// server sends all three look-backs at once (a few KB, cached per loaded hour), so the
// slider switches between them here without another request.

const LOOKBACKS = [1, 2, 3]

export default function Missed() {
  const status = useStatus()
  const names = status.data?.leagues.map((l) => l.name) ?? []
  const [league, setLeague] = useLeague(names)
  const info = status.data?.leagues.find((l) => l.name === league)
  const summary = useMissed(info?.latest_hour ? league : undefined)
  const [hoursParam, setHours] = useNumberParam('hours', 1)
  const hours = LOOKBACKS.includes(hoursParam) ? hoursParam : 1
  const w = summary.data?.find((x) => x.hours === hours)
  const rate = info?.divine_chaos
  // Amounts arrive in Chaos. Anything worth a Divine or more (judged by `ref`, so a pair
  // of prices shares a unit) is shown in Divines at the league's latest rate.
  const money: Money = (chaos, ref = chaos) =>
    rate && Math.abs(ref ?? 0) >= rate ? price(inUnit(chaos, 'divine', rate), 'divine') : price(chaos, 'chaos')

  const header = (
    <PageHeader title="Missed opportunities">
      What the market offered while you weren't watching. GGG publishes each hour of trades just after it ends, so this is a recap of the latest published
      hours, not a live feed. Check the in-game exchange before acting on it.
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

  return (
    <>
      {header}
      {names.length > 1 && (
        <div>
          <Select label="League" value={league!} options={names} onChange={setLeague} />
        </div>
      )}
      <FreshnessBanner league={info} now={status.data!.now} />
      {info.latest_hour &&
        (queryFallback(summary, 4) ??
          (w ? (
            <>
              <Hero w={w} money={money} onHours={setHours} />
              <KeyMovement w={w} money={money} />
              <Loops w={w} money={money} />
              <Cards w={w} money={money} />
            </>
          ) : (
            <Notice kind="info">Nothing to recap yet.</Notice>
          )))}
    </>
  )
}

type Money = (chaos: number | null | undefined, ref?: number | null) => string

function span(w: MissedWindow) {
  const end = new Date(Date.parse(w.latest_hour) + 3_600_000).toISOString()
  const start = new Date(Date.parse(w.latest_hour) - (w.hours - 1) * 3_600_000).toISOString()
  return `${utcHour(start)} – ${utcHour(end).replace(/^.*, /, '')}`
}

const lastHours = (n: number) => (n === 1 ? 'the last hour' : `the last ${n} hours`)

function Hero({ w, money, onHours }: { w: MissedWindow; money: Money; onHours: (h: number) => void }) {
  const total = w.loops_missed + w.cards_missed
  return (
    <section className="flex flex-col gap-4 rounded-xl border border-accent/40 bg-gradient-to-br from-accent/10 via-surface to-surface p-5" aria-label="Recap">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <p className="text-sm text-muted">In {lastHours(w.hours)}, up to</p>
          <p className="num text-4xl font-semibold tracking-tight text-accent-strong sm:text-5xl">{money(total)}</p>
          <p className="mt-1 text-sm text-muted">
            sat on the table in loops ({money(w.loops_missed)}) and card turn-ins ({money(w.cards_missed)}).
          </p>
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
      <p className="text-xs text-faint">
        Trades {span(w)}. Every paying trade counted at the volume that actually traded: an upper bound, since nobody catches them all.
      </p>
    </section>
  )
}

function Block({ title, icon: Icon, children, more }: { title: string; icon: typeof Waves; children: ReactNode; more?: ReactNode }) {
  return (
    <section className="flex flex-col gap-3">
      <div className="flex items-baseline justify-between gap-3">
        <h2 className="flex items-center gap-2 text-lg font-semibold">
          <Icon aria-hidden className="size-4 text-accent" />
          {title}
        </h2>
        {more}
      </div>
      {children}
    </section>
  )
}

function Empty({ children }: { children: ReactNode }) {
  return <p className="rounded-lg border border-dashed border-border px-3 py-4 text-center text-sm text-faint">{children}</p>
}

function KeyMovement({ w, money }: { w: MissedWindow; money: Money }) {
  return (
    <Block title="Key movement" icon={Waves}>
      <div className="grid gap-3 md:grid-cols-3">
        <Column title="Rising" hint={`Price now against ${w.hours}h before`}>
          {w.rising.length ? w.rising.map((m) => <MoverRow key={m.item_id} m={m} money={money} />) : <Empty>Nothing liquid rose.</Empty>}
        </Column>
        <Column title="Falling" hint={`Price now against ${w.hours}h before`}>
          {w.falling.length ? w.falling.map((m) => <MoverRow key={m.item_id} m={m} money={money} />) : <Empty>Nothing liquid fell.</Empty>}
        </Column>
        <Column title="Volatile" hint="Widest gap between the lowest and highest trade">
          {w.volatile.length ? w.volatile.map((v) => <VolatileRow key={v.item_id} v={v} money={money} />) : <Empty>No wide swings.</Empty>}
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

/** A short read on a mover: does it look like a trend to ride or a dip still going? */
function trendNote(m: Mover) {
  const s = m.streak ?? 0
  if (m.change > 0 && s >= 2) return { text: `up ${s}h running · momentum`, cls: 'text-positive' }
  if (m.change > 0 && s < 0) return { text: 'cooling off last hour', cls: 'text-muted' }
  if (m.change < 0 && s <= -2) return { text: `down ${-s}h running · still sliding`, cls: 'text-negative' }
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

function VolatileRow({ v, money }: { v: Volatile; money: Money }) {
  // Where the typical price sat between the low and high trades.
  const at = v.high > v.low ? ((v.price - v.low) / (v.high - v.low)) * 100 : 50
  return (
    <li className="flex flex-col gap-1">
      <div className="flex items-baseline justify-between gap-2">
        <span className="truncate text-sm font-medium" title={v.name}>
          {v.name}
        </span>
        <span className="num text-sm font-semibold text-warning">{Math.round(v.range * 100)}% range</span>
      </div>
      <div className="relative h-2 rounded-full bg-gradient-to-r from-info/40 to-warning/50" title={`Typical ${money(v.price)}`}>
        <span className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rounded-full border-2 border-bg bg-text" style={{ left: `${at}%` }} />
      </div>
      <div className="num flex justify-between text-[11px] text-faint">
        <span>low {money(v.low, v.high)}</span>
        <span>high {money(v.high, v.high)}</span>
      </div>
    </li>
  )
}

function Pill({ children, accent = false }: { children: ReactNode; accent?: boolean }) {
  return (
    <span
      className={`max-w-[10rem] truncate rounded-full border px-2 py-0.5 text-xs ${accent ? 'border-accent/50 text-accent-strong' : 'border-border text-text'}`}
    >
      {children}
    </span>
  )
}

const Arrow = () => <ArrowRight aria-hidden className="size-3 shrink-0 text-faint" />

function Opportunity({ rank, missed, children, footer }: { rank: number; missed: string; children: ReactNode; footer: ReactNode }) {
  return (
    <li className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-2">
        <span className="text-xs font-semibold text-accent-strong">#{rank}</span>
        <div className="text-right">
          <div className="num text-2xl font-semibold text-positive">{missed}</div>
          <div className="text-[11px] text-faint">left on the table</div>
        </div>
      </div>
      {children}
      <div className="mt-auto flex flex-wrap gap-x-3 gap-y-1 text-xs text-muted">{footer}</div>
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

function Loops({ w, money }: { w: MissedWindow; money: Money }) {
  const route = (l: MissedLoop) => (l.direction === 'chaos_first' ? ['Chaos', l.name, 'Divine', 'Chaos'] : ['Chaos', 'Divine', l.name, 'Chaos'])
  return (
    <Block
      title="Best loops"
      icon={Repeat}
      more={
        <Link to="/arbitrage" className="text-sm text-accent hover:text-accent-strong">
          All loops →
        </Link>
      }
    >
      {w.loops.length === 0 ? (
        <Empty>No loop beat a 2% edge in {lastHours(w.hours)}.</Empty>
      ) : (
        <ol className="grid gap-3 md:grid-cols-3">
          {w.loops.map((l, i) => (
            <Opportunity
              key={l.item_id}
              rank={i + 1}
              missed={money(l.missed)}
              footer={
                <>
                  <span>
                    best edge <span className="num text-positive">{signedPct(l.best_edge, 0)}</span>
                  </span>
                  <Steady paid={l.hours_paid} hours={w.hours} />
                </>
              }
            >
              <div className="flex flex-wrap items-center gap-1">
                {route(l).map((step, j) => (
                  <span key={j} className="flex items-center gap-1">
                    {j > 0 && <Arrow />}
                    <Pill accent={step !== l.name}>{step}</Pill>
                  </span>
                ))}
              </div>
            </Opportunity>
          ))}
        </ol>
      )}
    </Block>
  )
}

function Cards({ w, money }: { w: MissedWindow; money: Money }) {
  return (
    <Block
      title="Best card turn-ins"
      icon={Layers}
      more={
        <Link to="/cards" className="text-sm text-accent hover:text-accent-strong">
          All cards →
        </Link>
      }
    >
      {w.cards.length === 0 ? (
        <Empty>No card turn-in paid in {lastHours(w.hours)}.</Empty>
      ) : (
        <ol className="grid gap-3 md:grid-cols-3">
          {w.cards.map((c: MissedCard, i) => (
            <Opportunity
              key={c.item_id}
              rank={i + 1}
              missed={money(c.missed)}
              footer={
                <>
                  <span>
                    <span className="num text-positive">+{money(c.margin)}</span> a set
                  </span>
                  <span>set costs {money(c.set_cost)}</span>
                  <Steady paid={c.hours_paid} hours={w.hours} />
                </>
              }
            >
              <div className="flex flex-wrap items-center gap-1">
                <Pill>{c.name}</Pill>
                <Arrow />
                <Pill accent>{c.reward}</Pill>
              </div>
            </Opportunity>
          ))}
        </ol>
      )}
    </Block>
  )
}
