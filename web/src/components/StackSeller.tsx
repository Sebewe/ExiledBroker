import { Clock } from 'lucide-react'
import type { FarmingHours, HourEffect } from '../api/client'
import { count, pct, price } from '../lib/format'
import {
  busiestHours,
  DEFAULT_BANDS,
  localHour,
  perHour,
  profileFor,
  spreadOver,
  stackInMarkets,
  swing,
  tradingTime,
  type Bands,
  type ImpactBand,
  type MarketStack,
  type StackItem,
} from '../lib/impact'
import type { Money } from '../lib/money'

// The stack seller and the best-hour sentence (findings 6 and 7), shared by the Price check
// page and the Farming page until that one is removed (docs/price-check.md, workstream E).
// All sums run here (lib/impact), so a typed quantity costs no request.

export const DEFAULT_NOTE = "Hourly prices swing more than a stack moves them, so this shows how much of the market's trading your stack is, not a price drop."

const MARKET_NAME = { chaos: 'Chaos market', divine: 'Divine market' } as const

/** A band's edge in words: 0.25 → "15 minutes", 1 → "an hour". */
function bandEdge(hours: number) {
  if (hours === 1) return 'an hour'
  return hours < 1 ? `${Math.round(hours * 60)} minutes` : `${count(hours, 1)} hours`
}

const LEAD: Record<ImpactBand, (hours: number) => string> = {
  low: () => 'it sells into the market as it is.',
  medium: () => "a large part of the hour's trading, so it may take a while to sell at this price.",
  high: (hours) => `an hour's trading or more, so split it and list it over ${spreadOver(hours)}.`,
}

/** The stack as hours of each market's trading (finding 7): the Chaos market first, since
 *  it carries most of an item's trading; the Divine market as its own hours. */
