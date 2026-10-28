import { Clock } from 'lucide-react'
import type { DayHour } from '../api/client'
import { count, pct, price } from '../lib/format'
import {
  DEFAULT_BANDS,
  localHour,
  perHour,
  spreadOver,
  stackInMarkets,
  swing,
  tradingTime,
  type Bands,
  type ImpactBand,
  type MarketStack,
  type StackItem,
} from '../lib/impact'
import { lastDay } from '../lib/lastDay'
import type { Money } from '../lib/money'
import { Details } from './Opportunity'

// The stack seller and the best-hour sentence (findings 6 and 7), on the Price check page
// (docs/price-check.md).
// All sums run here (lib/impact), so a typed quantity costs no request.

export const DEFAULT_NOTE = "Hourly prices swing more than a stack moves them, so this shows how much of the market's trading your stack is, not a price drop."

const MARKET_NAME = { chaos: 'Chaos market', divine: 'Divine market' } as const

/** A band's edge in words: 0.25 → "15 minutes", 1 → "an hour". */
function bandEdge(hours: number) {
  if (hours === 1) return 'an hour'
  return hours < 1 ? `${Math.round(hours * 60)} minutes` : `${count(hours, 1)} hours`
}

/** The headline: what to do with the stack, in a few words. */
const ACTION: Record<ImpactBand, (hours: number) => string> = {
  low: () => 'Sell it as it is.',
  medium: () => 'List it a little at a time.',
  high: (hours) => `Split it and list it over ${spreadOver(hours)}.`,
}

/** The stack as hours of each market's trading (finding 7): the Chaos market first, since
 *  it carries most of an item's trading; the Divine market as its own hours. The headline
 *  says what to do; each market's card shows its hours and the stack's worth, with the
 *  rest behind Details. */
