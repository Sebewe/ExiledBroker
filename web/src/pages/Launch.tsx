import { Crown, Flame, Sprout, TrendingDown } from 'lucide-react'
import { Link } from 'react-router'
import type { LaunchPick, LaunchWindow, LiveLeague } from '../api/client'
import { useLaunchPicks, useLeagues, useStatus } from '../api/queries'
import { ItemName } from '../components/ItemLink'
import { Notice } from '../components/Notice'
import { PageHeader } from '../components/Section'
import { HowItWorks } from '../components/HowItWorks'
import { count } from '../lib/format'
import { useItemHref } from '../lib/itemHref'
import { queryFallback } from '../lib/queryFallback'
import { trackFeature } from '../lib/usage'
import { useParam } from '../lib/useParam'

// What a typical early-league wallet holds; picks cost at most this much each.
const BUDGET = 2
type WindowId = 'day1' | 'days2_4' | 'days5_10'
const STYLE: Record<WindowId, { name: string; tagline: string; icon: typeof Flame }> = {
  day1: {
    name: 'First grab',
    tagline: 'Everything is cheap while Chaos is still worth a lot.',
    icon: Flame,
  },
  days2_4: {
    name: 'Early climb',
    tagline: 'Prices are moving; the reliable risers are still on sale.',
    icon: Sprout,
  },
  days5_10: {
    name: 'Last call',
    tagline: 'Smaller gains, but the safest ones before the market settles.',
    icon: Crown,
  },
}

const days = (w: LaunchWindow) => (w.first_day === w.last_day ? `Day ${w.first_day}` : `Days ${w.first_day}–${w.last_day}`)
const times = (x: number | null | undefined) => (x == null ? '–' : `×${x >= 10 ? x.toFixed(0) : x.toFixed(1)}`)
/** Divines: 10.4div, 0.42div; tiny prices keep two significant digits (0.0072div). */
function div(x: number | null | undefined) {
  if (x == null) return '–'
  return `${x >= 10 ? x.toFixed(1) : x >= 0.01 ? x.toFixed(2) : x.toPrecision(2)}div`
}

/** The live league's launch day (1-based), from its first and latest traded hours. */
function launchDay(l: LiveLeague | undefined) {
  if (!l?.launched_at || !l.latest_hour) return null
  return Math.floor((Date.parse(l.latest_hour) - Date.parse(l.launched_at)) / 86_400_000) + 1
}

export default function Launch() {
  const status = useStatus()
  const board = useLaunchPicks()
  const live = useLeagues().find((l) => l.latest_hour) // in the preview: its league that day
  const day = launchDay(live)
  const windows = board.data ?? []
  const current = day == null ? undefined : windows.find((w) => day >= w.first_day && day <= w.last_day)
  // Without a choice in the URL, follow the live league into its current window.
  const [picked, setPicked] = useParam<WindowId>('window', (current?.window_id as WindowId | undefined) ?? 'day1')
  const w = windows.find((x) => x.window_id === picked) ?? windows[0]

  return (
    <>
      <PageHeader title="Launch market">
        What to buy with your first couple of Divines, so early-league inflation doesn't eat your currency. <HowItWorks anchor="launch-picks" />
      </PageHeader>
      {queryFallback(status) ??
        queryFallback(board) ??
        (!w ? (
          <Notice kind="waiting" title="No picks yet">
            Picks are ranked from past leagues' launch fortnights and appear once they've been built.
          </Notice>
        ) : (
          <>
            <LiveBanner league={live?.name} day={day} current={current} />
            <div role="tablist" aria-label="When you buy" className="grid grid-cols-3 gap-2">
              {windows.map((x) => {
                const id = x.window_id as WindowId
                const Icon = STYLE[id]?.icon ?? Flame
                const on = x.window_id === w.window_id
                return (
                  <button
                    key={x.window_id}
                    role="tab"
                    type="button"
                    aria-selected={on}
                    onClick={() => {
                      trackFeature('launch-pick')
                      setPicked(id)
                    }}
                    className={`relative flex cursor-pointer flex-col items-start gap-0.5 rounded-lg border px-3 py-2.5 text-left transition-colors duration-150 sm:px-4 ${
                      on ? 'border-accent/60 bg-accent/10' : 'border-border bg-surface hover:border-accent/30'
                    }`}
                  >
                    <span className="flex items-center gap-1.5 text-xs font-medium text-muted">
                      <Icon aria-hidden className={`size-3.5 ${on ? 'text-accent' : ''}`} />
                      {days(x)}
                    </span>
                    <span className={`font-semibold ${on ? 'text-accent-strong' : 'text-text'}`}>{STYLE[id]?.name ?? days(x)}</span>
                    {current?.window_id === x.window_id && (
                      <span className="absolute top-2 right-2 flex items-center gap-1 text-[11px] font-medium text-accent-strong">
                        <span className="size-1.5 animate-pulse rounded-full bg-accent" aria-hidden />
                        {/* On a phone the three windows are too narrow for the word: the dot says it. */}
                        <span className="sr-only sm:not-sr-only">Now</span>
                      </span>
                    )}
                  </button>
                )
              })}
            </div>
            <WindowView w={w} isNow={current?.window_id === w.window_id} />
          </>
        ))}
    </>
  )
}

