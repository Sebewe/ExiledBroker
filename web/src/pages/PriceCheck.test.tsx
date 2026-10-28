import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { SellHours } from '../api/client'
import type { Horizon, PriceCheckIndex, PriceCheckItem, SeriesPoint } from '../api/client'
import type { ChartTokens } from '../lib/chartOptions'
import { PREVIEW_DOCS, previewRoutes, previewStatus } from '../test/preview'
import PriceCheck from './PriceCheck'

// ECharts needs a canvas, which jsdom hasn't got: stand in for the chart, building its
// option so a broken one still fails here, and expose its series.
vi.mock('../components/Chart', () => ({
  default: ({ build, label }: { build: (t: ChartTokens) => { series: { name: string; data: unknown[] }[] }; label: string }) => {
    const t = { text: '', muted: '', faint: '', border: '', surface: '', surface2: '', accent: '#e3ac72', info: '#93b8f5' }
    const option = build(t)
    return <div role="img" aria-label={label} data-series={option.series.map((s) => `${s.name}:${s.data.length}`).join(',')} />
  },
}))

function serve(routes: Record<string, { status?: number; body: unknown }>) {
  const fetch = vi.fn(async (input: Request | string) => {
    const url = new URL(typeof input === 'string' ? input : input.url, 'http://test')
    const { status = 200, body } = routes[url.pathname] ?? { status: 404, body: { detail: 'not found' } }
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}

function renderPage(url = '/price-check') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Routes>
          <Route
            path="*"
            element={
              <>
                <PriceCheck />
                <Where />
              </>
            }
          />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const MIN = 60_000
const HOUR = 60 * MIN
const NOW = Date.parse('2026-10-24T10:20:00Z')
const LATEST = NOW - 80 * MIN
const iso = (ms: number) => new Date(ms).toISOString()
const league = (latest: number | null, divine: number | null = 200) => ({
  name: 'Allflame',
  latest_hour: latest == null ? null : iso(latest),
  hours: 30,
  launched_at: iso(NOW - 10 * 24 * HOUR),
  divine_chaos: divine,
})
const status = (leagues: unknown[]) => ({ body: { now: iso(NOW), data_version: 'v1', leagues, upcoming: null } })

const SPLINTER = 'currency:splinter-of-xoph'
const DIVINE = 'currency:divine-orb'
const ESSENCE = 'currency:deafening-essence-of-greed'
const INDEX: PriceCheckIndex = {
  league: 'Allflame',
  latest_hour: iso(LATEST),
  day_offset: 9.9,
  items: [
    { item_id: ESSENCE, name: 'Deafening Essence of Greed', label: 'Essence', chaos: 3, volume_h: 50, verdict_24h: 'hold', change_24h: 0.04 },
    { item_id: SPLINTER, name: 'Splinter of Xoph', label: 'Breach', chaos: 1.4, volume_h: 3200, verdict_24h: 'sell', change_24h: -0.06 },
    { item_id: 'currency:chaos-orb', name: 'Chaos Orb', label: null, chaos: 1, volume_h: 9000, verdict_24h: 'none', change_24h: null },
    { item_id: DIVINE, name: 'Divine Orb', label: 'Currency', chaos: 200, volume_h: 400, verdict_24h: 'none', change_24h: 0.02 },
  ],
  movers: [SPLINTER, ESSENCE],
  movers_mode: 'calls',
}

const horizon = (x: Partial<Horizon> = {}): Horizon => ({ verdict: 'sell', typical: -0.08, low: -0.12, high: 0.02, leagues: 4, basis: 'item', state: 'judged', ...x })
/** Hourly from launch to the latest hour (10 days), Chaos 1.4, Divines at 1/200. */
const hourly = (hours: number, divine = true): SeriesPoint[] =>
  Array.from({ length: hours }, (_, i) => [iso(LATEST - (hours - 1 - i) * HOUR), 1.4, divine ? 0.007 : null])
const flat = Array(24).fill(0)
const HOURS: SellHours = {
  phase: 'd7_14',
  leagues: 5,
  days: 30,
  price: flat.map((_, h) => (h === 23 ? 0.021 : h === 6 ? -0.017 : 0)),
  price_divine_market: flat,
  divine: flat,
  volume: flat.map((_, h) => (h >= 17 && h < 21 ? 2 : h >= 2 && h < 6 ? 1 : 1.5) / 36),
  effect: { gain: 0.021, gap: 0.042, best: 23, worst: 6, null95: 0.01, verdict: 'worth_it' },
  effect_divine_market: { gain: 0.003, gap: 0.006, best: 21, worst: 8, null95: 0.01, verdict: 'small' },
  divine_effect: { gain: 0.004, gap: 0.008, best: 23, worst: 12, null95: 0.01, verdict: 'small' },
  mechanics: {},
}
const ITEM: PriceCheckItem = {
  item_id: SPLINTER,
  name: 'Splinter of Xoph',
  label: 'Breach',
  latest_hour: iso(LATEST),
  day_offset: 9.9,
  thick: true,
  change_24h: -0.06,
  unit: 'divine',
  series: hourly(240),
  outlook: { h24: horizon({ typical: -0.03, low: -0.09 }), d3: horizon({ verdict: 'none', typical: -0.01 }), unit: 'divine' },
  stack: {
    chaos: { price: 1.4, volume_h: 3200, sigma_h: 0.031, hours_traded: 0.92 },
    divine: { price: 0.008, volume_h: 40, sigma_h: 0.05, hours_traded: 0.21 },
  },
  launch_prices: { day1: { divine: 0.02, leagues: 4 }, days2_4: { divine: 0.01, leagues: 4 }, days5_10: null },
  last_day: [
    { hour: '2026-10-22T19:00:00Z', chaos_price: 1.4, chaos_units: 3000, divine_price: null, divine_units: null, divine_rate: 200 },
    { hour: '2026-10-22T20:00:00Z', chaos_price: 1.5, chaos_units: 4000, divine_price: 0.008, divine_units: 40, divine_rate: 200 },
    { hour: '2026-10-22T21:00:00Z', chaos_price: 1.3, chaos_units: 2000, divine_price: null, divine_units: null, divine_rate: 200 },
  ],
  hours: HOURS,
  impact: { y: null, bands: [0.25, 1], note: null },
}
const itemPath = (id: string) => `/api/price-check/Allflame/${encodeURIComponent(id)}`
const live = (item: PriceCheckItem = ITEM, index: PriceCheckIndex = INDEX) => ({
  '/api/status': status([league(LATEST)]),
  '/api/price-check/Allflame': { body: index },
  [itemPath(item.item_id)]: { body: item },
})

// Hour labels are local time: pin the clock's zone so they read as UTC.
const realDTF = Intl.DateTimeFormat
beforeEach(() => {
  vi.spyOn(Intl, 'DateTimeFormat').mockImplementation(function (locales?: Intl.LocalesArgument, options?: Intl.DateTimeFormatOptions) {
    return new realDTF(locales, { ...options, timeZone: options?.timeZone ?? 'UTC' })
  } as unknown as typeof Intl.DateTimeFormat)
})
afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe('Price check', () => {
  it('explains when nothing is loaded yet', async () => {
    serve({ '/api/status': { status: 503, body: { detail: 'no data loaded yet' } } })
    renderPage()
    expect(await screen.findByText('No data yet')).toBeInTheDocument()
  })

  it("explains the API's 503 for the league", async () => {
    serve({ '/api/status': status([league(LATEST)]), '/api/price-check/Allflame': { status: 503, body: { detail: 'no data' } } })
    renderPage()
    expect(await screen.findByText('No data yet')).toBeInTheDocument()
  })

  it('says when the feed has no league', async () => {
    serve({ '/api/status': status([]) })
    renderPage()
    expect(await screen.findByText('No league yet')).toBeInTheDocument()
  })

  it('opens on the search and the movers, strongest first, money first', async () => {
    serve(live())
    renderPage()
    const box = await screen.findByRole('combobox', { name: 'Find an item' })
    expect(box).toHaveValue('')
    const rows = within(screen.getByRole('list', { name: 'Movers' })).getAllByRole('link')
    expect(rows.map((r) => r.textContent)).toEqual(['−6%1.40cSplinter of XophSell', '+4%3.00cDeafening Essence of GreedHold'])
    // The 24 h move is a gain or loss: green or red, and so is the card's border. The verdict isn't.
    expect(within(rows[0]!).getByText('−6%')).toHaveClass('text-negative')
    expect(rows[0]!.className).toMatch(/border-negative/)
    expect(rows[1]!.className).toMatch(/border-positive/)
    expect(within(rows[0]!).getByText('Sell').className).not.toMatch(/positive|negative/)
    // Focused, the search lists every item, most traded first, each with its group.
    fireEvent.focus(box)
    const options = within(screen.getByRole('listbox')).getAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual(['Divine OrbCurrency', 'Chaos Orb', 'Splinter of XophBreach', 'Deafening Essence of GreedEssence'])
  })

  it('opens an item from the movers, and from the search, with the item in the URL', async () => {
    serve({ ...live(), [itemPath(ESSENCE)]: { body: { ...ITEM, item_id: ESSENCE, name: 'Deafening Essence of Greed' } } })
    renderPage('/price-check?league=Allflame')
    fireEvent.click(await screen.findByRole('link', { name: /Splinter of Xoph/ }))
    expect(screen.getByTestId('where')).toHaveTextContent(`/price-check?league=Allflame&item=${encodeURIComponent(SPLINTER)}`)
    expect(await screen.findByRole('heading', { name: 'Splinter of Xoph', level: 2 })).toBeInTheDocument()
    const box = screen.getByRole('combobox', { name: 'Find an item' })
    expect(box).toHaveValue('Splinter of Xoph')
    fireEvent.focus(box)
    fireEvent.change(box, { target: { value: 'greed' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(await screen.findByRole('heading', { name: 'Deafening Essence of Greed', level: 2 })).toBeInTheDocument()
    // Back to the movers keeps the league.
    fireEvent.click(screen.getByRole('link', { name: 'Back to the list' }))
    expect(screen.getByTestId('where')).toHaveTextContent(/^\/price-check\?league=Allflame$/)
    expect(await screen.findByRole('list', { name: 'Movers' })).toBeInTheDocument()
  })

  it("opens Divine Orb's own page: its price in Chaos, no call, its Chaos market only", async () => {
    const item: PriceCheckItem = {
      ...ITEM,
      item_id: DIVINE,
      name: 'Divine Orb',
      label: 'Currency',
      unit: 'chaos',
      change_24h: 0.02,
      series: hourly(240).map(([t]) => [t, 200, null]),
      outlook: null,
      stack: { chaos: { price: 200, volume_h: 400, sigma_h: 0.01, hours_traded: 1 }, divine: null },
      launch_prices: null,
      last_day: [
        { hour: '2026-10-22T19:00:00Z', chaos_price: 198, chaos_units: 300, divine_price: null, divine_units: null, divine_rate: null },
        { hour: '2026-10-22T20:00:00Z', chaos_price: 205, chaos_units: 500, divine_price: null, divine_units: null, divine_rate: null },
        { hour: '2026-10-22T21:00:00Z', chaos_price: 201, chaos_units: 200, divine_price: null, divine_units: null, divine_rate: null },
      ],
    }
    serve(live(item))
    renderPage('/price-check?league=Allflame')
    const box = await screen.findByRole('combobox', { name: 'Find an item' })
    fireEvent.focus(box)
    fireEvent.change(box, { target: { value: 'divine' } })
    fireEvent.keyDown(box, { key: 'Enter' })
    expect(await screen.findByRole('heading', { name: 'Divine Orb', level: 2 })).toBeInTheDocument()
    // In Chaos, even where the visitor's unit would make it "1.0 div".
    expect(screen.getByTitle('Latest hourly price')).toHaveTextContent('200')
    expect(screen.getByTitle('Latest hourly price')).not.toHaveTextContent(/div/)
    const verdict = within(screen.getByRole('region', { name: 'Verdict' }))
    expect(verdict.getByText(/has no call of its own/)).toBeInTheDocument()
    expect(verdict.queryByText('No clear signal')).toBeNull()
    const chart = screen.getByRole('img', { name: /hourly price in Chaos, 3 days/ })
    expect(chart.dataset.series).toBe('Chaos:72')
    expect(screen.queryByText(/No Divine rate for these hours yet/)).toBeNull()
    expect(screen.getByText(/of the Chaos market's trading/)).toBeInTheDocument()
    expect(screen.queryByText('Divine market')).toBeNull()
    const best = within(screen.getByRole('region', { name: 'Best time to sell' }))
    expect(best.getByText('Highest price, your time').nextSibling).toHaveTextContent('20:00')
    expect(best.getByText('205.0c')).toBeInTheDocument() // in Chaos
    expect(screen.queryByRole('heading', { name: 'At past launches' })).toBeNull()
  })

  it('asks for each table at the data version it has, so no cache can hand it an older hour', async () => {
    const fetch = serve(live())
    renderPage(`/price-check?league=Allflame&item=${encodeURIComponent(SPLINTER)}`)
    expect(await screen.findByRole('heading', { name: 'Splinter of Xoph', level: 2 })).toBeInTheDocument()
    const urls = fetch.mock.calls.map(([input]) => new URL(typeof input === 'string' ? input : input.url, 'http://test'))
    const v = (path: string) => urls.filter((u) => u.pathname === path).map((u) => u.searchParams.get('v'))
    expect(v('/api/status')).not.toContain('v1') // the status is what says the version
    expect(v('/api/price-check/Allflame')).toEqual(['v1'])
    expect(v(itemPath(SPLINTER))).toEqual(['v1'])
  })

  it('shows the chart, then the verdict for 24 hours and 3 days, the stack seller and the launch premium', async () => {
    serve(live())
    renderPage(`/price-check?item=${SPLINTER}&qty=10`)
    const verdict = within(await screen.findByRole('region', { name: 'Verdict' }))
    const day = within(verdict.getByRole('group', { name: 'Next 24 hours' }))
    expect(day.getByText('Sell now')).toBeInTheDocument()
    expect(day.getByText('In past leagues it fell 3% in Divines over the next 24 hours from this point (−9% to +2%, 4 leagues).')).toBeInTheDocument()
    expect(within(verdict.getByRole('group', { name: 'Next 3 days' })).getByText('No clear signal')).toBeInTheDocument()
    expect(verdict.getByText(/Judged in Divines/)).toBeInTheDocument()
    // The typical path at a glance, beside the question.
    expect(verdict.getByRole('img', { name: 'Typically −3% after 24 hours and −1% after 3 days in past leagues, in Divines.' })).toBeInTheDocument()
    // The order of the page: chart, verdict (under the chart: the user), selling, launch.
    const chartBlock = screen.getByRole('region', { name: 'Price this league' })
    expect(chartBlock.compareDocumentPosition(screen.getByRole('region', { name: 'Verdict' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    expect(screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)).toEqual([
      'Splinter of Xoph',
      'Price this league',
      'Selling a stack',
      'At past launches',
    ])
    // The stack seller: what to do first, then each market's hours and the stack's worth;
    // the rest behind Details.
    const selling = within(screen.getByRole('region', { name: 'Selling a stack' }))
    expect(selling.getByText('Sell it as it is.').closest('p')).toHaveTextContent("Sell it as it is. 10 Splinter of Xoph is under a minute of the Chaos market's trading.")
    const chaosMarket = within(selling.getByRole('region', { name: 'Chaos market' }))
    expect(chaosMarket.getByText('Worth')).toBeInTheDocument()
    // Not the header's latest price: the card says which price it values the stack at.
    expect(chaosMarket.getByText(/each, typical last 24 h$/)).toBeInTheDocument()
    expect(chaosMarket.queryByText('Trades an hour')).toBeNull()
    fireEvent.click(chaosMarket.getByRole('button', { name: 'Details' }))
    expect(chaosMarket.getByText('Trades an hour')).toBeInTheDocument()
    expect(selling.queryByText(/Hours of trading: your stack/)).toBeNull()
    fireEvent.click(selling.getByRole('button', { name: 'How this is worked out' }))
    expect(selling.getByText(/Hours of trading: your stack/)).toBeInTheDocument()
    // Best time to sell: the busiest and dearest hours up front, the totals behind Details.
    const best = within(selling.getByRole('region', { name: 'Best time to sell' }))
    expect(best.getByText('Most traded, your time').nextSibling).toHaveTextContent('20:00')
    expect(best.getByText(/4,040 traded that hour/)).toBeInTheDocument()
    expect(best.getByText('Highest price, your time').nextSibling).toHaveTextContent('20:00')
    expect(best.queryByText(/traded \(about/)).toBeNull()
    fireEvent.click(best.getByRole('button', { name: 'Details' }))
    expect(best.getByText(/traded \(about/)).toHaveTextContent('9,040 traded')
    // At past launches: each window's typical price, against today's.
    const launch = within(screen.getByRole('heading', { name: 'At past launches' }).closest('section')!)
    expect(launch.getAllByText(/^Today it sells for/)).toHaveLength(2)
    expect(launch.getByText('No past league has this window.')).toBeInTheDocument()
    expect(launch.getAllByText('Typical over 4 past leagues')).toHaveLength(2)
    // Sell is the accent, never green or red.
    expect(day.getByText('Sell now').className).toMatch(/accent/)
    expect(day.getByText('Sell now').className).not.toMatch(/positive|negative/)
  })

  it('charts 3 days by default, with the band past the last hour; 14 days and the launch fortnight on request', async () => {
    serve(live())
    renderPage(`/price-check?item=${SPLINTER}`)
    const chart = await screen.findByRole('img', { name: /hourly price in Chaos \(left axis\) and in Divines \(right axis\), 3 days, with the outlook range/ })
    expect(chart.dataset.series).toBe('Chaos:72,Divine:72,band-low:3,Outlook range:3,Outlook (typical):3')
    expect(screen.getByRole('radio', { name: '3 days' })).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(screen.getByRole('radio', { name: '14 days' }))
    // The league is 10 days old: 14 days shows all 240 hours.
    expect(screen.getByRole('img', { name: /14 days/ }).dataset.series).toMatch(/^Chaos:240,Divine:240,band-low/)
    fireEvent.click(screen.getByRole('radio', { name: 'Launch fortnight' }))
    expect(screen.getByRole('img', { name: /launch fortnight/ }).dataset.series).toMatch(/^Chaos:240,/)
    expect(screen.getByTestId('where')).toHaveTextContent('range=launch')
  })

  it('has no Divine line without a Divine rate, and no verdict for an item without history', async () => {
    const none = horizon({ verdict: 'none', state: 'no_history', typical: null, low: null, high: null, leagues: 0 })
    const item: PriceCheckItem = {
      ...ITEM,
      series: hourly(240, false),
      outlook: { h24: none, d3: none, unit: 'divine' },
      stack: { ...ITEM.stack, divine: null },
      launch_prices: null,
    }
    serve(live(item))
    renderPage(`/price-check?item=${SPLINTER}`)
    expect(await screen.findByText(/No Divine rate for these hours yet, so there's no Divine line/)).toBeInTheDocument()
    expect(screen.getByText(/hasn't traded against Divines lately/)).toBeInTheDocument() // the stack's Divine market
    const verdict = within(screen.getByRole('region', { name: 'Verdict' }))
    expect(verdict.getAllByText('No clear signal')).toHaveLength(2)
    expect(verdict.getAllByText(/nothing to judge by/)).toHaveLength(2)
    expect(verdict.getByText(/A verdict needs at least two past leagues/)).toBeInTheDocument()
    expect(verdict.queryByRole('img')).toBeNull() // no path to draw
    expect(screen.getByRole('img', { name: /hourly price/ }).dataset.series).toBe('Chaos:72,Divine:72') // no band
    expect(screen.getByText(/No past league's launch has this item yet/)).toBeInTheDocument()
  })

  it('after the launch fortnight, shows no verdict and no band, only the line saying why', async () => {
    const later = horizon({ verdict: 'none', state: 'later', typical: null, low: null, high: null, leagues: 0 })
    serve(live({ ...ITEM, day_offset: 40, outlook: { h24: later, d3: later, unit: 'divine' } }))
    renderPage(`/price-check?item=${SPLINTER}`)
    const verdict = within(await screen.findByRole('region', { name: 'Verdict' }))
    expect(verdict.getByText("Calls appear in a league's first two weeks; after that past leagues don't predict the next few days.")).toBeInTheDocument()
    expect(verdict.queryByText('Sell now')).toBeNull()
    expect(verdict.queryByText('No clear signal')).toBeNull()
    expect(verdict.queryByRole('img')).toBeNull()
    expect(screen.getByRole('img', { name: /hourly price/ }).dataset.series).toBe('Chaos:72,Divine:72')
    expect(screen.getByRole('region', { name: 'Selling a stack' })).toBeInTheDocument()
  })

  it('between launches, lists the biggest 24-hour moves without Sell or Hold labels', async () => {
    const items = INDEX.items.map((x) => ({ ...x, verdict_24h: 'none' as const }))
    serve(live(ITEM, { ...INDEX, day_offset: 40, items, movers: [SPLINTER, ESSENCE], movers_mode: 'moves' }))
    renderPage()
    expect(await screen.findByRole('heading', { name: 'Biggest moves, last 24 hours' })).toBeInTheDocument()
    expect(screen.getByText(/Calls appear in a league's first two weeks/)).toBeInTheDocument()
    const rows = within(screen.getByRole('list', { name: 'Movers' })).getAllByRole('listitem')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('Splinter of Xoph')
    expect(rows[0]).toHaveTextContent('−6%')
    for (const row of rows) for (const word of ['Sell', 'Hold', '–']) expect(within(row).queryByText(word)).toBeNull()
  })

  it('handles a single hour of data', async () => {
    serve(live({ ...ITEM, series: hourly(1) }))
    renderPage(`/price-check?item=${SPLINTER}`)
    expect(await screen.findByText(/Only one hour has traded so far/)).toBeInTheDocument()
    expect(screen.getByRole('img', { name: /hourly price/ }).dataset.series).toMatch(/^Chaos:1,Divine:1,/)
  })

  it('says when the item has not traded in the range', async () => {
    serve(live({ ...ITEM, series: [] }))
    renderPage(`/price-check?item=${SPLINTER}`)
    expect(await screen.findByText("Splinter of Xoph hasn't traded in this range yet.")).toBeInTheDocument()
  })

  it("says when an item isn't one we price", async () => {
    serve({ ...live(), [itemPath('currency:mirror-of-kalandra')]: { status: 404, body: { detail: 'unknown item' } } })
    renderPage('/price-check?item=currency:mirror-of-kalandra')
    expect(await screen.findByText('Not an item we price')).toBeInTheDocument()
  })

  it('waits for the first trades, and warns about a stale feed', async () => {
    serve({
      '/api/status': status([league(null, null)]),
      '/api/price-check/Allflame': { body: { ...INDEX, latest_hour: null, day_offset: null, items: [], movers: [] } },
    })
    const { unmount } = renderPage()
    expect(await screen.findByText('Waiting for the first trades')).toBeInTheDocument()
    expect(await screen.findByText(/No item has traded yet this league/)).toBeInTheDocument()
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
    unmount()
    serve({ ...live(), '/api/status': status([league(NOW - 5 * HOUR)]) })
    renderPage()
    expect(await screen.findByText('Data may be out of date')).toBeInTheDocument()
  })

  it('says when no item has a clear call', async () => {
    serve(live(ITEM, { ...INDEX, movers: [], movers_mode: 'calls' }))
    renderPage()
    expect(await screen.findByText(/No item has a clear call right now/)).toBeInTheDocument()
    expect(screen.getByRole('combobox', { name: 'Find an item' })).toBeInTheDocument()
  })

  it('shows no reveal outside the preview', async () => {
    serve(live())
    renderPage(`/price-check?item=${SPLINTER}`)
    expect(await screen.findByRole('region', { name: 'Verdict' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Show what happened next' })).toBeNull()
  })
})

describe('Price check in the preview', () => {
  const EXALT = 'currency:exalted-orb'
  const day2 = PREVIEW_DOCS[`d2/price-check/${EXALT}`] as PriceCheckItem
  const cutoff = Date.parse(day2.latest_hour!)
  // Its next days, made up: 0.005 Divines up to the cutoff, 0.004 after (a 20% fall).
  const next = {
    item_id: EXALT,
    name: 'Exalted Orb',
    unit: 'divine',
    series: Array.from({ length: 24 * 5 }, (_, i) => {
      const at = cutoff - 24 * HOUR + i * HOUR
      const d = at <= cutoff ? 0.005 : 0.004
      return [iso(at), d * 100, d]
    }),
  }
  const routes = (over: Record<string, { body: unknown }> = {}) => ({ ...previewRoutes(), '/api/status': { body: previewStatus() }, ...over })

  it('hides what happened next until asked, then fetches it', async () => {
    const fetch = serve(routes())
    renderPage(`/price-check?item=${EXALT}`)
    const button = await screen.findByRole('button', { name: 'Show what happened next' })
    expect(screen.getByText(/as it stood at the end of day 2/)).toBeInTheDocument()
    // The toggle is in the box, right under the chart: no bar fixed to the screen here.
    const box = screen.getByRole('region', { name: 'What happened next' })
    expect(box).toContainElement(button)
    expect(screen.getByRole('region', { name: 'Price this league' })).toContainElement(box)
    expect(screen.queryByRole('region', { name: 'Preview reveal' })).toBeNull()
    expect(document.body).not.toHaveClass('has-reveal-bar')
    const paths = () => fetch.mock.calls.map(([input]) => new URL(typeof input === 'string' ? input : input.url, 'http://test').pathname)
    expect(paths()).not.toContain(`/api/preview/next/price-check/${EXALT}`)
    fireEvent.click(button)
    // The sample ends 2 hours after day 2: neither horizon is known yet.
    const panel = within(screen.getByRole('region', { name: 'What happened next' }))
    expect(await panel.findAllByText("The preview's data ends before then.")).toHaveLength(2)
    expect(paths()).toContain(`/api/preview/next/price-check/${EXALT}`)
    // What came next is drawn dotted on the item's own chart (the user: one chart, nothing
    // jumps): the range stays, the box stays under the chart, and no second chart appears.
    const block = within(screen.getByRole('region', { name: 'Price this league' }))
    expect(block.getAllByRole('img')).toHaveLength(1)
    expect(panel.queryByRole('img')).toBeNull()
    expect(block.getByRole('radiogroup', { name: 'Range' })).toBeInTheDocument()
    const chart = block.getByRole('img')
    expect(chart.compareDocumentPosition(screen.getByRole('region', { name: 'What happened next' })) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
    await waitFor(() => expect(chart.getAttribute('data-series')).toMatch(/What came next:3,What came next:3$/))
    expect(chart).toHaveAccessibleName(/what came next dotted/)
    fireEvent.click(panel.getByRole('button', { name: 'Hide what happened' }))
    expect(screen.queryByRole('group', { name: '1 day later' })).toBeNull()
    expect(block.getByRole('img').getAttribute('data-series')).not.toMatch(/What came next/)
  })

  it("judges the day's calls against what the price did", async () => {
    const sell = { verdict: 'sell', typical: -0.05, low: -0.1, high: 0.01, leagues: 3, basis: 'item', state: 'judged' } as Horizon
    const called = { ...day2, outlook: { h24: sell, d3: { ...sell, verdict: 'hold' }, unit: 'divine' } }
    serve(routes({ [`/api/preview/d2/price-check/${EXALT}`]: { body: called }, [`/api/preview/next/price-check/${EXALT}`]: { body: next } }))
    renderPage(`/price-check?item=${EXALT}`)
    fireEvent.click(await screen.findByRole('button', { name: 'Show what happened next' }))
    const day = within(await screen.findByRole('group', { name: '1 day later' }))
    expect(day.getByText('−20%')).toBeInTheDocument()
    expect(day.getByText('Call: Sell')).toBeInTheDocument()
    expect(day.getByText('It fell: selling then paid. The call held.')).toBeInTheDocument()
    const days3 = within(screen.getByRole('group', { name: '3 days later' }))
    expect(days3.getByText('It fell: selling then would have paid. The call missed.')).toBeInTheDocument()
    // The day's outlook band stays drawn, with what came next over it: the cutoff, then 3 days on.
    const chart = within(screen.getByRole('region', { name: 'Price this league' })).getByRole('img')
    expect(chart.getAttribute('data-series')).toMatch(/,Outlook range:3,Outlook \(typical\):3,What came next:73,What came next:73$/)
    expect(chart).toHaveAccessibleName(/with the outlook range past the latest hour, and what came next dotted/)
  })
})