export function Stack({
  item,
  qty,
  bands = DEFAULT_BANDS,
  note = DEFAULT_NOTE,
  money,
  divineChaos,
  chaosOnly = false,
}: {
  item: StackItem & { name: string }
  qty: number
  bands?: Bands
  note?: string
  money: Money
  divineChaos: number | null | undefined
  /** Divine Orb: its one market is the Chaos one, so there is no Divine market card. */
  chaosOnly?: boolean
}) {
  const { chaos, divine } = stackInMarkets(item, qty, divineChaos, bands)
  const lead = chaos ?? divine
  // Only the case worth acting on: the same stack sells clearly faster for Divines.
  const faster = chaos && divine && divine.hours <= chaos.hours / 1.5 ? chaos.hours / divine.hours : null
  const noDivine = !item.divine?.volume_h
    ? "It hasn't traded against Divines lately, so the Chaos market is the only one."
    : 'Too few Divine trades to judge by.'
  return (
    <div className="flex flex-col gap-3">
      {lead && (
        <p className="text-sm" aria-live="polite">
          <span className="font-semibold text-accent">{ACTION[lead.band](lead.hours)}</span>{' '}
          <span className="text-muted">
            {count(qty)} {item.name} is <span className="num text-text">{tradingTime(lead.hours)}</span> of the {MARKET_NAME[lead.market]}'s trading
            {faster != null && `; it sells ${count(faster, faster < 10 ? 1 : 0)} times as fast in the Divine market`}.
          </span>
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <MarketCard name={MARKET_NAME.chaos} stack={chaos} qty={qty} bands={bands} money={money} missing="No recent Chaos trades to judge by." />
        {!chaosOnly && <MarketCard name={MARKET_NAME.divine} stack={divine} qty={qty} bands={bands} money={money} missing={noDivine} />}
      </div>
      <Details label="How this is worked out">
        <p className="text-xs text-muted">
          {note} Hours of trading: your stack over the units the market trades in a typical hour, last 3 days. Under {bandEdge(bands[0])} of trading it sells as it
          is; from {bandEdge(bands[1])} on, split it. The typical hourly swing is how far the price moves in an hour anyway.
        </p>
      </Details>
    </div>
  )
}

const BAND_TEXT: Record<ImpactBand, string> = {
  low: 'Sells as it is',
  medium: 'List it a little at a time',
  high: 'Split it',
}
const BAND_STEPS: ImpactBand[] = ['low', 'medium', 'high']

function MarketCard({
  name,
  stack,
  qty,
  bands,
  money,
  missing,
}: {
  name: string
  stack: MarketStack | null
  qty: number
  bands: Bands
  money: Money
  missing: string
}) {
  if (!stack)
    return (
      <section aria-label={name} className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4">
        <h3 className="font-semibold">{name}</h3>
        <p className="text-sm text-muted">{missing}</p>
      </section>
    )
  // The Divine market before there's a Divine rate: its own prices, in Divines. (A missing
  // price alone isn't that: it shows as a dash.)
  const inDivines = stack.market === 'divine' && stack.noRate
  const spread = stack.band === 'high' ? spreadOver(stack.hours) : null
  const each = stack.unit == null ? null : inDivines ? price(stack.unit, 'divine') : money(stack.unitChaos)
  const worth = stack.unit == null ? null : inDivines ? price(stack.unit * qty, 'divine') : money(stack.valueChaos)
  const thin = stack.hoursTraded != null && stack.hoursTraded < 0.5
  return (
    <section aria-label={name} className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-semibold">{name}</h3>
        <span className="num text-right text-xl font-semibold" title="Your stack, in this market's typical hours of trading">
          {tradingTime(stack.hours)}
        </span>
      </div>
      <div className="grid grid-cols-3 gap-1" role="img" aria-label={`Bands at ${bandEdge(bands[0])} and ${bandEdge(bands[1])} of trading: ${BAND_TEXT[stack.band]}`}>
        {BAND_STEPS.map((b) => (
          <span key={b} className={`h-1.5 rounded-full ${b === stack.band ? 'bg-accent' : 'bg-surface-2'}`} />
        ))}
      </div>
      <p className="text-sm text-muted">
        {BAND_TEXT[stack.band]}
        {spread && ` over ${spread}`}.
      </p>
      {/* A warning stays on the card, outside Details. */}
      {thin && <p className="text-xs text-muted">It trades in only {pct(stack.hoursTraded, 0)} of hours, so it may take a while to fill.</p>}
      <div className="mt-auto flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1 text-sm">
        {worth == null ? (
          <span className="text-xs text-muted">No recent price here, so the stack can't be valued in this market.</span>
        ) : (
          <>
            <span>
              <span className="text-muted">Worth </span>
              <span className="num font-semibold">{worth}</span>
            </span>
            <span className="num text-xs text-muted" title="The median of the market's hourly average prices over the last 24 hours, not a live price">
              {each} each
            </span>
          </>
        )}
      </div>
      <Details>
        <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-sm">
          <dt className="text-muted">Trades an hour</dt>
          <dd className="num text-right">{perHour(stack.volumeH)}</dd>
          <dt className="text-muted" title="The median of the market's hourly average prices over the last 24 hours, not a live price">
            Typical price, last 24 h
          </dt>
          <dd className="num text-right">{each == null ? '–' : `${each} each`}</dd>
          <dt className="text-muted">Typical hourly swing</dt>
          <dd className="num text-right">{swing(stack.sigmaH)}</dd>
        </dl>
        {inDivines && <p className="text-xs text-muted">There's no Divine price yet this league, so its prices are in Divines.</p>}
      </Details>
    </section>
  )
}

// --- Best hours ----------------------------------------------------------------------

/** The last 24 hours of the item's trading (the user: this league's last day, not past
 *  leagues): how much traded, the busiest hour and the highest-priced one, in local time. */
export function BestHours({
  rows,
  money,
  divineChaos,
  unit = 'divine',
}: {
  rows: DayHour[]
  money: Money
  divineChaos: number | null | undefined
  /** "chaos": Divine Orb's own view, priced in Chaos. */
  unit?: 'divine' | 'chaos'
}) {
  const d = lastDay(rows, divineChaos, unit)
  const dearest = d?.dearest
    ? d.unit === 'chaos'
      ? money(d.dearest.price)
      : divineChaos
        ? money(d.dearest.price * divineChaos)
        : price(d.dearest.price, 'divine')
    : null
  return (
    <section aria-label="Best time to sell" className="flex flex-col gap-3 rounded-lg border border-border bg-surface p-4">
      <h3 className="flex items-center gap-2 font-semibold">
        <Clock aria-hidden className="size-4 text-accent" /> Best time to sell, last 24 hours
      </h3>
      {!d ? (
        <p className="text-sm text-muted">Nothing traded in the last 24 hours.</p>
      ) : (
        <>
          {/* The two hours worth knowing, side by side; the totals and caveats behind Details. */}
          <dl className="grid grid-cols-2 gap-3">
            {d.busiest && (
              <div className="flex flex-col gap-0.5">
                <dt className="text-xs text-muted">Most traded, your time</dt>
                <dd className="num text-xl font-semibold">{localHour(d.busiest.hour)}</dd>
                <dd className="text-xs text-muted">
                  {count(d.busiest.units, 0)} traded that hour: a big stack sells most easily then.
                </dd>
              </div>
            )}
            {d.dearest && (
              <div className="flex flex-col gap-0.5">
                <dt className="text-xs text-muted">Highest price, your time</dt>
                <dd className="num text-xl font-semibold">{localHour(d.dearest.hour)}</dd>
                <dd className="text-xs text-muted">
                  <span className="num text-text">{dearest}</span> each
                  {d.dearest.over != null && d.dearest.over > 0 && <>, {pct(d.dearest.over, 1)} over the day's typical hour</>}.
                </dd>
              </div>
            )}
          </dl>
          {d.hours < 12 && <p className="text-xs text-muted">Only {d.hours} of the last 24 hours traded, so this is rough.</p>}
          <Details>
            <p className="text-sm text-muted">
              <span className="num text-text">{count(d.units, 0)}</span> traded{d.valueChaos != null && <> (about <span className="num text-text">{money(d.valueChaos)}</span>)</>}
              {d.divineUnits > 0 && d.chaosUnits > 0 && (
                <>
                  : {count(d.chaosUnits, 0)} for Chaos, {count(d.divineUnits, 0)} for Divines
                </>
              )}
              . Every one was both sold and bought: the exchange doesn't say which side started a trade.
            </p>
            <p className="text-xs text-faint">One day's trading, in your time zone: it can change from one day to the next.</p>
          </Details>
        </>
      )}
    </section>
  )
}