function LiveBanner({ league, day, current }: { league?: string; day: number | null; current?: LaunchWindow }) {
  if (!league || day == null) return null
  if (current)
    return (
      <Notice kind="ok" title={`${league} is on day ${day}: ${STYLE[current.window_id as WindowId]?.name ?? days(current)} is open now.`}>
        Picks show their live price from the latest hour next to what they usually cost.
      </Notice>
    )
  return (
    <Notice kind="info">
      {league} is on day {count(day)}, past these windows. This is the playbook for the next league's launch.
    </Notice>
  )
}

function WindowView({ w, isNow }: { w: LaunchWindow; isNow: boolean }) {
  const id = w.window_id as WindowId
  const top = w.picks[0]
  const sell = `days ${w.sell_first}–${w.sell_last}`
  return (
    <div className="flex flex-col gap-5">
      <p className="text-sm text-muted">
        {STYLE[id]?.tagline} Buy in {days(w).toLowerCase()}, sell on {sell}.
      </p>
      {top && <Outcome w={w} top={top} />}
      {w.picks.length === 0 ? (
        <Notice kind="info">No item passed the filters for this window.</Notice>
      ) : (
        <>
          <ol className="grid gap-3 md:grid-cols-3" aria-label="Top picks">
            {w.picks.slice(0, 3).map((p) => (
              <li key={p.item_id}>
                <PickCard p={p} w={w} isNow={isNow} />
              </li>
            ))}
          </ol>
          {w.picks.length > 3 && (
            <ol className="flex flex-col divide-y divide-border/60 rounded-lg border border-border bg-surface" aria-label="Also good">
              {w.picks.slice(3).map((p) => (
                <li key={p.item_id}>
                  <PickRow p={p} w={w} isNow={isNow} />
                </li>
              ))}
            </ol>
          )}
        </>
      )}
      <HowRanked w={w} />
    </div>
  )
}

/** What 2 Divines turned into by the sale: kept in Chaos, put in a typical item, or the #1 pick. */
function Outcome({ w, top }: { w: LaunchWindow; top: LaunchPick }) {
  const bars = [
    { label: 'Kept as Chaos', value: w.chaos_growth, cls: 'bg-negative/70' },
    { label: 'A typical item', value: w.typical_growth, cls: 'bg-faint' },
    { label: `#1 ${top.name}`, value: top.growth, cls: 'bg-positive/80' },
  ]
  const max = Math.max(...bars.map((b) => b.value ?? 0), 1)
  const kept = w.chaos_growth
  return (
    <section className="rounded-lg border border-border bg-surface p-4" aria-label={`What ${BUDGET} Divines became`}>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
        <h2 className="font-semibold">
          Your {BUDGET} Divines, by day {w.sell_last}
        </h2>
        {kept != null && kept < 1 && (
          <span className="flex items-center gap-1 text-sm text-negative">
            <TrendingDown aria-hidden className="size-4" />
            Chaos lost {Math.round((1 - kept) * 100)}% of its value against Divines
          </span>
        )}
      </div>
      <dl className="mt-3 flex flex-col gap-2">
        {bars.map((b) => (
          <div key={b.label} className="grid grid-cols-[minmax(0,9rem)_1fr_auto] items-center gap-3 text-sm sm:grid-cols-[minmax(0,14rem)_1fr_auto]">
            <dt className="truncate text-muted" title={b.label}>
              {b.label}
            </dt>
            <dd className="h-3 rounded-full bg-surface-2">
              <div
                className={`h-3 rounded-full ${b.cls}`}
                style={{
                  width: `${Math.max(2, ((b.value ?? 0) / max) * 100)}%`,
                }}
              />
            </dd>
            <dd className="num w-20 text-right font-medium">{b.value == null ? '–' : div(BUDGET * b.value)}</dd>
          </div>
        ))}
      </dl>
      <p className="mt-2 text-xs text-faint">Typical results across the reference leagues, in Divines, at median prices.</p>
    </section>
  )
}

