import { RotateCcw, Tag } from 'lucide-react'
import { useId, useState } from 'react'
import { Link } from 'react-router'
import { useGameHour, useStatus } from '../api/queries'
import { hourLabel, useGameClock } from '../lib/gameClock'
import { Notice } from '../components/Notice'
import { PageHeader, Section } from '../components/Section'
import { Stat } from '../components/Stat'
import { price, signedPct } from '../lib/format'
import { listingAt, quickSell, setListing, tally, total, worth } from '../lib/game'
import { EMPTY, setGame, START_CASH, type Done, type FlipTrade, type Trade } from '../lib/gameStore'
import { usePreview } from '../lib/preview'
import { queryFallback } from '../lib/queryFallback'

// The preview's trading game, the player's side (docs/preview.md, lib/game.ts): what they
// have, the trades still open (flips held: change their listing or sell them now) and the
// history of every trade with what it made or lost. Played on the Market recap. Frontend
// only: the state is in this browser, and the page reads the game's current hour.

const div = (v: number) => price(v, 'divine')
const signed = (v: number) => `${v < -0.005 ? '−' : '+'}${div(Math.abs(v))}`
const tone = (v: number) => (v > 0.005 ? 'text-positive' : v < -0.005 ? 'text-negative' : 'text-muted')

const KIND = { loop: 'Loop', card: 'Card turn-in', flip: 'Flip' } as const
const DIRECTION: Record<string, string> = { chaos_first: 'Chaos first', divine_first: 'Divines first' }
const OUTCOME = { sold: 'Sold', 'quick-sold': 'Sold now', unfilled: "Didn't fill" } as const

export default function Portfolio() {
  const status = useStatus()
  const preview = usePreview()
  const header = (
    <PageHeader title="Portfolio">
      Your trading game: the trades you made on the{' '}
      <Link to="/" className="text-accent hover:text-accent-strong">
        Market recap
      </Link>{' '}
      and what each made or lost. Kept in this browser only.
    </PageHeader>
  )
  if (!preview.on)
    return (
      <>
        {header}
        {queryFallback(status) ?? (
          <Notice kind="info" title="Part of the pre-launch preview">
            The trading game let you trade a past league's early days hour by hour before launch. The live league is on now: the{' '}
            <Link to="/" className="text-accent hover:text-accent-strong">
              Market recap
            </Link>{' '}
            has today's trades.
          </Notice>
        )}
      </>
    )
  return (
    <>
      {header}
      <Board />
    </>
  )
}

function Board() {
  const clock = useGameClock()
  const doc = useGameHour(clock.running || undefined).data
  if (!clock.running)
    return (
      <Notice kind="info" title="No trades yet">
        You start with {div(START_CASH)}. On the{' '}
        <Link to="/" className="text-accent hover:text-accent-strong">
          Market recap
        </Link>
        , pick a trade and press "Trade this hour", then "Next hour" in the bar at the bottom to see how it went. Only what the recap lists can be traded, and
        the market only takes so much each hour.
      </Notice>
    )
  const s = clock.s
  const rate = doc?.divine_chaos
  const now = total(s, rate)
  const t = tally(s.done)
  return (
    <>
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <Stat label="Worth now" value={div(now)} />
        <Stat label={`Since you started with ${div(START_CASH)}`} value={`${signed(now - START_CASH)} (${signedPct(now / START_CASH - 1, 0)})`} />
        <Stat label="Free to trade" value={div(s.cash)} />
        <Stat label="Trades closed" value={t.trades ? `${t.won} of ${t.trades} made money` : '–'} />
      </div>
      <p className="text-sm text-muted">
        Started at {hourLabel(clock.launched, s.start)}; now at <span className="text-text">{hourLabel(clock.launched, s.n)}</span>.
      </p>
      <Section title="Open" description="Orders waiting to fill or sell, and flips you hold. A held flip counts at its latest average price.">
        {s.open.length === 0 ? (
          <p className="text-sm text-muted">Nothing open.</p>
        ) : (
          <ul className="flex flex-col gap-2">
            {s.open.map((x) => (
              <OpenRow key={x.id} t={x} n={s.n} rate={rate} launched={clock.launched} />
            ))}
          </ul>
        )}
      </Section>
      <Section title="History" description="Every trade that closed, newest first.">
        {s.done.length === 0 ? <p className="text-sm text-muted">No trade has closed yet: step the clock with "Next hour" on the recap.</p> : <HistoryTable rows={s.done} launched={clock.launched} />}
        {t.trades > 0 && (
          <p className="text-sm text-muted">
            Closed trades made <span className={`num font-semibold ${tone(t.profit)}`}>{signed(t.profit)}</span> in all.
          </p>
        )}
      </Section>
      <StartOver />
    </>
  )
}

const tradeName = (x: { kind: Trade['kind']; name: string; direction?: string | null }) =>
  `${KIND[x.kind]}: ${x.name}${x.kind === 'loop' && x.direction ? ` (${DIRECTION[x.direction] ?? x.direction})` : ''}`

