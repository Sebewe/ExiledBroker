import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { Farming as FarmingData, FarmingHours, FarmingMechanic, FarmingOutlook, HourEffect } from '../api/farming'
import Farming from './Farming'

function serve(routes: Record<string, { status?: number; body: unknown }>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === 'string' ? input : input.url, 'http://test')
      const { status = 200, body } = routes[url.pathname] ?? { status: 404, body: { detail: 'not found' } }
      return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
    }),
  )
}

function renderFarming(url = '/farming') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Farming />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const MIN = 60_000
const NOW = Date.parse('2026-10-24T10:20:00Z')
const iso = (offset: number) => new Date(NOW + offset).toISOString()
const league = (latest: string | null, launched: string | null = iso(-30 * 60 * MIN), divine: number | null = 200) => ({
  name: 'Allflame',
  latest_hour: latest,
  hours: 30,
  launched_at: launched,
  divine_chaos: divine,
})
const status = (leagues: unknown[], upcoming: unknown = null) => ({ body: { now: iso(0), data_version: 'v1', leagues, upcoming } })

const mechanic = (id: string, name: string, x: Partial<FarmingMechanic> = {}): FarmingMechanic => ({
  id,
  name,
  items: 14,
  priced_items: 11,
  index: 1.32,
  usual: 1.1,
  usual_low: 0.95,
  usual_high: 1.25,
  change_24h: 0.04,
  change_7d: -0.08,
  chaos_volume_h: 18500,
  liquidity: 0.71,
  score: 0.66,
  ...x,
})
const outlook = (id: string, name: string, day1: number, days5_10: number): FarmingOutlook => ({
  id,
  name,
  leagues: 4,
  windows: { day1: { premium: day1, worst: 0.9 }, days2_4: { premium: 1.2, worst: 1.0 }, days5_10: { premium: days5_10, worst: 1.01 } },
})
const flat = Array(24).fill(0)
const effect = (gain: number, best: number, worst: number, verdict: 'small' | 'worth_it' = 'worth_it'): HourEffect => ({
  gain,
  gap: gain * 2,
  best,
  worst,
  null95: 0.01,
  verdict,
})
// In UTC (the tests' time zone is pinned below): evening dear, early morning cheap.
const HOURS: FarmingHours = {
  phase: 'd2_7',
  leagues: 5,
  days: 30,
  price: flat.map((_, h) => (h === 23 ? 0.021 : h === 6 ? -0.017 : 0)),
  price_divine_market: flat.map((_, h) => (h === 21 ? 0.017 : 0)),
  divine: flat.map((_, h) => (h === 23 ? 0.041 : h === 12 ? -0.04 : 0)),
  volume: Array(24).fill(1 / 24),
  effect: effect(0.021, 23, 6),
  effect_divine_market: effect(0.003, 21, 8, 'small'),
  divine_effect: { ...effect(0.041, 23, 12), gap: 0.081 },
  mechanics: { essence: { ...effect(0.092, 23, 6), price: flat.map((_, h) => (h === 23 ? 0.092 : 0)), items: 42, stability: 0.9, shown: true } },
}
const FARMING: FarmingData = {
  league: 'Allflame',
  latest_hour: iso(-80 * MIN),
  day_offset: 1.2,
  phase: 'launch',
  mechanics: [
    mechanic('breach', 'Breach'),
    mechanic('delirium', 'Delirium', { score: 0.9, index: 0.9, usual: 1.2, liquidity: 0.2 }),
    mechanic('essence', 'Essence', { score: 0.3, liquidity: 0.95 }),
  ],
  outlook: [outlook('breach', 'Breach', 1.8, 1.1), outlook('essence', 'Essence', 1.3, 1.5)],
  items: [
    {
      item_id: 'currency:splinter-of-xoph',
      name: 'Splinter of Xoph',
      mechanics: ['breach'],
      chaos: { price: 1.4, volume_h: 3200, sigma_h: 0.031, hours_traded: 0.92 },
      divine: { price: 0.008, volume_h: 40, sigma_h: 0.05, hours_traded: 0.21 },
    },
    {
      item_id: 'currency:deafening-essence-of-greed',
      name: 'Deafening Essence of Greed',
      mechanics: ['essence'],
      chaos: { price: 3, volume_h: 50, sigma_h: 0.08, hours_traded: 0.6 },
      divine: null,
    },
  ],
  hours: HOURS,
  impact: { y: 0.8, note: null },
}

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

