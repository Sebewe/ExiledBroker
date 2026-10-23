import { Check, FlaskConical, Minus, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { BacktestFlip, BacktestLaunch, BacktestLimit, BacktestReport } from '../api/client'
import { useBacktest, useStatus } from '../api/queries'
import { Notice } from '../components/Notice'
import { PageHeader, Section } from '../components/Section'
import { queryFallback } from '../lib/queryFallback'

// The backtest's write-up: every figure comes from the stored report (analysis/backtest.py,
// `eb backtest run`), so the page stays true when it's rebuilt with more leagues.

type Strategy = 'loops' | 'cards' | 'rising'
type Rule = 'top' | 'steady'
const WINDOWS: Record<string, string> = { day1: 'Day 1', days2_4: 'Days 2–4', days5_10: 'Days 5–10' }
const SEGMENT: Record<string, string> = { launch: 'first 14 days', late: 'latest 14 days' }

/** "+0.29" / "−1.50", Divines. */
function signed(x: number, digits = 2) {
  const s = Math.abs(x).toFixed(digits)
  return x > 0.005 ? `+${s}` : x < -0.005 ? `−${s}` : s
}
const times = (x: number | null | undefined) => (x == null ? '–' : `×${x.toFixed(2)}`)
const pctOf = (x: number) => `${Math.round(x * 100)}%`
/** Green above `even`, red below; grey when it would show as even (×1.00, +0.00). */
const tone = (x: number | null | undefined, even = 1) =>
  x == null || Math.abs(x - even) < 0.005 ? 'text-muted' : x > even ? 'text-positive' : 'text-negative'

function range(xs: number[], fmt: (x: number) => string) {
  if (!xs.length) return '–'
  const lo = Math.min(...xs)
  const hi = Math.max(...xs)
  return lo === hi ? fmt(lo) : `${fmt(lo)} to ${fmt(hi)}`
}

const perHour = (hs: { per_hour: number }[]) => hs.map((h) => h.per_hour)

export default function Backtest() {
  const status = useStatus()
  const report = useBacktest()
  const r = report.data?.[0]
  return (
    <>
      <PageHeader title="Backtest">
        Would following this site have paid? We replayed every hour of exchange data we have as a trader who does only what the site said at the time, an hour
        late, at fair prices and at the worst prices traded. Predicting a market from hourly summaries is hard, and most of what looks like free money doesn't
        survive the test. Here's what does.
      </PageHeader>
      {queryFallback(status) ??
        queryFallback(report) ??
        (!r ? (
          <Notice kind="waiting" title="No backtest yet">
            The backtest is built from past leagues' hours and appears here once it's been run.
          </Notice>
        ) : (
          <Report r={r} />
        ))}
    </>
  )
}

function Report({ r }: { r: BacktestReport }) {
  const day1 = r.launch.filter((l) => l.window_id === 'day1')
  // The best option tested for each strategy, over each league's first 14 days.
  const best = (strategy: string, method: string, fill: string) =>
    perHour(r.limits.filter((c) => c.strategy === strategy && c.method === method && c.fill === fill && c.segment === 'launch'))
  const a = r.assumptions
  return (
    <>
      <section aria-label="Verdict" className="flex flex-col gap-2">
        <h2 className="text-sm font-medium text-muted">The best option we tested for each strategy</h2>
        <div className="grid gap-3 md:grid-cols-2">
          <Verdict
            kind="pays"
            strategy="Hold for days · Launch picks"
            title="Buy the day-1 picks, sell in days 12–14"
            figure={range(
              day1.map((l) => l.harsh ?? 0),
              times,
            )}
            figureNote="what the basket came back as, in Divines, at harsh prices"
          >
            Spread your Divines across the day-1 list on Launch market. The typical affordable item fell to{' '}
            {range(
              day1.map((l) => l.typical_harsh ?? 0),
              times,
            )}{' '}
            over the same days; the picks, ranked only from earlier leagues, beat it in every league we tested.
          </Verdict>
          {r.flips.length > 0 && r.flip_settings && <FlipVerdict flips={r.flips} s={r.flip_settings} />}
          <Verdict
            kind="pays"
            strategy="Trade every hour · Loops"
            title="Limit orders, mid-range"
            figure={`${range(best('loops', 'limit_mid', 'touch'), signed)} div/h`}
            figureNote={`if a trade past the order fills it; ${range(best('loops', 'limit_mid', 'strict'), signed)} if the hour's average has to cross it`}
          >
            Bid halfway up the latest hour's price range for the item, and ask three quarters up its range in the other currency. The worst case, caught at the
            worst price both hours, made {range(best('loops', 'market', 'touch'), signed)} div/h.
          </Verdict>
          <Verdict
            kind="even"
            strategy="Trade every hour · Card turn-ins"
            title="Limit orders at the low"
            figure={`${range(best('cards', 'limit', 'touch'), signed)} div/h`}
            figureNote={`if a trade past the order fills it; ${range(best('cards', 'limit', 'strict'), signed)} if the hour's average has to cross it`}
          >
            Bid the card's lowest price from the latest hour, only if a set still pays at the reward's lowest, and ask the reward's average. Few orders fill, so
            the true figure is uncertain. The worst case made {range(best('cards', 'market', 'touch'), signed)} div/h.
          </Verdict>
        </div>
      </section>

      <Section title="How we tested">
        <ul className="grid max-w-4xl gap-2 text-sm text-muted sm:grid-cols-2">
          <Assumption label="The trader">
            starts with {a.bank_divines} Divines and acts on the top {a.top} picks each hour, at most {a.trade_divines} Divines a trade.
          </Assumption>
          <Assumption label="An hour late">
            GGG publishes an hour only after it ends, so every pick from hour H is traded in hour H+1 at H+1's prices. A pick that didn't trade then isn't filled.
          </Assumption>
          <Assumption label="Small fills">
            at most {pctOf(a.capture)} of what actually traded that hour, in whole items, so one trader never takes the whole market.
          </Assumption>
          <Assumption label="Fair prices">
            the hour's average traded price, losing {pctOf(a.slippage)} on every trade (a loop has three).
          </Assumption>
          <Assumption label="Harsh prices">
            the hour's worst traded price for the trader: buying at the highest, selling at the lowest. For launch picks, the median hourly high to buy and low to
            sell.
          </Assumption>
          <Assumption label="Lost if unsold">
            a card's reward or a riser that doesn't trade within 6 hours of when it's meant to be sold counts as a total loss.
          </Assumption>
        </ul>
        <p className="max-w-3xl text-sm text-muted">
          The hours: each challenge league's first 14 days since the exchange arrived ({r.leagues.join(', ')}), plus the live league's latest 14 days. Real fills
          land somewhere between fair and harsh: hourly data has no order book, so the spread a trader crosses can't be seen. We only call something advice if it
          holds up harsh.
        </p>
      </Section>

      <LaunchSection launch={r.launch} />
      {r.flips.length > 0 && r.flip_settings && <FlipSection flips={r.flips} s={r.flip_settings} />}
      <HourlySection r={r} />
      <LimitSection limits={r.limits} />

      <Section title="What to do with this">
        <ol className="flex max-w-3xl list-decimal flex-col gap-2 pl-5 text-sm leading-relaxed text-muted marker:text-accent">
          <li>
            <span className="text-text">Buy the day-1 launch picks and sell them in days 12–14.</span> It's where the money is, because it rides the league's
            biggest move instead of an hour's spread. Spread your Divines across the list: a single pick can fall. See{' '}
            <Link to="/launch" className="text-accent hover:text-accent-strong">
              Launch market
            </Link>
            .
          </li>
          <li>
            <span className="text-text">Flip volatile items with patience.</span> Bid low in the hour's range on the recap's most volatile liquid items,
            list high and cut the ask about 1% an hour until it sells. A bid that doesn't fill costs nothing: cancel it. It needs a busy market to fill, so it
            should work best in a league's first days.
          </li>
          <li>
            <span className="text-text">Later launch windows pay less.</span> Days 2–4 still beat the typical item; days 5–10 is close to break-even at harsh prices.
          </li>
          <li>
            <span className="text-text">For loops, put in orders instead of buying at the market.</span> Bid about halfway up the last hour's price range for the
            item, and ask about three quarters up its range in the other currency. Without orders, only run a loop that paid every hour (the badge on the
            3-hour recap). Either way, expect under a Divine an hour.
          </li>
          <li>
            <span className="text-text">For card turn-ins, use limit orders, not market buys.</span> Bid for cards at the last hour's lowest price, only if a set
            still pays at the reward's lowest price, and ask the last hour's average for the reward. Many orders won't fill, and the ones that do are the
            whole edge; the worst case, caught at the worst price both hours, lost money in every launch fortnight.
          </li>
          <li>
            <span className="text-text">Don't chase the Rising list.</span> It tells you what already happened.
          </li>
        </ol>
      </Section>

      <Section title="Caveats">
        <ul className="flex max-w-3xl list-disc flex-col gap-1.5 pl-5 text-sm text-muted">
          <li>One trader, small sizes. Many people following the same picks would move the prices against each other.</li>
          <li>
            Items and cards are today's core pool and loot-filter list, a small head start the trader wouldn't have had. The picks' rankings use only earlier
            leagues.
          </li>
          <li>
            {r.leagues.length} leagues is a small sample, and every league is different. The first leagues had fewer earlier leagues to rank picks from.
          </li>
        </ul>
        <p className="text-xs text-faint">Built {new Date(r.built_at).toUTCString().replace(' GMT', ' UTC')}.</p>
      </Section>
    </>
  )
}

const VERDICT = {
  pays: { icon: Check, cls: 'border-positive/40 bg-positive/5', iconCls: 'bg-positive/15 text-positive', fig: 'text-positive' },
  even: { icon: Minus, cls: 'border-border bg-surface', iconCls: 'bg-surface-2 text-muted', fig: 'text-text' },
  loses: { icon: X, cls: 'border-negative/40 bg-negative/5', iconCls: 'bg-negative/15 text-negative', fig: 'text-negative' },
}

function Verdict({
  kind,
  strategy,
  title,
  figure,
  figureNote,
  children,
}: {
  kind: keyof typeof VERDICT
  strategy: string
  title: string
  figure: string
  figureNote: string
  children: ReactNode
}) {
  const v = VERDICT[kind]
  const Icon = v.icon
  return (
    <div className={`flex flex-col gap-2 rounded-xl border p-4 ${v.cls}`}>
      <p className="text-[11px] font-semibold tracking-wide text-faint uppercase">{strategy}</p>
      <h3 className="flex items-center gap-2 font-semibold">
        <span className={`grid size-6 place-items-center rounded-full ${v.iconCls}`}>
          <Icon aria-hidden className="size-3.5" />
        </span>
        {title}
      </h3>
      <div>
        <p className={`num text-2xl font-semibold tracking-tight ${v.fig}`}>{figure}</p>
        <p className="text-xs text-faint">{figureNote}</p>
      </div>
      <p className="text-sm text-muted">{children}</p>
    </div>
  )
}

function Assumption({ label, children }: { label: string; children: ReactNode }) {
  return (
    <li className="rounded-lg border border-border bg-surface px-3 py-2">
      <span className="font-medium text-text">{label}:</span> {children}
    </li>
  )
}

function Table({ caption, head, children }: { caption: string; head: string[]; children: ReactNode }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full min-w-[34rem] text-sm">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-surface-2 text-xs text-muted">
          <tr>
            {head.map((h, i) => (
              <th key={h} scope="col" className={`px-3 py-2 font-medium ${i === 0 ? 'text-left' : 'text-right'}`}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border">{children}</tbody>
      </table>
    </div>
  )
}

function LaunchSection({ launch }: { launch: BacktestLaunch[] }) {
  const latest = launch.filter((l) => l.window_id === 'day1').at(-1)
  return (
    <Section
      title="Launch picks, league by league"
      description="Each league traded with the picks ranked from the leagues before it only, 10 Divines a pick (less where 10% of the market couldn't take it), held in Divines until days 12–14."
    >
      <Table caption="Launch picks backtest" head={['League · buy window', 'Fair', 'Harsh', 'Typical item, harsh', 'Profit, harsh']}>
        {launch.map((l) => (
          <tr key={`${l.league}-${l.window_id}`}>
            <td className="px-3 py-2">
              {l.league} <span className="text-muted">· {WINDOWS[l.window_id] ?? l.window_id}</span>
            </td>
            <td className={`num px-3 py-2 text-right ${tone(l.fair)}`}>{times(l.fair)}</td>
            <td className={`num px-3 py-2 text-right font-medium ${tone(l.harsh)}`}>{times(l.harsh)}</td>
            <td className={`num px-3 py-2 text-right ${tone(l.typical_harsh)}`}>{times(l.typical_harsh)}</td>
            <td className={`num px-3 py-2 text-right ${tone(l.harsh_profit, 0)}`}>
              {signed(l.harsh_profit, 0)} div <span className="text-faint">on {l.staked.toFixed(0)}</span>
            </td>
          </tr>
        ))}
      </Table>
      {latest && (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">
            {latest.league}'s day-1 picks <span className="font-normal text-muted">(ranked from {latest.references.join(', ')})</span>
          </h3>
          <ol className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
            {latest.picks.map((p) => (
              <li key={p.rank} className="flex items-center justify-between gap-2 rounded-lg border border-border bg-surface px-3 py-2">
                <span className="min-w-0 truncate text-sm" title={p.name}>
                  <span className="num text-faint">{p.rank}.</span> {p.name}
                </span>
                <span className={`num text-sm font-medium ${tone(p.harsh)}`} title={`fair ${times(p.fair)}`}>
                  {times(p.harsh)}
                </span>
              </li>
            ))}
          </ol>
          <p className="text-xs text-faint">Harsh multiples, in Divines; hover for fair. Not every pick wins: the spread is what makes the list pay.</p>
        </div>
      )}
    </Section>
  )
}

const STRATEGIES: { strategy: Strategy; rule: Rule; name: string; what: string }[] = [
  { strategy: 'loops', rule: 'top', name: 'Loops, top 3', what: 'the 1-hour recap’s best loops' },
  { strategy: 'loops', rule: 'steady', name: 'Loops, steady', what: 'only loops that paid every hour of the last 3' },
  { strategy: 'cards', rule: 'top', name: 'Card turn-ins, top 3', what: 'buy full sets, turn in, sell the reward the hour after' },
  { strategy: 'cards', rule: 'steady', name: 'Card turn-ins, steady', what: 'only cards that paid every hour of the last 3' },
  { strategy: 'rising', rule: 'top', name: 'Rising, top 3', what: 'buy the biggest risers, sell 2 hours later' },
  { strategy: 'rising', rule: 'steady', name: 'Rising, steady', what: 'only items that rose every hour of the last 3' },
]

function HourlySection({ r }: { r: BacktestReport }) {
  const segments = r.hourly.filter((h) => h.strategy === 'loops' && h.rule === 'top' && h.scenario === 'fair')
  const flagged = r.persistence.map((p) => p.flagged).filter((x): x is number => x != null)
  const others = r.persistence.map((p) => p.others).filter((x): x is number => x != null)
  const cell = (s: (typeof STRATEGIES)[number], league: string, segment: string) => {
    const find = (scenario: string) =>
      r.hourly.find((h) => h.strategy === s.strategy && h.rule === s.rule && h.scenario === scenario && h.league === league && h.segment === segment)
    return { fair: find('fair'), harsh: find('harsh') }
  }
  return (
    <Section
      title="Market recap, hour by hour"
      description="Divines an hour, harsh (fair below), for a trader acting on the recap every hour. Green made money, red lost it."
    >
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[46rem] text-sm">
          <caption className="sr-only">Hourly strategies backtest</caption>
          <thead className="bg-surface-2 text-xs text-muted">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">
                Strategy
              </th>
              {segments.map((h) => (
                <th key={h.league + h.segment} scope="col" className="px-3 py-2 text-right font-medium">
                  {h.league}
                  <span className="block font-normal text-faint">{SEGMENT[h.segment] ?? h.segment}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {STRATEGIES.map((s) => (
              <tr key={s.strategy + s.rule}>
                <th scope="row" className="px-3 py-2 text-left font-normal">
                  <span className="text-text">{s.name}</span>
                  <span className="block text-xs text-faint">{s.what}</span>
                </th>
                {segments.map((h) => {
                  const c = cell(s, h.league, h.segment)
                  return (
                    <td key={h.league + h.segment} className="px-3 py-2 text-right" title={c.harsh ? `${c.harsh.filled} trades, ${c.harsh.won} won (harsh)` : ''}>
                      <span className={`num block font-medium ${tone(c.harsh?.per_hour, 0)}`}>{c.harsh ? signed(c.harsh.per_hour) : '–'}</span>
                      <span className={`num block text-xs ${tone(c.fair?.per_hour, 0)}`}>{c.fair ? signed(c.fair.per_hour) : '–'}</span>
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Finding icon={<FlaskConical aria-hidden className="size-4 text-accent" />} title="The recap does spot something">
          A loop it flags pays again the next hour {range(flagged, pctOf)} of the time, against {range(others, pctOf)} for every other loop that traded. But when it
          doesn't pay again, buying at the hour's worst price costs more than the wins bring in.
        </Finding>
        <Finding icon={<FlaskConical aria-hidden className="size-4 text-accent" />} title="Fair prices flatter loops">
          Even unflagged items often look a few percent cheaper in Chaos than in Divines on average. That's most likely the gap between buyers and sellers, which a
          trader pays rather than collects, so treat the fair figures above as a ceiling.
        </Finding>
      </div>
    </Section>
  )
}

function Finding({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5 rounded-lg border border-border bg-surface p-4">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        {icon}
        {title}
      </h3>
      <p className="text-sm text-muted">{children}</p>
    </div>
  )
}

// The orders compared, one row each (analysis/backtest.LIMIT_ORDERS).
const ORDERS: { strategy: string; method: string; name: string; what: string }[] = [
  { strategy: 'cards', method: 'market', name: 'Cards, worst case', what: 'caught at the worst price both hours: sets bought at the next hour’s highest, the reward sold at its lowest' },
  {
    strategy: 'cards',
    method: 'limit',
    name: 'Cards, limit orders',
    what: 'bid the recap hour’s lowest card price if the set still pays at the reward’s lowest; ask the reward’s average',
  },
  { strategy: 'loops', method: 'market', name: 'Loops, worst case', what: 'caught at the worst price both hours: bought at the next hour’s highest, sold the hour after at the lowest' },
  { strategy: 'loops', method: 'limit', name: 'Loops, limit orders at the low', what: 'bid the recap hour’s lowest price; ask its average in the other currency' },
  {
    strategy: 'loops',
    method: 'limit_mid',
    name: 'Loops, limit orders mid-range',
    what: 'bid halfway up the recap hour’s range; ask three quarters up the other currency’s',
  },
]
type Order = (typeof ORDERS)[number]

const pick = (limits: BacktestLimit[], o: Order, fill: string) => limits.filter((c) => c.strategy === o.strategy && c.method === o.method && c.fill === fill)

function fills(limits: BacktestLimit[], o: Order, fill: string) {
  const rs = pick(limits, o, fill)
  return { placed: rs.reduce((s, c) => s + c.signals, 0), filled: rs.reduce((s, c) => s + c.filled, 0) }
}

const filledShare = (f: { placed: number; filled: number }) => (f.placed ? pctOf(f.filled / f.placed) : '–')
const launchHours = (limits: BacktestLimit[], o: Order, fill: string) => perHour(pick(limits, o, fill).filter((c) => c.segment === 'launch'))

/** Cards and loops traded with orders priced from the recap's hour: a row per way of
 *  ordering, a column per league; each cell the result if a trade past the order fills
 *  it, and below it the result if the hour's average has to cross it. */
function LimitSection({ limits }: { limits: BacktestLimit[] }) {
  if (!limits.length) return null
  const segments = limits.filter((c) => c.strategy === 'cards' && c.method === 'market')
  const find = (o: Order, fill: string, league: string, segment: string) =>
    pick(limits, o, fill).find((c) => c.league === league && c.segment === segment)
  const [cardsMarket, cardsLimit, loopsMarket, , loopsMid] = ORDERS as [Order, Order, Order, Order, Order]
  return (
    <Section
      title="Limit orders"
      description="The recap's top card turn-ins and loops again, with orders priced from the recap's own hour instead of whatever the next hour asks. Divines an hour: on top if any trade past the order fills it, below if the hour's average has to cross it. Unsold items count as lost; orders that don't fill cost nothing."
    >
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[48rem] text-sm">
          <caption className="sr-only">Card turn-ins and loops with limit orders</caption>
          <thead className="bg-surface-2 text-xs text-muted">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">
                Orders
              </th>
              {segments.map((h) => (
                <th key={h.league + h.segment} scope="col" className="px-3 py-2 text-right font-medium">
                  {h.league}
                  <span className="block font-normal text-faint">{SEGMENT[h.segment] ?? h.segment}</span>
                </th>
              ))}
              <th scope="col" className="px-3 py-2 text-right font-medium" title="Orders that filled, of all placed">
                Filled
              </th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {ORDERS.map((o) => {
              const market = o.method === 'market'
              return (
                <tr key={o.strategy + o.method}>
                  <th scope="row" className="px-3 py-2 text-left font-normal">
                    <span className="text-text">{o.name}</span>
                    <span className="block text-xs text-faint">{o.what}</span>
                  </th>
                  {segments.map((h) => {
                    const touch = find(o, 'touch', h.league, h.segment)
                    const strict = market ? undefined : find(o, 'strict', h.league, h.segment)
                    return (
                      <td
                        key={h.league + h.segment}
                        className="px-3 py-2 text-right"
                        title={[touch, strict]
                          .filter((c) => c)
                          .map((c) => `${c!.filled} of ${c!.signals} orders filled, ${c!.won} won (${c!.fill})`)
                          .join('; ')}
                      >
                        <span className={`num block font-medium ${tone(touch?.per_hour, 0)}`}>{touch ? signed(touch.per_hour) : '–'}</span>
                        {strict && <span className={`num block text-xs ${tone(strict.per_hour, 0)}`}>{signed(strict.per_hour)}</span>}
                      </td>
                    )
                  })}
                  <td className="num px-3 py-2 text-right text-muted">
                    <span className="block">{filledShare(fills(limits, o, 'touch'))}</span>
                    {!market && <span className="block text-xs">{filledShare(fills(limits, o, 'strict'))}</span>}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Finding icon={<FlaskConical aria-hidden className="size-4 text-accent" />} title="Price from the last hour's range, not the market">
          The worst case lost for both in every launch fortnight ({range(launchHours(limits, cardsMarket, 'touch'), signed)} div/h for cards,{' '}
          {range(launchHours(limits, loopsMarket, 'touch'), signed)} for loops). Cards did best bidding at the hour's low and asking the reward's average (
          {range(launchHours(limits, cardsLimit, 'touch'), signed)}). Loops did best bidding mid-range ({range(launchHours(limits, loopsMid, 'touch'), signed)}
          ), and were the only orders that still made money when the hour's average had to cross them ({range(launchHours(limits, loopsMid, 'strict'), signed)}).
        </Finding>
        <Finding icon={<FlaskConical aria-hidden className="size-4 text-accent" />} title="Whether the orders fill is the open question">
          Hourly data shows each hour's range, not the queue at each price, so the two figures bracket it. The mid-range loop orders were picked from a grid of
          bid and ask levels on Mirage and Allflame, then checked on the other leagues, where they held up but earned less. Cards' best settings didn't beat the
          simple ones.
        </Finding>
      </div>
    </Section>
  )
}

const FLIP_MODELS: { model: string; name: string; what: string }[] = [
  { model: 'touch', name: 'One trade past your price fills you', what: 'the most optimistic: the hour’s lowest and highest trades are yours to take' },
  { model: 'even', name: 'Volume spread evenly over the range', what: 'you get the share of the hour’s trading past your price' },
  { model: 'peaked', name: 'Volume peaked at the average', what: 'the same, with most trades near the hour’s average' },
  { model: 'strict', name: 'The hour’s average must cross your price', what: 'the most cautious: fills only when the typical trade reaches you' },
]

/** Pooled over leagues: bids filled, the share of those that made money, profit over
 *  capital put in, and the middle league's hours to sell out. */
function pooled(flips: BacktestFlip[], model: string) {
  const rs = flips.filter((f) => f.model === model)
  const bought = rs.reduce((n, f) => n + f.bought, 0)
  const tried = rs.reduce((n, f) => n + f.tried, 0)
  const invested = rs.reduce((n, f) => n + f.invested, 0)
  const won = bought ? rs.reduce((n, f) => n + (f.won ?? 0) * f.bought, 0) / bought : null
  const dumped = bought ? rs.reduce((n, f) => n + (f.dumped ?? 0) * f.bought, 0) / bought : null
  const hours = rs.map((f) => f.median_hours).filter((h): h is number => h != null).sort((a, b) => a - b)
  return {
    rs,
    bought,
    tried,
    won,
    dumped,
    ret: invested ? rs.reduce((n, f) => n + f.profit, 0) / invested : null,
    hours: hours.length ? hours[Math.floor(hours.length / 2)]! : null,
  }
}

const signedPct = (x: number | null | undefined) => (x == null ? '–' : `${x > 0 ? '+' : x < 0 ? '−' : ''}${Math.abs(x * 100).toFixed(1)}%`)

function FlipVerdict({ flips, s }: { flips: BacktestFlip[]; s: NonNullable<BacktestReport['flip_settings']> }) {
  const strict = pooled(flips, 'strict')
  const touch = pooled(flips, 'touch')
  const won = FLIP_MODELS.map((m) => pooled(flips, m.model).won).filter((w): w is number => w != null)
  return (
    <Verdict
      kind="pays"
      strategy="List and wait · Volatile flips"
      title={`Bid low, list high, cut the ask ${pctOf(s.cut)} an hour`}
      figure={`${signedPct(strict.ret)} to ${signedPct(touch.ret)} a trade`}
      figureNote="from the strictest fill rule (the hour's average must cross your price) to the most optimistic (one trade past it fills you)"
    >
      On the recap's most volatile liquid items, in the Chaos market: bid {pctOf(s.bid_at)} of the way up the hour's range, list at {pctOf(s.ask_at)}, in
      whole Chaos for whole numbers of items as the exchange takes them. A bid that doesn't fill costs nothing: cancel it and keep your Divines. Of the bids that filled, {range(won, pctOf)} sold at a profit. How often bids fill is the open question:{' '}
      {pctOf(strict.bought / (strict.tried || 1))} to {pctOf(touch.bought / (touch.tried || 1))} here, and a league launch's busier market should fill more.
    </Verdict>
  )
}

function FlipSection({ flips, s }: { flips: BacktestFlip[]; s: NonNullable<BacktestReport['flip_settings']> }) {
  const leagues = [...new Set(flips.map((f) => f.league))]
  return (
    <Section
      title="Volatile flips, with patience"
      description={`${s.entries} random hours in each league's first 14 days. Each time, the recap's top ${s.top} volatile items in the Chaos market (at least ${Math.round(s.min_volume / 1000)}k Chaos traded that hour, a range of ${s.min_range != null ? `${pctOf(s.min_range)}–` : 'at most '}${pctOf(s.max_range)}), ordered in whole Chaos for lots of up to ${s.lot_max ?? 1} items and filled lot by lot: bid ${pctOf(s.bid_at)} up the hour's range, filled the next hour or cancelled; listed at ${pctOf(s.ask_at)} up from the hour after, the ask cut ${pctOf(s.cut)} every hour it doesn't sell, and what's left after ${s.max_hold} hours dumped at the low. At most ${s.trade_divines} Divines and ${pctOf(s.capture)} of the hour's trading a position.`}
    >
      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[52rem] text-sm">
          <caption className="sr-only">Volatile flips under each fill model</caption>
          <thead className="bg-surface-2 text-xs text-muted">
            <tr>
              <th scope="col" className="px-3 py-2 text-left font-medium">
                If fills work like this
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                Bids filled
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                Sold at a profit
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                Return a trade
              </th>
              <th scope="col" className="px-3 py-2 text-right font-medium">
                Hours to sell
              </th>
              {leagues.map((l) => (
                <th key={l} scope="col" className="px-3 py-2 text-right font-medium">
                  {l}
                </th>
              ))}
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {FLIP_MODELS.map((m) => {
              const p = pooled(flips, m.model)
              return (
                <tr key={m.model}>
                  <th scope="row" className="px-3 py-2 text-left font-normal">
                    <span className="text-text">{m.name}</span>
                    <span className="block text-xs text-faint">{m.what}</span>
                  </th>
                  <td className="num px-3 py-2 text-right text-muted" title={`${p.bought} of ${p.tried} bids`}>
                    {pctOf(p.bought / (p.tried || 1))}
                  </td>
                  <td className="num px-3 py-2 text-right">{p.won == null ? '–' : pctOf(p.won)}</td>
                  <td className={`num px-3 py-2 text-right font-medium ${tone(p.ret, 0)}`}>{signedPct(p.ret)}</td>
                  <td className="num px-3 py-2 text-right text-muted" title={p.dumped ? `${pctOf(p.dumped)} dumped unsold` : ''}>
                    {p.hours ?? '–'}
                  </td>
                  {leagues.map((l) => {
                    const f = p.rs.find((x) => x.league === l)
                    return (
                      <td
                        key={l}
                        className={`num px-3 py-2 text-right ${tone(f?.overall_return, 0)}`}
                        title={f ? `${f.bought} of ${f.tried} bids filled` : ''}
                      >
                        {f?.bought ? signedPct(f.overall_return) : '–'}
                      </td>
                    )
                  })}
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <Finding icon={<FlaskConical aria-hidden className="size-4 text-accent" />} title="Why it can work, and what it risks">
          The volatility lasts: the picks' hourly range barely shrinks over the next day, so the hour's delay before the data is published costs little. A bid
          that doesn't fill is cancelled and costs nothing, and a filled one is usually sold within hours at the first ask. The risk is a position that doesn't
          sell: the ask comes down every hour, and after {s.max_hold} hours what's left is sold at the low. Cutting faster than 1–2% an hour gave the gain away.
        </Finding>
        <Finding icon={<FlaskConical aria-hidden className="size-4 text-accent" />} title="The open question: are the hour's extremes real trades?">
          Hourly data shows each hour's average, lowest and highest trade, not how much traded at each price, and it isn't confirmed whether the lowest and
          highest are executed trades or listings. If they're trades in any size, this is the best hourly strategy we tested. If not, it's the bottom row:
          few fills, slow sales, and not every league ahead. A launch's busy market is the time to try it with small orders.
        </Finding>
      </div>
    </Section>
  )
}