function OpenRow({ t, n, rate, launched }: { t: Trade; n: number; rate: number | null | undefined; launched: string | null | undefined }) {
  const state =
    t.kind === 'flip'
      ? t.state === 'bidding'
        ? 'Bid placed: fills next hour if a trade goes under it'
        : `Holding ${t.left} of ${t.units}${t.got > 0 ? `, ${div(t.got)} sold so far` : ''}`
      : t.state === 'placed'
        ? 'Order placed: fills next hour or comes back'
        : t.settle != null
          ? `Filled; sells ${hourLabel(launched, t.settle)}`
          : "Filled; the sale isn't known by the end of the preview's data"
  return (
    <li className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-3 sm:flex-row sm:items-center sm:justify-between">
      <div className="min-w-0">
        <p className="truncate font-semibold" title={tradeName(t)}>
          {tradeName(t)}
        </p>
        <p className="text-xs text-muted">
          {hourLabel(launched, t.at)} · {state}
        </p>
      </div>
      <div className="flex shrink-0 flex-wrap items-center gap-3">
        <span className="num text-sm">
          <span className="text-faint">in</span> {div(t.stake)} <span className="text-faint">· worth</span> {div(worth(t, rate))}
        </span>
        {t.kind === 'flip' && t.state === 'holding' && <FlipControls t={t} n={n} />}
      </div>
    </li>
  )
}

/** A held flip's listing (the recap's, cut each hour, or the player's) and "Sell now". */
function FlipControls({ t, n }: { t: FlipTrade; n: number }) {
  const clock = useGameClock()
  const doc = useGameHour(clock.running || undefined).data
  const [edit, setEdit] = useState('')
  const [error, setError] = useState<string | null>(null)
  const id = useId()
  const listing = listingAt(t, n + 1)
  const lo = doc?.prices[t.item_id]?.[0]
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <form
        className="flex items-center gap-1.5"
        onSubmit={(e) => {
          e.preventDefault()
          const v = Number(edit)
          if (!(v > 0)) return setError('Enter a price in Chaos.')
          setGame(setListing(clock.s, t.id, v))
          setEdit('')
          setError(null)
        }}
      >
        <Tag aria-hidden className="size-4 text-accent" />
        <label htmlFor={id} className="text-muted">
          Listed at <span className="num text-text">{price(listing)}</span>
          {t.listing == null && <span className="text-faint"> (auto)</span>}
        </label>
        <input
          id={id}
          type="number"
          inputMode="decimal"
          min="0"
          step="any"
          placeholder="c each"
          value={edit}
          onChange={(e) => setEdit(e.target.value)}
          className="num min-h-8 w-20 rounded-md border border-border bg-bg px-2"
        />
        <button type="submit" className="min-h-8 cursor-pointer rounded-md border border-border px-2 text-muted hover:text-text">
          Set
        </button>
        {t.listing != null && (
          <button type="button" onClick={() => setGame(setListing(clock.s, t.id, null))} className="min-h-8 cursor-pointer px-1 text-xs text-muted hover:text-text">
            Auto
          </button>
        )}
      </form>
      <button
        type="button"
        disabled={!doc || lo == null}
        title={lo == null ? "It didn't trade this hour" : `At this hour's lowest trade, ${price(lo)} each`}
        onClick={() => {
          const next = doc ? quickSell(clock.s, doc, t.id) : 'Loading the hour.'
          if (typeof next === 'string') return setError(next)
          setGame(next)
        }}
        className="min-h-8 cursor-pointer rounded-md border border-accent/50 bg-accent/10 px-2.5 font-semibold text-accent-strong hover:bg-accent/20 disabled:cursor-default disabled:opacity-50"
      >
        Sell now{lo != null && <span className="num font-normal"> at {price(lo)}</span>}
      </button>
      {error && <span className="text-xs text-negative">{error}</span>}
    </div>
  )
}

function HistoryTable({ rows, launched }: { rows: Done[]; launched: string | null | undefined }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-surface text-left text-xs text-muted">
          <tr>
            <th className="px-3 py-2 text-right font-medium">Profit</th>
            <th className="px-3 py-2 text-right font-medium">In</th>
            <th className="px-3 py-2 text-right font-medium">Out</th>
            <th className="px-3 py-2 font-medium">Trade</th>
            <th className="px-3 py-2 font-medium">Placed</th>
            <th className="px-3 py-2 font-medium">Closed</th>
          </tr>
        </thead>
        <tbody>
          {[...rows].reverse().map((x) => {
            const gain = x.back - x.cost
            return (
              <tr key={x.id} className="border-t border-border">
                <td className={`num px-3 py-2 text-right font-semibold ${x.outcome === 'unfilled' ? 'text-faint' : tone(gain)}`}>{x.outcome === 'unfilled' ? '–' : signed(gain)}</td>
                <td className="num px-3 py-2 text-right">{div(x.cost)}</td>
                <td className="num px-3 py-2 text-right">{div(x.back)}</td>
                <td className="max-w-64 truncate px-3 py-2" title={tradeName(x)}>
                  {tradeName(x)}
                </td>
                <td className="px-3 py-2 whitespace-nowrap text-muted">{hourLabel(launched, x.at)}</td>
                <td className="px-3 py-2 whitespace-nowrap text-muted">
                  {OUTCOME[x.outcome]}, {hourLabel(launched, x.closed)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function StartOver() {
  const [sure, setSure] = useState(false)
  return sure ? (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span>Start over with {div(START_CASH)}? Your trades here are cleared.</span>
      <button type="button" onClick={() => setGame(EMPTY)} className="min-h-8 cursor-pointer rounded-md bg-negative/15 px-3 font-semibold text-negative hover:bg-negative/25">
        Start over
      </button>
      <button type="button" onClick={() => setSure(false)} className="min-h-8 cursor-pointer px-2 text-muted hover:text-text">
        Keep playing
      </button>
    </div>
  ) : (
    <button type="button" onClick={() => setSure(true)} className="inline-flex min-h-8 cursor-pointer items-center gap-1.5 self-start text-sm text-muted hover:text-negative">
      <RotateCcw aria-hidden className="size-4" /> Start over
    </button>
  )
}