export function Stack({
  item,
  qty,
  bands = DEFAULT_BANDS,
  note = DEFAULT_NOTE,
  money,
  divineChaos,
}: {
  item: StackItem & { name: string }
  qty: number
  bands?: Bands
  note?: string
  money: Money
  divineChaos: number | null | undefined
}) {
  const { chaos, divine } = stackInMarkets(item, qty, divineChaos, bands)
  const lead = chaos ?? divine
  const longer = chaos && divine ? divine.hours / chaos.hours : null
  const noDivine = !item.divine?.volume_h
    ? "It hasn't traded against Divines lately, so the Chaos market is the only one."
    : 'Too few Divine trades to judge by.'
  return (
    <div className="flex flex-col gap-3">
      {lead && (
        <p className="text-sm" aria-live="polite">
          {count(qty)} {item.name} is <span className="num font-semibold">{tradingTime(lead.hours)}</span> of the {MARKET_NAME[lead.market]}'s trading:{' '}
          {LEAD[lead.band](lead.hours)}
          {longer != null && longer >= 1.5 && ` The Divine market trades less of it: the same stack is ${count(longer, longer < 10 ? 1 : 0)} times as long there.`}
          {longer != null && longer <= 1 / 1.5 && ` The Divine market trades ${count(1 / longer, longer > 0.1 ? 1 : 0)} times as much of it, so it sells faster there.`}
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-2">
        <MarketCard name={MARKET_NAME.chaos} stack={chaos} qty={qty} bands={bands} money={money} missing="No recent Chaos trades to judge by." />
        <MarketCard name={MARKET_NAME.divine} stack={divine} qty={qty} bands={bands} money={money} missing={noDivine} />
      </div>
      <p className="text-xs text-faint">
        {note} Hours of trading: your stack over the units the market trades in a typical hour, last 3 days. Under {bandEdge(bands[0])} of trading it sells as it
        is; from {bandEdge(bands[1])} on, split it. The typical hourly swing is how far the price moves in an hour anyway.
      </p>
    </div>
  )
}

const BAND_TEXT: Record<ImpactBand, string> = {
  low: 'Sells into the market as it is',
  medium: "A large part of the hour's trading: list it a little at a time",
  high: "An hour's trading or more: split it",
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
        {spread && `, and list it over ${spread}`}.
        {stack.hoursTraded != null && stack.hoursTraded < 0.5 && ` It trades in only ${pct(stack.hoursTraded, 0)} of hours, so it may take a while to fill.`}
      </p>
      <dl className="grid grid-cols-[1fr_auto] gap-x-3 gap-y-1 text-sm">
        <dt className="text-muted">Trades an hour</dt>
        <dd className="num text-right">{perHour(stack.volumeH)}</dd>
        <dt className="text-muted">Price now</dt>
        <dd className="num text-right">{stack.unit == null ? '–' : `${inDivines ? price(stack.unit, 'divine') : money(stack.unitChaos)} each`}</dd>
        <dt className="text-muted">The stack at that price</dt>
        <dd className="num text-right font-medium">
          {inDivines ? price(stack.unit == null ? null : stack.unit * qty, 'divine') : money(stack.valueChaos)}
        </dd>
        <dt className="text-muted">Typical hourly swing</dt>
        <dd className="num text-right">{swing(stack.sigmaH)}</dd>
      </dl>
      {stack.unit == null ? (
        <p className="text-xs text-muted">No recent price here, so the stack can't be valued in this market.</p>
      ) : (
        inDivines && <p className="text-xs text-muted">There's no Divine price yet this league, so its prices are in Divines.</p>
      )}
    </section>
  )
}

// --- Best hours ----------------------------------------------------------------------

const PHASE_TEXT: Record<FarmingHours['phase'], string> = { d0_2: 'days 0–2', d2_7: 'days 2–7', d7_14: 'days 7–14', later: 'later days' }

/** Finding 6 in a sentence or two (past leagues, for the league's phase): the busiest
 *  hours; the dearest ones when timing is worth it (the item's own mechanic's profile where
 *  it holds across leagues, else the pooled one); and when Divines are cheapest. */
export function BestHours({
  hours,
  mechanics = [],
  mechanicName = new Map(),
}: {
  hours: FarmingHours | null
  mechanics?: string[]
  mechanicName?: Map<string, string>
}) {
  const chosen = hours ? profileFor(hours, mechanics) : null
  const e = chosen && chosen.price.some((p) => p != null) ? chosen.effect : null
  const busy = busiestHours(hours?.volume)
  const own = chosen?.mechanic ? (mechanicName.get(chosen.mechanic) ?? chosen.mechanic) : null
  return (
    <div className="flex flex-col gap-2 rounded-lg border border-border bg-surface p-4">
      <h3 className="flex items-center gap-2 font-semibold">
        <Clock aria-hidden className="size-4 text-accent" /> Best time to sell
      </h3>
      {busy && (
        <p className="text-sm text-muted">
          {busy.ratio < 1.2 ? (
            'Trading is about as busy at every hour of the day.'
          ) : busy.ratio === Infinity ? (
            <>
              Trading is busiest from <span className="num text-text">{localHour(busy.start)}</span> to <span className="num text-text">{localHour(busy.end)}</span>{' '}
              your time: a big stack sells most easily then. Almost nothing trades from {localHour(busy.quietStart)} to {localHour(busy.quietEnd)}.
            </>
          ) : (
            <>
              Trading is busiest from <span className="num text-text">{localHour(busy.start)}</span> to <span className="num text-text">{localHour(busy.end)}</span>{' '}
              your time, {count(busy.ratio, 1)} times as busy as from {localHour(busy.quietStart)} to {localHour(busy.quietEnd)}: a big stack sells most easily then.
            </>
          )}
        </p>
      )}
      {!e || e.gain == null ? (
        <p className="text-sm text-muted">Not enough days of trades yet to tell which hours sell higher.</p>
      ) : e.verdict === 'small' || e.best == null ? (
        <p className="text-sm text-muted">
          Time of day barely matters{own ? ` for ${own}'s drops` : ''} on {PHASE_TEXT[hours!.phase]}: the best hour beats the day's average by about {pct(e.gain, 1)}.
          Sell whenever suits you.
        </p>
      ) : (
        <p className="text-sm text-muted">
          {own ? `${own}'s drops sell` : 'Prices run'} highest around <span className="num text-text">{localHour(e.best)}</span> your time: about {pct(e.gain, 1)} over
          the day's average{e.gap != null && e.worst != null && `, and ${pct(e.gap, 1)} over the lowest hour (${localHour(e.worst)})`}.
        </p>
      )}
      {hours && <ConvertHint e={hours.divine_effect} />}
      {hours && (
        <p className="text-xs text-faint">
          From {count(hours.leagues)} past {hours.leagues === 1 ? "league's" : "leagues'"} {PHASE_TEXT[hours.phase]} ({count(hours.days)} league-days), in your time zone.
        </p>
      )}
    </div>
  )
}

/** The Divine's own daily cycle: when Chaos buys the most Divines. */
function ConvertHint({ e }: { e: HourEffect }) {
  if (e.verdict !== 'worth_it' || e.best == null || e.worst == null || e.gap == null) return null
  return (
    <p className="text-sm text-muted">
      Converting to Divines? They're cheapest in Chaos around <span className="num text-text">{localHour(e.worst)}</span> your time and dearest around{' '}
      <span className="num text-text">{localHour(e.best)}</span>: about {pct(e.gap, 1)} apart.
    </p>
  )
}
