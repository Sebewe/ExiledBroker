import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MissedLoop, MissedWindow } from '../api/client'
import Missed from './Missed'

// The landing page against a fake API: no data, a league waiting for its first trades,
// a stale feed, and a normal recap.
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

function renderPage() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Missed />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const NOW = '2026-10-22T09:30:00Z'
const league = (latest: string | null) => ({ name: 'Allflame', latest_hour: latest, hours: 30, launched_at: '2026-10-21T00:00:00Z', divine_chaos: 200 })
const status = (latest: string | null) => ({ body: { now: NOW, data_version: 'v1', leagues: [league(latest)] } })

const recap = (hours: number, scale: number): MissedWindow => ({
  hours,
  latest_hour: '2026-10-22T08:00:00Z',
  rising: [{ item_id: 'currency:a', name: 'Domination Scarab', price: 60, before: 40, change: 0.5, volume: 5000, streak: 3 }],
  falling: [{ item_id: 'currency:b', name: 'Essence of Horror', price: 30, before: 45, change: -1 / 3, volume: 3000, streak: -2 }],
  volatile: [{ item_id: 'currency:c', name: 'Abyss Scarab', low: 4, high: 64, price: 10, range: 6, volume: 9000 }],
  ticker: [
    { item_id: 'currency:a', name: 'Domination Scarab', price: 60, before: 40, change: 0.5, volume: 5000, streak: 3 },
    { item_id: 'currency:f', name: 'Ancient Orb', price: 90, before: 100, change: -0.1, volume: 9000, streak: -1 },
  ],
  loops: [
    { item_id: 'currency:d', name: 'Reverent Fragment', direction: 'chaos_first', missed: 2000 * scale, best_edge: 0.12, hours_paid: hours, price: 50, volume: 4000 },
  ],
  cards: [
    { item_id: 'currency:e', name: 'The Sephirot', reward: '10× Divine Orb', missed: 1000 * scale, margin: 400, set_cost: 1600, sets: 2.5, hours_paid: 1 },
  ],
  loops_paid: 2 * scale,
  cards_paid: scale,
})
const RECAP = [recap(1, 1), recap(2, 2), recap(3, 3)]

// A league's first hour, as the API reports it (tests/test_league_start.py replays
// Allflame's): nothing to compare against and nothing paid yet.
const empty = (hours: number): MissedWindow => ({
  hours,
  latest_hour: '2026-10-22T08:00:00Z',
  rising: [],
  falling: [],
  volatile: [],
  ticker: [],
  loops: [],
  cards: [],
  loops_paid: 0,
  cards_paid: 0,
})
const iso = (msFromNow: number) => new Date(Date.now() + msFromNow).toISOString()
const MIN = 60_000

afterEach(() => vi.unstubAllGlobals())