/** One dot per reference league, newest first: green if the pick beat holding Divines there. */
function LeagueDots({ p }: { p: LaunchPick }) {
  return (
    <span className="flex items-center gap-1" aria-label={`Beat holding Divines in ${p.rose} of ${p.leagues.length} leagues`}>
      {p.leagues.map((l) => (
        <span
          key={l.league}
          title={`${l.league}: ${l.growth == null ? 'not traded' : times(l.growth)}`}
          className={`size-2.5 rounded-full ${l.growth == null ? 'border border-border' : l.growth > 1 ? 'bg-positive' : 'bg-negative'}`}
        />
      ))}
    </span>
  )
}

const units = (p: LaunchPick) => Math.floor(BUDGET / p.buy_divine)

function LivePrice({ p }: { p: LaunchPick }) {
  if (p.live_divine == null) return <span className="text-faint">no trades this hour</span>
  const cheaper = p.live_divine <= p.buy_divine
  return (
    <span title="Latest hour's price against what it usually cost in this window">
      now <span className="num text-text">{div(p.live_divine)}</span>{' '}
      <span className={cheaper ? 'text-positive' : 'text-warning'}>{cheaper ? '(below usual)' : '(above usual)'}</span>
    </span>
  )
}

function PickCard({ p, w, isNow }: { p: LaunchPick; w: LaunchWindow; isNow: boolean }) {
  const href = useItemHref(w.live_league ?? undefined)
  const medal = ['text-accent-strong', 'text-text', 'text-warning/80'][p.rank - 1] ?? 'text-muted'
  return (
    <article className="flex h-full flex-col gap-3 rounded-lg border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className={`text-xs font-semibold ${medal}`}>#{p.rank}</div>
          <h3 className="truncate font-semibold" title={p.name}>
            <ItemName name={p.name} href={href(p.item_id)} />
          </h3>
          <div className="text-xs text-faint capitalize">{p.group_id === 'divination' ? 'Divination card' : p.group_id}</div>
        </div>
        <div className="num text-right text-2xl font-semibold text-positive">{times(p.growth)}</div>
      </div>
      <p className="text-sm">
        <span className="num">{BUDGET} div</span> → <span className="num font-semibold text-positive">{div(BUDGET * p.growth)}</span>
        <span className="text-muted"> by day {w.sell_last}</span>
      </p>
      <div className="mt-auto flex flex-col gap-1.5 text-xs text-muted">
        <div className="flex items-center justify-between gap-2">
          <LeagueDots p={p} />
          <span>
            worst league <span className={`num ${p.worst >= 1 ? 'text-positive' : 'text-negative'}`}>{times(p.worst)}</span>
          </span>
        </div>
        <div className="flex flex-wrap justify-between gap-x-3">
          <span>
            ≈<span className="num text-text">{div(p.buy_divine)}</span> each · {BUDGET} div buys ≈{count(units(p))}
          </span>
          {isNow && <LivePrice p={p} />}
        </div>
      </div>
    </article>
  )
}

function PickRow({ p, w, isNow }: { p: LaunchPick; w: LaunchWindow; isNow: boolean }) {
  const href = useItemHref(w.live_league ?? undefined)
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2.5 text-sm">
      <span className="num w-6 text-faint">#{p.rank}</span>
      <span className="min-w-0 flex-1 truncate font-medium" title={p.name}>
        <ItemName name={p.name} href={href(p.item_id)} />
      </span>
      {/* On a phone the name gets the room; the cards above show the full detail. */}
      <span className="hidden sm:flex">
        <LeagueDots p={p} />
      </span>
      <span className="num hidden w-24 text-right text-xs text-muted sm:inline">≈{div(p.buy_divine)} each</span>
      {isNow && (
        <span className="order-last w-full pl-10 text-xs text-muted sm:order-none sm:w-auto sm:pl-0">
          <LivePrice p={p} />
        </span>
      )}
      <span className="num w-14 text-right font-semibold text-positive" title={`${BUDGET} div → ${div(BUDGET * p.growth)} by day ${w.sell_last}`}>
        {times(p.growth)}
      </span>
    </div>
  )
}

/** Where the picks come from, in one line; the method is on Research's How the tools work. */
function HowRanked({ w }: { w: LaunchWindow }) {
  return (
    <p className="text-xs text-faint">
      Ranked from {w.leagues.join(', ')}, among {w.candidates} items at most {BUDGET} div each.{' '}
      <Link to="/research/method#launch-picks" className="hover:text-info">
        How these are picked →
      </Link>
    </p>
  )
}
