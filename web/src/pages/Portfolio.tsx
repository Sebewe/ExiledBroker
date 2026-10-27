import { useQueries } from '@tanstack/react-query'
import { RotateCcw, SkipForward, StepForward, Trash2 } from 'lucide-react'
import { useCallback, useMemo, type ReactNode } from 'react'
import { Link } from 'react-router'
import { useLaunchPicks, usePriceCheck, useStatus } from '../api/queries'
import type { PreviewItemNext } from '../api/client'
import { ItemSearch } from '../components/ItemSearch'
import { LazyChart } from '../components/LazyChart'
import { Notice } from '../components/Notice'
import { PortfolioAdd } from '../components/PortfolioAdd'
import { Skeleton } from '../components/QueryState'
import { PageHeader, Section } from '../components/Section'
import { Stat } from '../components/Stat'
import { alpha, axisStyle, baseOptions, line, type ChartTokens } from '../lib/chartOptions'
import { pctTone, price, signedPct, utcHour } from '../lib/format'
import { atFor, DIVINE, hoursFrom, keptAsChaos, MAX_POSITIONS, MAX_STAKE, portfolio, usePortfolio, valueStake, type Position, type Valued } from '../lib/portfolio'
import { fetchPreview, previewKey, usePreview } from '../lib/preview'
import { queryFallback } from '../lib/queryFallback'
import { trackFeature } from '../lib/usage'

// The preview's paper portfolio (docs/preview.md, lib/portfolio.ts): stake Divines on a few
// items as the league stood at the end of the chosen day, step the clock forward hour by
// hour, and see what they'd be worth against keeping the Divines (or Chaos). Frontend only:
// it reads the snapshot's price paths, one cached document per item.

const div = (v: number | null | undefined) => price(v, 'divine')

/** Each item's path past the chosen day (and the Divine Orb's, for the Chaos yardstick). */
function useNexts(ids: string[], version: string | undefined) {
  return useQueries({
    queries: ids.map((id) => {
      const key = previewKey.itemNext(id)
      return { queryKey: ['preview', key, version], queryFn: () => fetchPreview<PreviewItemNext>(key, version), staleTime: Infinity }
    }),
  })
}

export default function Portfolio() {
  const status = useStatus()
  const preview = usePreview()
  if (!preview.on)
    return (
      <>
        <PageHeader title="Paper portfolio" />
        {queryFallback(status) ?? (
          <Notice kind="info" title="Part of the pre-launch preview">
            The paper portfolio let you try trades on a past league's early days before launch. The live league is on now: the{' '}
            <Link to="/" className="text-accent hover:text-accent-strong">
              Market recap
            </Link>{' '}
            has today's trades.
          </Notice>
        )}
      </>
    )
  return <Board />
}

