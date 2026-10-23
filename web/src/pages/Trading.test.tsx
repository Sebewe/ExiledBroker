import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ArbitrageItem, TurnIn } from '../api/client'
import Arbitrage from './Arbitrage'
import Cards from './Cards'

// Arbitrage and Card turn-ins: every option as a card, filtered in the browser by the
// viewer's capital, volume and margin, without asking the server again.
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

function renderPage(page: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{page}</MemoryRouter>
    </QueryClientProvider>,
  )
}

const STATUS = {
  body: {
    now: '2026-10-22T09:30:00Z',
    data_version: 'v1',
    leagues: [{ name: 'Allflame', latest_hour: '2026-10-22T08:00:00Z', hours: 30, launched_at: '2026-10-21T00:00:00Z', divine_chaos: 200 }],
  },
}
const titles = () =>
  within(screen.getByRole('region', { name: /Loops|Turn-ins/ }))
    .queryAllByRole('heading')
    .map((h) => h.textContent)
const fetches = () => vi.mocked(fetch).mock.calls.length

// hours: 10, so volume / hour = overlap / 10.
const loop = (name: string, edge: number, price: number, overlap: number): ArbitrageItem => ({
  item_id: `currency:${name}`,
  name,
  leagues: 1,
  weighted_share: 0.5,
  weighted_edge: edge,
  median_gap: edge,
  chaos_price: price,
  overlap_chaos: overlap,
  capacity_chaos: overlap * edge,
  hours: 10,
  worst_league_share: 0.5,
  score: 0.5,
  edge_rank: 0.5,
  consistency_rank: 0.5,
  worst_league_rank: 0.5,
  volume_rank: 0.5,
})
const LOOPS = [
  loop('Cheap Thin', 0.5, 10, 2_000), // 200c an hour can trade: small, whatever you invest
  loop('Deep Pool', 0.1, 50, 200_000), // 20,000c an hour: grows with capital
  loop('Pricey', 0.3, 5_000, 100_000), // 25 div for one item
]

const card = (name: string, margin: number, setCost: number, setsTraded: number): TurnIn => ({
  item_id: `currency:${name}`,
  name,
  filter_tier: 't1',
  stack_size: 5,
  reward_kind: 'currency',
  reward_name: 'Divine Orb',
  reward_quantity: 2,
  reward_item_id: 'currency:divine-orb',
  reward_fixed: true,
  reward_text: null,
  hours: 10,
  profitable_share: 1,
  margin,
  margin_pct: margin / setCost,
  set_cost: setCost,
  reward_value: setCost + margin,
  cards_traded: setsTraded * 5,
  sets_traded: setsTraded,
  score: 0.5,
  margin_rank: 0.5,
  investment_rank: 0.5,
  profitable_hours_rank: 0.5,
  volume_rank: 0.5,
})
const CARDS = [
  card('Small Set', 20, 100, 100), // 10 sets an hour, +20c each
  card('Big Set', 300, 1_500, 20), // 2 sets an hour, +300c each
  card('Loser', -5, 100, 50),
]

afterEach(() => vi.unstubAllGlobals())

describe('Arbitrage', () => {
  it('ranks loops by what a typical hour is worth with your capital', async () => {
    serve({ '/api/status': STATUS, '/api/arbitrage': { body: LOOPS } })
    renderPage(<Arbitrage />)
    await screen.findByRole('heading', { name: 'Deep Pool' })
    // 10 div = 2,000c: Deep Pool 0.5 × 2,000 × 10% = 100c; Cheap Thin 0.5 × 200 × 50% = 50c.
    expect(titles()).toEqual(['Deep Pool', 'Cheap Thin'])
    expect(screen.getByText(/1 more need over 10 div for a single item/)).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()

    const calls = fetches()
    fireEvent.click(screen.getByRole('button', { name: '100' })) // 100 div: Pricey is affordable
    expect(titles()).toEqual(['Pricey', 'Deep Pool', 'Cheap Thin'])
    fireEvent.change(screen.getByLabelText('Min margin'), { target: { value: '20' } })
    expect(titles()).toEqual(['Pricey', 'Cheap Thin'])
    fireEvent.change(screen.getByLabelText('Min volume / hour'), { target: { value: '5' } }) // 1,000c an hour
    expect(titles()).toEqual(['Pricey'])
    fireEvent.change(screen.getByLabelText('Min volume / hour'), { target: { value: '1000' } })
    expect(screen.getByText(/No loop matches/)).toBeInTheDocument()
    expect(fetches()).toBe(calls) // all in the browser
  })

  it('leaves out likely-junk margins unless asked', async () => {
    serve({ '/api/status': STATUS, '/api/arbitrage': { body: [...LOOPS, loop('Junk Ratio', 500, 10, 2_000)] } })
    renderPage(<Arbitrage />)
    await screen.findByRole('heading', { name: 'Deep Pool' })
    expect(titles()).not.toContain('Junk Ratio') // +50,000%
    fireEvent.change(screen.getByLabelText('Ignore margins above'), { target: { value: '100000' } })
    expect(titles()[0]).toBe('Junk Ratio')
  })

  it('sorts by margin or volume', async () => {
    serve({ '/api/status': STATUS, '/api/arbitrage': { body: LOOPS } })
    renderPage(<Arbitrage />)
    await screen.findByRole('heading', { name: 'Deep Pool' })
    fireEvent.click(screen.getByRole('radio', { name: 'Biggest margin' }))
    expect(titles()).toEqual(['Cheap Thin', 'Deep Pool'])
    fireEvent.click(screen.getByRole('radio', { name: 'Most volume' }))
    expect(titles()).toEqual(['Deep Pool', 'Cheap Thin'])
  })
})

describe('Card turn-ins', () => {
  it('shows profitable sets you can afford, best for your capital first', async () => {
    serve({ '/api/status': STATUS, '/api/cards/Allflame': { body: CARDS } })
    renderPage(<Cards />)
    await screen.findByRole('heading', { name: 'Small Set' })
    // 10 div = 2,000c: Big Set (1,500c) fits 1 set × 300c = 300c; Small Set min(20, 10) × 20c = 200c.
    expect(titles()).toEqual(['Big Set', 'Small Set'])
    expect(screen.getAllByText('5 cards turn into')).toHaveLength(2)
    fireEvent.click(screen.getByRole('button', { name: '5' })) // 1,000c: Big Set is out of reach
    expect(titles()).toEqual(['Small Set'])
    expect(screen.getByText(/1 more need over 5 div for a set/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Min margin'), { target: { value: '25' } }) // Small Set is +20%
    expect(screen.getByText(/No turn-in matches/)).toBeInTheDocument()
  })
})
