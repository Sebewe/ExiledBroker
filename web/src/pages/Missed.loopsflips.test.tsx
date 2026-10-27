import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MissedFlip, MissedLoop, MissedWindow } from '../api/client'
import Missed from './Missed'

// The recap's Loops and Volatile flips: a one-line takeaway, the odds behind Details, and
// an empty state with a hint.
function serve(windows: MissedWindow[]) {
  const routes: Record<string, { status?: number; body: unknown }> = {
    '/api/status': {
      body: {
        now: '2026-10-22T09:30:00Z',
        data_version: 'v1',
        leagues: [{ name: 'Allflame', latest_hour: '2026-10-22T08:00:00Z', hours: 30, launched_at: '2026-10-21T00:00:00Z', divine_chaos: 200 }],
      },
    },
    '/api/missed/Allflame': { body: windows },
  }
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

const loop = (name: string, extra: Partial<MissedLoop> = {}): MissedLoop => ({
  item_id: `currency:${name.toLowerCase().replace(/ /g, '-')}`,
  name,
  direction: 'chaos_first',
  missed: 100,
  best_edge: 0.06,
  hours_paid: 1,
  price: 10,
  volume: 4000,
  tries: 20,
  through: 15,
  chance: 0.75,
  ...extra,
})

const flip = (name: string, bid: number, ask: number, extra: Partial<MissedFlip> = {}): MissedFlip => ({
  item_id: `currency:${name.toLowerCase().replace(/ /g, '-')}`,
  name,
  price: 100,
  low: 80,
  high: 120,
  range: 0.4,
  volume: 50000,
  bid,
  ask,
  bid_lot: 1,
  bid_total: bid,
  ask_lot: 1,
  ask_total: ask,
  cut: 0.01,
  tries: 60,
  through: 54,
  chance: 0.9,
  ...extra,
})

const window = (loops: MissedLoop[], flips: MissedFlip[]): MissedWindow => ({
  hours: 1,
  latest_hour: '2026-10-22T08:00:00Z',
  rising: [],
  falling: [],
  volatile: [],
  flips,
  ticker: [],
  loops,
  cards: [],
  loops_paid: loops.length,
  cards_paid: 0,
})

const section = async (name: string) => (await screen.findByRole('heading', { level: 2, name })).closest('section')!

afterEach(() => vi.unstubAllGlobals())

describe('Market recap: loops and flips', () => {
  it('opens each section with the first qualifying item in list order', async () => {
    const loops = [
      loop('Odd Item', { best_edge: 0.9 }), // above ODD_EDGE: likely one odd trade
      loop('Never Item', { best_edge: 0.3, chance: 0 }), // its orders never went through
      loop('Skip Item', { best_edge: 0.2, order_ok: false }), // its orders are to be skipped this hour
      loop('Reverent Fragment', { best_edge: 0.06 }),
      loop('Small Item', { best_edge: 0.03 }),
      loop('Later Item', { best_edge: 0.4 }), // beyond the top 3 and larger, but listed later
    ]
    const flips = [flip('Never Shard', 50, 100, { chance: 0 }), flip('Orb of Conflict', 100, 110), flip('Chaos Shard', 100, 118)]
    serve([window(loops, flips)])
    renderPage()
    const l = await section('Loops that paid')
    expect(within(l).getByText('Best loop last hour: +6% on Reverent Fragment')).toBeInTheDocument()
    const f = await section('Volatile flips')
    // The first listed that went through, not the widest.
    expect(within(f).getByText('Top flip last hour: +10% on Orb of Conflict')).toBeInTheDocument()
  })

  it('has no takeaway when none qualifies', async () => {
    const loops = [loop('Odd Item', { best_edge: 0.9 }), loop('Never Item', { best_edge: 0.3, chance: 0 }), loop('Skip Item', { order_ok: false })]
    serve([window(loops, [flip('Never Shard', 50, 100, { chance: 0 })])])
    renderPage()
    const l = await section('Loops that paid')
    expect(within(l).getAllByText('Odd Item').length).toBeGreaterThan(0) // listed, but not named
    expect(within(l).queryByText(/^Best loop/)).not.toBeInTheDocument()
    const f = await section('Volatile flips')
    expect(within(f).getAllByText('Never Shard').length).toBeGreaterThan(0)
    expect(within(f).queryByText(/^Top flip/)).not.toBeInTheDocument()
  })

  it('opens Details on click, with nothing inside until then', async () => {
    serve([window([loop('Reverent Fragment')], [])])
    renderPage()
    const l = await section('Loops that paid')
    const details = within(l).getByRole('button', { name: 'Details' })
    const content = document.getElementById(details.getAttribute('aria-controls')!)!
    expect(details).toHaveAttribute('aria-expanded', 'false')
    expect(content).toHaveAttribute('hidden')
    expect(content).toBeEmptyDOMElement()
    expect(within(l).queryByText(/15 of 20 tries/)).not.toBeInTheDocument()
    fireEvent.click(details)
    expect(details).toHaveAttribute('aria-expanded', 'true')
    expect(content).not.toHaveAttribute('hidden')
    expect(within(content).getByText(/15 of 20 tries/)).toBeInTheDocument()
    fireEvent.click(details)
    expect(details).toHaveAttribute('aria-expanded', 'false')
    expect(content).toBeEmptyDOMElement()
  })

  it('shows the volume on the card when there is no price', async () => {
    serve([window([loop('Reverent Fragment', { price: null })], [])])
    renderPage()
    const l = await section('Loops that paid')
    expect(within(l).getByText(/traded through both markets an hour/)).toBeInTheDocument()
    expect(within(l).queryByText(/^price/)).not.toBeInTheDocument()
  })

  it('keeps the odds behind Details, and the warnings on the card', async () => {
    serve([window([loop('Odd Item', { best_edge: 0.9 }), loop('Never Item', { chance: 0, through: 0 })], [flip('Orb of Conflict', 100, 110)])])
    renderPage()
    const l = await section('Loops that paid')
    // By default: the headline, the route and the price, plus the warnings; the volume
    // sits behind Details.
    expect(within(l).getByText('+90%')).toBeInTheDocument()
    expect(within(l).getByText(/likely one odd trade/)).toBeInTheDocument()
    expect(within(l).getByText(/Its orders never went through lately/)).toBeInTheDocument()
    expect(within(l).getAllByText(/^price/)).toHaveLength(2)
    expect(within(l).queryByText(/traded through both markets an hour/)).not.toBeInTheDocument()
    expect(within(l).queryByText('Went through')).not.toBeInTheDocument()
    expect(within(l).queryByText(/tries in the last 3 days/)).not.toBeInTheDocument()
    const [odd] = within(l).getAllByRole('button', { name: 'Details' })
    expect(odd).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(odd!)
    expect(odd).toHaveAttribute('aria-expanded', 'true')
    expect(within(l).getByText('15 of 20 tries in the last 3 days, by the optimistic fill rule')).toBeInTheDocument()
    expect(within(l).getByText('75%')).toBeInTheDocument()
    expect(within(l).getAllByText(/traded through both markets an hour/)).toHaveLength(1)

    const f = await section('Volatile flips')
    expect(within(f).getByText(/^average/)).toBeInTheDocument()
    expect(within(f).queryByText('90%')).not.toBeInTheDocument()
    expect(within(f).queryByText(/range last hour/)).not.toBeInTheDocument()
    fireEvent.click(within(f).getByRole('button', { name: 'Details' }))
    expect(within(f).getByText('90%')).toBeInTheDocument()
    expect(within(f).getByText('54 of 60 tries in the last 3 days, by the optimistic fill rule')).toBeInTheDocument()
    expect(within(f).getByText(/range last hour/)).toBeInTheDocument()
  })

  it('says what to try instead when there is nothing', async () => {
    serve([window([], [])])
    renderPage()
    const l = await section('Loops that paid')
    expect(within(l).getByText(/No loop with enough volume beat a 2% edge/)).toBeInTheDocument()
    expect(within(l).getByText('Try the Volatile flips above, or check back after the next hour.')).toBeInTheDocument()
    expect(within(l).queryByText(/^Best loop/)).not.toBeInTheDocument()
    const f = await section('Volatile flips')
    expect(within(f).getByText(/No liquid item traded across a wide enough range/)).toBeInTheDocument()
    expect(within(f).getByText('Loops and card turn-ins below may still have something.')).toBeInTheDocument()
    expect(within(f).queryByText(/^Top flip/)).not.toBeInTheDocument()
  })
})
