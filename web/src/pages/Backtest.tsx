import { Check, FlaskConical, Minus, X } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router'
import type { BacktestHourly, BacktestLaunch, BacktestReport } from '../api/client'
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
const tone = (x: number | null | undefined, even = 1) =>
  x == null ? 'text-muted' : x > even * 1.0001 ? 'text-positive' : x < even * 0.9999 ? 'text-negative' : 'text-muted'

function range(xs: number[], fmt: (x: number) => string) {
  if (!xs.length) return '–'
  const lo = Math.min(...xs)
  const hi = Math.max(...xs)
  return lo === hi ? fmt(lo) : `${fmt(lo)} to ${fmt(hi)}`
}

function rows(r: BacktestReport, strategy: Strategy, rule: Rule, scenario: 'fair' | 'harsh') {
  return r.hourly.filter((h) => h.strategy === strategy && h.rule === rule && h.scenario === scenario)
}

const perHour = (hs: BacktestHourly[]) => hs.map((h) => h.per_hour)

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
  const steady = rows(r, 'loops', 'steady', 'harsh')
  const top = rows(r, 'loops', 'top', 'harsh')
  const cards = [...rows(r, 'cards', 'top', 'harsh'), ...rows(r, 'cards', 'steady', 'harsh')]
  const rising = [...rows(r, 'rising', 'top', 'fair'), ...rows(r, 'rising', 'steady', 'fair')]
  const a = r.assumptions
  return (
    <>
      <section aria-label="Verdict" className="grid gap-3 md:grid-cols-3">
        <Verdict
          kind="pays"
          title="Launch picks pay"
          figure={range(
            day1.map((l) => l.harsh ?? 0),
            times,
          )}
          figureNote="what day-1 picks came back as, harsh, by days 12–14"
        >
          The typical affordable item fell to {range(day1.map((l) => l.typical_harsh ?? 0), times)} over the same days. Picks ranked only from earlier leagues beat it in
          every league we tested.
        </Verdict>
        <Verdict kind="even" title="Steady loops pay a little" figure={`${range(perHour(steady), signed)} div/h`} figureNote="harsh, loops that paid every hour of the last 3">
          Pocket change, not a few Divines an hour. Acting on every loop the recap shows makes {range(perHour(top), signed)} div/h harsh.
        </Verdict>
        <Verdict kind="loses" title="Cards and risers lose" figure={`${range(perHour(cards), signed)} div/h`} figureNote="card turn-ins, harsh">
          Buying the Rising list loses even at fair prices ({range(perHour(rising), signed)} div/h): by the time an hour is published, the rise is over.
        </Verdict>
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
      <HourlySection r={r} />

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
            <span className="text-text">Later windows pay less.</span> Days 2–4 still beat the typical item; days 5–10 is close to break-even at harsh prices.
          </li>
          <li>
            <span className="text-text">Only run a loop that paid every hour</span> (the "paid every hour" badge on the 3-hour recap), and check the in-game
            prices first. Expect a fraction of a Divine an hour.
          </li>
          <li>
            <span className="text-text">Treat card turn-ins as leads, not trades.</span> A card's price swings so much within an hour that buying at the wrong
            moment wipes out the margin.
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
  title,
  figure,
  figureNote,
  children,
}: {
  kind: keyof typeof VERDICT
  title: string
  figure: string
  figureNote: string
  children: ReactNode
}) {
  const v = VERDICT[kind]
  const Icon = v.icon
  return (
    <div className={`flex flex-col gap-2 rounded-xl border p-4 ${v.cls}`}>
      <h2 className="flex items-center gap-2 font-semibold">
        <span className={`grid size-6 place-items-center rounded-full ${v.iconCls}`}>
          <Icon aria-hidden className="size-3.5" />
        </span>
        {title}
      </h2>
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
      title="Missed opportunities, hour by hour"
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