describe('Farming', () => {
  it('explains when nothing is loaded yet', async () => {
    serve({ '/api/status': { status: 503, body: { detail: 'no data loaded yet' } } })
    renderFarming()
    expect(await screen.findByText('No data yet')).toBeInTheDocument()
  })

  it('says when the feed has no league', async () => {
    serve({ '/api/status': status([]) })
    renderFarming()
    expect(await screen.findByText('No league yet')).toBeInTheDocument()
  })

  it('is the launch outlook alone before launch, with the countdown', async () => {
    const upcoming = { name: 'Allflame', start_at: iso(26 * 60 * MIN), first_data_at: iso(27 * 60 * MIN) }
    serve({
      '/api/status': status([league(null, null, null)], upcoming),
      '/api/farming/Allflame': { body: { ...FARMING, latest_hour: null, day_offset: null, phase: 'pre_launch', mechanics: [], items: [], hours: null } },
    })
    renderFarming()
    expect(await screen.findByText(/Allflame launches in 26h/)).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Launch outlook' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'What to farm' })).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Selling a stack' })).not.toBeInTheDocument()
    const ranked = within(screen.getByRole('list', { name: 'Outlook, Day 1' }))
    expect(ranked.getAllByRole('listitem').map((li) => li.textContent)).toEqual([expect.stringContaining('Breach'), expect.stringContaining('Essence')])
  })

  it('leads with the outlook in launch week, opened on the current window', async () => {
    serve({ '/api/status': status([league(iso(-80 * MIN))]), '/api/farming/Allflame': { body: FARMING } })
    renderFarming()
    const headings = (await screen.findAllByRole('heading', { level: 2 })).map((h) => h.textContent)
    expect(headings).toEqual(['Launch outlook', 'What to farm', 'Selling a stack'])
    // Day offset 1.2 is day 2: days 2–4 is open now.
    expect(screen.getByRole('radio', { name: 'Days 2–4 (now)' })).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(screen.getByRole('radio', { name: 'Days 5–10' }))
    const ranked = within(screen.getByRole('list', { name: 'Outlook, Days 5–10' }))
    expect(ranked.getAllByRole('listitem')[0]).toHaveTextContent('Essence')
  })

  it('ranks mechanics by score, trend or ease of selling', async () => {
    serve({ '/api/status': status([league(iso(-80 * MIN))]), '/api/farming/Allflame': { body: FARMING } })
    renderFarming()
    const names = () => within(screen.getByRole('list', { name: 'Mechanics' })).getAllByRole('heading').map((h) => h.textContent)
    expect(await screen.findByRole('list', { name: 'Mechanics' })).toBeInTheDocument()
    expect(names()).toEqual(['Delirium', 'Breach', 'Essence'])
    fireEvent.click(screen.getByRole('radio', { name: 'Easy to sell' }))
    expect(names()).toEqual(['Essence', 'Breach', 'Delirium'])
    fireEvent.click(screen.getByRole('radio', { name: 'Above usual' }))
    expect(names()).toEqual(['Breach', 'Essence', 'Delirium'])
    expect(screen.getAllByText('+20%')[0]).toBeInTheDocument() // 1.32 against a usual 1.1
    expect(screen.getByText('−25%')).toBeInTheDocument() // Delirium: 0.9 against 1.2
  })

  it('shows the top six mechanics until asked for all', async () => {
    const many = Array.from({ length: 8 }, (_, i) => mechanic(`m${i}`, `Mechanic ${i}`, { score: 1 - i / 10 }))
    serve({ '/api/status': status([league(iso(-80 * MIN))]), '/api/farming/Allflame': { body: { ...FARMING, mechanics: many } } })
    renderFarming()
    const cards = async () => within(await screen.findByRole('list', { name: 'Mechanics' })).getAllByRole('listitem')
    expect(await cards()).toHaveLength(6)
    fireEvent.click(screen.getByRole('button', { name: 'Show all 8' }))
    expect(await cards()).toHaveLength(8)
  })

  it('compares the two markets for a stack, and says which fetches more', async () => {
    serve({ '/api/status': status([league(iso(-80 * MIN))]), '/api/farming/Allflame': { body: FARMING } })
    renderFarming('/farming?item=currency:splinter-of-xoph&qty=10')
    // 10 splinters: the Divine market pays 1.6c each and barely moves.
    expect(await screen.findByText(/^Sell /)).toHaveTextContent('Sell 10 Splinter of Xoph in the Divine market')
    expect(within(screen.getByRole('region', { name: 'Divine market' })).getByText('Better')).toBeInTheDocument()
    // 5000 sink the thin Divine market.
    fireEvent.change(screen.getByLabelText('How many'), { target: { value: '5000' } })
    expect(screen.getByText(/^Sell /)).toHaveTextContent('Sell 5,000 Splinter of Xoph in the Chaos market')
    const divine = within(screen.getByRole('region', { name: 'Divine market' }))
    expect(divine.getByText('about −36%')).toBeInTheDocument()
    expect(divine.getByText(/trades in only 21% of hours/)).toBeInTheDocument()
  })

  it('says when an item has no Divine market', async () => {
    serve({ '/api/status': status([league(iso(-80 * MIN))]), '/api/farming/Allflame': { body: FARMING } })
    renderFarming('/farming?item=currency:deafening-essence-of-greed')
    expect(await screen.findByText(/hasn't traded against Divines lately/)).toBeInTheDocument()
    expect(screen.getByText(/^Sell /)).toHaveTextContent('in the Chaos market.')
  })

  it("can't compare the Divine market before there's a Divine price", async () => {
    serve({ '/api/status': status([league(iso(-80 * MIN), iso(-3 * 60 * MIN), null)]), '/api/farming/Allflame': { body: FARMING } })
    renderFarming('/farming?item=currency:splinter-of-xoph')
    expect(await screen.findByText(/no Divine price yet/)).toBeInTheDocument()
  })

  it("names the best hours: the item's own mechanic's where it holds, the pooled ones otherwise", async () => {
    serve({ '/api/status': status([league(iso(-80 * MIN))]), '/api/farming/Allflame': { body: FARMING } })
    renderFarming('/farming?item=currency:splinter-of-xoph')
    expect(await screen.findByText(/^Prices run highest/)).toHaveTextContent(
      "Prices run highest around 23:00 your time: about 2.1% over the day's average, and 4.2% over the lowest hour (06:00).",
    )
    expect(screen.getByText(/Converting to Divines/)).toHaveTextContent("They're cheapest in Chaos around 12:00 your time and dearest around 23:00: about 8.1% apart.")
    expect(screen.getByText(/From 5 past leagues' days 2–7 \(30 league-days\)/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Item'), { target: { value: 'currency:deafening-essence-of-greed' } })
    expect(screen.getByText(/drops sell highest/)).toHaveTextContent("Essence's drops sell highest around 23:00 your time: about 9.2% over the day's average")
  })

  it('says when time of day barely matters, as in the Divine market here', async () => {
    serve({ '/api/status': status([league(iso(-80 * MIN))]), '/api/farming/Allflame': { body: FARMING } })
    renderFarming()
    fireEvent.click(await screen.findByRole('radio', { name: 'Divine market' }))
    expect(screen.getByText(/Time of day barely matters/)).toHaveTextContent("on days 2–7: the best hour beats the day's average by about 0.3%")
  })

  it('later in the league: no usual path after day 14, the outlook is for the next league', async () => {
    const later = {
      ...FARMING,
      day_offset: 40,
      phase: 'later',
      mechanics: FARMING.mechanics.map((m) => ({ ...m, usual: null, usual_low: null, usual_high: null })),
      hours: { ...HOURS, price: Array(24).fill(null), divine_effect: effect(0.004, 23, 12, 'small'), mechanics: {} },
    }
    serve({ '/api/status': status([league(iso(-80 * MIN))]), '/api/farming/Allflame': { body: later } })
    renderFarming()
    expect(await screen.findByText(/no usual path to compare against this late/)).toBeInTheDocument()
    const headings = screen.getAllByRole('heading', { level: 2 }).map((h) => h.textContent)
    expect(headings).toEqual(['What to farm', 'Selling a stack', "Next league's launch"])
    expect(screen.getByRole('radio', { name: 'Day 1' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByText(/Not enough days of trades yet/)).toBeInTheDocument()
  })

  it('waits for the first trades, and warns about a stale feed', async () => {
    serve({
      '/api/status': status([league(null)]),
      '/api/farming/Allflame': { body: { ...FARMING, latest_hour: null, mechanics: [], items: [], hours: null } },
    })
    const { unmount } = renderFarming()
    expect(await screen.findByText('Waiting for the first trades')).toBeInTheDocument()
    expect(await screen.findByText(/No mechanic's drops have traded yet/)).toBeInTheDocument()
    expect(screen.getByText(/None of the mechanics' drops has a recent price yet/)).toBeInTheDocument()
    unmount()
    serve({ '/api/status': status([league(iso(-5 * 60 * MIN))]), '/api/farming/Allflame': { body: FARMING } })
    renderFarming()
    expect(await screen.findByText('Data may be out of date')).toBeInTheDocument()
  })

  it("explains the API's 503 for the league", async () => {
    serve({ '/api/status': status([league(iso(-80 * MIN))]), '/api/farming/Allflame': { status: 503, body: { detail: 'no data' } } })
    renderFarming()
    expect(await screen.findByText('No data yet')).toBeInTheDocument()
  })
})