describe('Market recap', () => {
  it('explains when nothing is loaded yet', async () => {
    serve({ '/api/status': { status: 503, body: { detail: 'no data loaded yet' } } })
    renderPage()
    expect(await screen.findByText('No data yet')).toBeInTheDocument()
  })

  it('waits for the first trades of a new league', async () => {
    serve({ '/api/status': status(null) })
    renderPage()
    expect(await screen.findByText('Waiting for the first trades')).toBeInTheDocument()
  })

  it('warns when the feed looks stopped', async () => {
    serve({ '/api/status': status('2026-10-22T05:00:00Z'), '/api/missed/Allflame': { body: RECAP } })
    renderPage()
    expect(await screen.findByText('Data may be out of date')).toBeInTheDocument()
  })

  it('recaps the last hour without promising a payout', async () => {
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body: RECAP } })
    renderPage()
    const hero = await screen.findByRole('region', { name: 'Recap' })
    expect(within(hero).getByText('Loops that paid').nextSibling?.textContent).toBe('2')
    expect(within(hero).getByText('Domination Scarab')).toBeInTheDocument() // the biggest move
    expect(screen.queryByText(/on the table/)).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Options' })).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Backtest/ })).toHaveAttribute('href', '/backtest')
    expect(screen.getByText(/^up 3h running$/)).toBeInTheDocument()
    expect(screen.getByText(/^down 2h running$/)).toBeInTheDocument()
    expect(screen.getByText('600% range')).toBeInTheDocument()
    expect(screen.getByText('+12%')).toBeInTheDocument() // the loop's edge, not a total
    expect(screen.queryByText(/likely one odd trade/)).not.toBeInTheDocument() // 12% isn't odd
    expect(screen.getByText('20.0div')).toBeInTheDocument() // 4000c traded an hour, at 200c
    expect(screen.getByText('40.0c → 60.0c')).toBeInTheDocument() // under a Divine: Chaos
    // The ticker scrolls the last hour's movers; its second copy is for the loop only.
    const ticker = screen.getByRole('region', { name: 'Price changes in the last published hour' })
    expect(within(ticker).getAllByText('Ancient Orb')).toHaveLength(2)
    expect(within(ticker).getAllByText('▼ −10%')).toHaveLength(2)
    expect(screen.getByText('10× Divine Orb')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('lists every paying loop on request, each with this hour’s orders and its 24h range', async () => {
    const loop = (i: number, extra: Partial<MissedLoop> = {}): MissedLoop => ({
      item_id: `currency:l${i}`,
      name: `Loop item ${i}`,
      direction: 'chaos_first',
      missed: 100 - i,
      best_edge: 0.05,
      hours_paid: 1,
      price: 10,
      volume: 4000,
      bid: 10.5,
      ask: 0.06,
      bid_in: 'chaos',
      order_ok: true,
      range_low: 9,
      range_avg: 10,
      range_high: 12,
      range_hours: 24,
      ...extra,
    })
    const loops = [loop(1), loop(2, { order_ok: false }), loop(3, { bid: null, ask: null, bid_in: null }), loop(4)]
    const body = RECAP.map((w) => ({ ...w, loops, loops_paid: 4 }))
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body } })
    renderPage()
    const section = (await screen.findByRole('heading', { name: 'Loops that paid' })).closest('section')!
    expect(within(section).getAllByRole('heading', { level: 3 })).toHaveLength(3) // the top 3
    expect(within(section).getAllByText('10.5c').length).toBeGreaterThan(0) // the bid, in Chaos
    expect(within(section).getAllByText('0.0600 div')).toHaveLength(2) // the asks, in Divines (not the one with no order)
    expect(within(section).getByText(/skip it this hour/)).toBeInTheDocument() // order_ok false
    expect(within(section).getByText(/no price to order from/)).toBeInTheDocument() // didn't trade
    expect(within(section).getAllByText('24h low 9.00c')).toHaveLength(3)
    fireEvent.click(within(section).getByRole('button', { name: 'Show all 4' }))
    expect(within(section).getByRole('heading', { name: 'Loop item 4' })).toBeInTheDocument()
  })

  it('switches look-back without asking the server again', async () => {
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body: RECAP } })
    renderPage()
    await screen.findByRole('region', { name: 'Recap' })
    const calls = vi.mocked(fetch).mock.calls.length
    fireEvent.change(screen.getByRole('slider'), { target: { value: '3' } })
    expect(await screen.findByText(/1 of the loops below paid every hour of the last 3/)).toBeInTheDocument()
    expect(screen.getByText('paid every hour')).toBeInTheDocument()
    expect(vi.mocked(fetch).mock.calls.length).toBe(calls)
  })

  it('counts down to the first published hour once the new league has started', async () => {
    const upcoming = { name: 'Allflame', start_at: iso(-10 * MIN), first_data_at: iso(60 * MIN) }
    serve({ '/api/status': { body: { now: iso(0), data_version: null, leagues: [], upcoming } } })
    renderPage()
    expect(await screen.findByText(/Allflame is live\. First trades published in about/)).toBeInTheDocument()
    expect(screen.getByRole('timer').textContent).toMatch(/^(59:\d\d|01:00:00)$/)
    expect(screen.queryByRole('region', { name: 'Recap' })).not.toBeInTheDocument()
  })

  it('takes over from the old league as soon as the new one starts', async () => {
    const upcoming = { name: 'Next', start_at: iso(-1 * MIN), first_data_at: iso(69 * MIN) }
    serve({ '/api/status': { body: { now: iso(0), data_version: 'v1', leagues: [league(iso(-90 * MIN))], upcoming } } })
    renderPage()
    expect(await screen.findByRole('region', { name: 'Countdown' })).toBeInTheDocument()
    expect(screen.queryByText('Data may be out of date')).not.toBeInTheDocument()
  })

  it('shows the countdown above the running league before launch', async () => {
    const upcoming = { name: 'Next', start_at: iso(26 * 60 * MIN), first_data_at: iso(27 * 60 * MIN) }
    serve({
      '/api/status': { body: { now: NOW, data_version: 'v1', leagues: [league('2026-10-22T08:00:00Z')], upcoming } },
      '/api/missed/Allflame': { body: RECAP },
    })
    renderPage()
    expect(await screen.findByText(/^Next launches in 1d 0[12]:/)).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Recap' })).toBeInTheDocument()
  })

  it('says the old league has ended, not that the feed stopped, once the next is announced', async () => {
    // Leagues end days before the next one launches: the old one's last hours are stale.
    const upcoming = { name: 'Next', start_at: iso(26 * 60 * MIN), first_data_at: iso(27 * 60 * MIN) }
    serve({
      '/api/status': { body: { now: NOW, data_version: 'v1', leagues: [league('2026-10-20T08:00:00Z')], upcoming } },
      '/api/missed/Allflame': { body: RECAP },
    })
    renderPage()
    expect(await screen.findByText('Allflame has ended')).toBeInTheDocument()
    expect(screen.queryByText('Data may be out of date')).not.toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Recap' })).toBeInTheDocument()
  })

  it('says it is early when the league has only a few hours of trades', async () => {
    const first = { ...league('2026-10-22T08:00:00Z'), launched_at: '2026-10-22T08:00:00Z' }
    serve({
      '/api/status': { body: { now: NOW, data_version: 'v1', leagues: [first] } },
      '/api/missed/Allflame': { body: [empty(1), empty(2), empty(3)] },
    })
    renderPage()
    expect(await screen.findByText("Looks like it's early in the league")).toBeInTheDocument()
    expect(await screen.findByText('nothing liquid moved')).toBeInTheDocument()
    expect(screen.getByText('Nothing liquid rose.')).toBeInTheDocument()
    expect(screen.getByText(/No loop with enough volume beat a 2% edge/)).toBeInTheDocument()
    expect(screen.getByText(/No card turn-in paid/)).toBeInTheDocument()
  })

  it('drops the early note once the league has a few hours behind it', async () => {
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body: RECAP } })
    renderPage()
    await screen.findByRole('region', { name: 'Recap' })
    expect(screen.queryByText("Looks like it's early in the league")).not.toBeInTheDocument()
    // The key item names the opportunity, not a rank number.
    expect(screen.getByRole('heading', { name: 'Reverent Fragment' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'The Sephirot' })).toBeInTheDocument()
    expect(screen.queryByText('#1')).not.toBeInTheDocument()
  })
})