function Board() {
  const preview = usePreview()
  const state = usePortfolio()
  const until = preview.manifest?.next_until
  const hours = useMemo(() => (preview.hour && until ? hoursFrom(preview.hour, until) : []), [preview.hour, until])
  const at = atFor(state, preview.day, hours.length)
  const ids = state.positions.map((p) => p.item_id)
  const nexts = useNexts([...ids, DIVINE], preview.version)
  const divineNext = nexts[ids.length]?.data
  const valued = state.positions.map((p, i) => {
    const q = nexts[i]!
    return { p, missing: !!q.error, pending: q.isPending, v: q.data ? valueStake(q.data, p.stake, hours) : undefined }
  })
  const loading = valued.some((x) => x.pending)

  // The total over the stakes that bought something: an item that hadn't traded by the
  // day's end keeps its Divines, so it's left out of both sides.
  const bought = valued.filter((x) => x.v?.entry)
  const staked = bought.reduce((s, x) => s + x.p.stake, 0)
  const total = hours.map((_, h) => (bought.length ? bought.reduce((s, x) => s + (x.v!.worth[h] ?? 0), 0) : null))
  const chaos = divineNext && staked ? keptAsChaos(divineNext, staked, hours) : hours.map(() => null)
  const now = total[at] ?? null
  const last = hours.length - 1
  const end = lastDay(preview.manifest?.launched_at, until)

  const step = (to: number) => {
    if (to > at) trackFeature('portfolio-step')
    portfolio.setAt(preview.day, Math.min(Math.max(0, to), last))
  }

  return (
    <>
      <PageHeader title="Paper portfolio">
        Stake Divines on a few items as {preview.manifest?.league} stood at the end of day {preview.day}, then step the clock forward and see what they'd be worth.
        Real prices, nothing traded: it's kept in this browser only.
      </PageHeader>
      <AddItems positions={state.positions} />
      {state.positions.length === 0 ? (
        <Notice kind="info" title="Nothing staked yet">
          Pick up to {MAX_POSITIONS} items above, or add them from{' '}
          <Link to={`/price-check?day=${preview.day}`} className="text-accent hover:text-accent-strong">
            Price check
          </Link>{' '}
          and the{' '}
          <Link to={`/launch?day=${preview.day}`} className="text-accent hover:text-accent-strong">
            Launch market
          </Link>
          . Each starts with {div(10)}; change it in the table.
        </Notice>
      ) : hours.length === 0 ? (
        <Skeleton rows={4} />
      ) : (
        <>
          <Clock at={at} hours={hours} day={preview.day} step={step} />
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Staked" value={div(staked || null)} />
            <Stat label={at === 0 ? 'Worth now' : `Worth after ${hoursLabel(at)}`} value={loading ? '…' : div(now)} />
            <Edge label="vs keeping the Divines" value={now != null && staked ? now / staked - 1 : null} />
            <Edge label="vs keeping it as Chaos" value={now != null && chaos[at] ? now / chaos[at]! - 1 : null} />
          </div>
          <Positions rows={valued} at={at} />
          {bought.length > 0 && <ValueChart hours={hours} at={at} total={total} staked={staked} chaos={chaos} day={preview.day} />}
          <p className="max-w-3xl text-xs text-faint">
            Prices are typical ones, the median of the 6 hours before each point, so one odd trade doesn't swing it. No spread or fees: a real trade would give up a
            little of every gain. {end != null && <>The preview's prices run to day {end}.</>}
          </p>
          <button
            type="button"
            onClick={() => portfolio.clear()}
            className="inline-flex min-h-8 cursor-pointer items-center gap-1.5 self-start text-sm text-muted hover:text-negative"
          >
            <Trash2 aria-hidden className="size-4" /> Empty the portfolio
          </button>
        </>
      )}
    </>
  )
}

/** The launch day the snapshot's paths end on (1-based, as the days are). */
function lastDay(launched: string | null | undefined, until: string | null | undefined) {
  if (!launched || !until) return null
  return Math.floor((Date.parse(until) - Date.parse(launched)) / 86_400_000) + 1
}

function hoursLabel(h: number) {
  if (h < 24) return `${h} h`
  const d = Math.floor(h / 24)
  const r = h % 24
  return r ? `${d} d ${r} h` : `${d} ${d === 1 ? 'day' : 'days'}`
}

function Edge({ label, value }: { label: string; value: number | null }) {
  return (
    <div className="rounded-lg border border-border bg-surface px-3 py-2.5 sm:px-4 sm:py-3">
      <div className="text-xs leading-snug text-muted">{label}</div>
      <div className={`num mt-1 text-xl font-semibold sm:text-2xl ${pctTone(value, 1)}`}>{signedPct(value, 1)}</div>
    </div>
  )
}

function AddItems({ positions }: { positions: Position[] }) {
  const preview = usePreview()
  const index = usePriceCheck(preview.league?.name)
  const board = useLaunchPicks()
  const held = new Set(positions.map((p) => p.item_id))
  const items = index.data?.items
  const options = useMemo(
    () =>
      (items ?? [])
        .filter((x) => x.item_id !== DIVINE && x.chaos != null)
        .sort((a, b) => (b.chaos ?? 0) * (b.volume_h ?? 0) - (a.chaos ?? 0) * (a.volume_h ?? 0) || a.name.localeCompare(b.name))
        .map((x) => ({ id: x.item_id, name: x.name, group: x.label ?? undefined })),
    [items],
  )
  const onChange = useCallback(
    (id: string) => {
      const item = options.find((o) => o.id === id)
      if (item && portfolio.add({ item_id: item.id, name: item.name })) trackFeature('portfolio-add')
    },
    [options],
  )
  // The Launch picks for the chosen day's window, as a place to start.
  const win = board.data?.find((w) => preview.day >= w.first_day && preview.day <= w.last_day)
  const picks = (win?.picks ?? []).filter((p) => !held.has(p.item_id) && p.item_id !== DIVINE).slice(0, 4)
  const full = positions.length >= MAX_POSITIONS
  return (
    <Section title="Pick your items" description={full ? `That's ${MAX_POSITIONS}: remove one to add another.` : undefined}>
      {!full && (
        <div className="max-w-xl">
          {queryFallback(index, 1) ?? <ItemSearch label="Add an item" options={options.filter((o) => !held.has(o.id))} value={undefined} onChange={onChange} placeholder="Type an item to stake on" />}
        </div>
      )}
      {!full && picks.length > 0 && (
        <div className="flex flex-wrap items-center gap-2 text-sm text-muted">
          <span>The day's Launch picks:</span>
          {picks.map((p) => (
            <span key={p.item_id} className="inline-flex items-center gap-1.5 rounded-md border border-border bg-surface py-0.5 pr-0.5 pl-2 text-text">
              {p.name}
              <PortfolioAdd item={p} compact />
            </span>
          ))}
        </div>
      )}
    </Section>
  )
}

function Clock({ at, hours, day, step }: { at: number; hours: string[]; day: number; step: (to: number) => void }) {
  const last = hours.length - 1
  const btn =
    'inline-flex min-h-9 cursor-pointer items-center gap-1.5 rounded-md border border-border bg-surface px-3 text-sm hover:border-accent/50 hover:text-accent disabled:cursor-not-allowed disabled:opacity-50'
  return (
    <section aria-label="The clock" className="flex flex-col gap-3 rounded-lg border border-accent/30 bg-accent/5 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <p className="text-sm text-muted">
          {at === 0 ? (
            <>
              Bought at the end of <strong className="font-semibold text-text">day {day}</strong>
            </>
          ) : (
            <>
              <strong className="font-semibold text-text">{hoursLabel(at)}</strong> after the end of day {day}
            </>
          )}{' '}
          <span className="num">({utcHour(hours[at])})</span>
        </p>
        {at === last && <span className="text-xs text-faint">That's as far as the preview goes.</span>}
      </div>
      <input
        type="range"
        min={0}
        max={last}
        value={at}
        onChange={(e) => step(Number(e.target.value))}
        aria-label="Hours after the day's end"
        className="w-full accent-accent"
      />
      <div className="flex flex-wrap gap-2">
        <Step className={btn} disabled={at >= last} onClick={() => step(at + 1)} icon={<StepForward aria-hidden className="size-4" />}>
          Next hour
        </Step>
        <Step className={btn} disabled={at >= last} onClick={() => step(at + 24)} icon={<SkipForward aria-hidden className="size-4" />}>
          Next day
        </Step>
        <Step className={btn} disabled={at === 0} onClick={() => step(0)} icon={<RotateCcw aria-hidden className="size-4" />}>
          Back to day {day}
        </Step>
      </div>
    </section>
  )
}

function Step({ className, disabled, onClick, icon, children }: { className: string; disabled: boolean; onClick: () => void; icon: ReactNode; children: ReactNode }) {
  return (
    <button type="button" className={className} disabled={disabled} onClick={onClick}>
      {icon}
      {children}
    </button>
  )
}

type Row = { p: Position; missing: boolean; pending: boolean; v: Valued | undefined }

function Positions({ rows, at }: { rows: Row[]; at: number }) {
  return (
    <div className="relative overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-sm">
        <thead className="bg-surface text-xs text-muted">
          <tr>
            <th className="px-2 py-2 sm:px-3 text-left font-medium">Item</th>
            <th className="px-2 py-2 text-right sm:px-3 font-medium">Worth</th>
            <th className="px-2 py-2 text-right sm:px-3 font-medium">Change</th>
            <th className="px-2 py-2 text-right sm:px-3 font-medium">Stake</th>
            <th className="hidden px-2 py-2 text-right sm:px-3 font-medium sm:table-cell">Bought at</th>
            <th className="hidden px-2 py-2 text-right sm:px-3 font-medium sm:table-cell">Price now</th>
            <th className="px-1 py-2">
              <span className="sr-only">Remove</span>
            </th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {rows.map((r) => (
            <PositionRow key={r.p.item_id} r={r} at={at} />
          ))}
        </tbody>
      </table>
    </div>
  )
}

function PositionRow({ r, at }: { r: Row; at: number }) {
  const { p, v } = r
  const worth = v?.worth[at] ?? null
  const change = worth != null ? worth / p.stake - 1 : null
  const priceNow = v?.entry && worth != null ? (worth / p.stake) * v.entry : null
  const note = r.missing ? "Not in the preview's data" : v && !v.entry ? "Hadn't traded by then: nothing bought" : null
  return (
    <tr>
      <td className="max-w-28 px-2 py-2 sm:max-w-48 sm:px-3">
        <div className="truncate font-medium" title={p.name}>
          {p.name}
        </div>
        {note && <div className="text-xs text-faint">{note}</div>}
      </td>
      <td className="num px-2 py-2 text-right sm:px-3 font-semibold">{r.pending ? '…' : div(worth)}</td>
      <td className={`num px-2 py-2 text-right sm:px-3 ${pctTone(change, 1)}`}>{signedPct(change, 1)}</td>
      <td className="px-2 py-2 text-right sm:px-3">
        <label className="inline-flex items-center gap-1">
          <span className="sr-only">Stake on {p.name}, in Divines</span>
          <input
            type="number"
            inputMode="decimal"
            min={1}
            max={MAX_STAKE}
            step={1}
            key={p.stake}
            defaultValue={p.stake}
            onBlur={(e) => {
              const stake = Number(e.target.value)
              if (stake > 0 && stake <= MAX_STAKE) portfolio.setStake(p.item_id, stake)
              else e.target.value = String(p.stake) // not a stake: put it back
            }}
            onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
            className="num w-14 rounded border border-border bg-bg px-1.5 py-0.5 text-right sm:w-16"
          />
          <span className="hidden text-xs text-faint sm:inline">div</span>
        </label>
      </td>
      <td className="num hidden px-2 py-2 text-right sm:px-3 text-muted sm:table-cell">{div(v?.entry)}</td>
      <td className="num hidden px-2 py-2 text-right sm:px-3 text-muted sm:table-cell">{div(priceNow)}</td>
      <td className="px-1 py-2 text-right">
        <button
          type="button"
          onClick={() => portfolio.remove(p.item_id)}
          aria-label={`Remove ${p.name}`}
          className="inline-flex size-8 cursor-pointer items-center justify-center rounded-md text-faint hover:bg-negative/10 hover:text-negative"
        >
          <Trash2 aria-hidden className="size-4" />
        </button>
      </td>
    </tr>
  )
}

function ValueChart({ hours, at, total, staked, chaos, day }: { hours: string[]; at: number; total: (number | null)[]; staked: number; chaos: (number | null)[]; day: number }) {
  // Drawn up to the clock only: what comes next stays hidden until it's stepped to.
  const build = useCallback(
    (t: ChartTokens) => {
      const upTo = <T,>(xs: T[]) => hours.slice(0, at + 1).map((h, i) => [h, xs[i] as number | null] as [string, number | null])
      const axis = axisStyle(t)
      const fmt = (v: number | null) => div(v)
      return {
        ...baseOptions(t),
        grid: { left: 8, right: 8, top: 56, bottom: 8, containLabel: true },
        xAxis: {
          type: 'time',
          min: hours[0],
          max: hours[hours.length - 1],
          ...axis,
          axisLabel: { ...axis.axisLabel, formatter: { day: '{d} {MMM}', hour: '{HH}:{mm}\n{d} {MMM}', minute: '{HH}:{mm}\n{d} {MMM}' } },
          splitLine: { show: false },
        },
        yAxis: { type: 'value', scale: true, ...axis, axisLabel: { ...axis.axisLabel, formatter: fmt } },
        series: [
          { ...line('Your portfolio', upTo(total)), color: t.accent, lineStyle: { width: 2 }, tooltip: { valueFormatter: fmt } },
          { ...line('Kept as Divines', upTo(hours.map(() => staked))), color: alpha(t.muted, 0.9), lineStyle: { width: 1.5, type: 'dashed' }, tooltip: { valueFormatter: fmt } },
          { ...line('Kept as Chaos', upTo(chaos)), color: alpha(t.faint, 0.9), lineStyle: { width: 1.5, type: 'dotted' }, tooltip: { valueFormatter: fmt } },
        ],
      }
    },
    [hours, at, total, staked, chaos],
  )
  return (
    <div className="rounded-lg border border-border bg-bg/40 p-3">
      <LazyChart build={build} height={260} label={`Your portfolio's worth in Divines from the end of day ${day}, against keeping the Divines or Chaos`} />
    </div>
  )
}
