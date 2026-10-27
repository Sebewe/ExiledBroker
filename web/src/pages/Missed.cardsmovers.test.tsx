import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MissedCard, MissedWindow } from '../api/client'
import Missed from './Missed'

// Market recap's card turn-ins and Market Movers: a one-line takeaway each, the card's
// odds behind Details, and empty states that say what to try instead.
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
// divine_chaos null: money reads in Chaos, so the amounts are easy to spell.
const status = { body: { now: NOW, data_version: 'v1', leagues: [{ name: 'Allflame', latest_hour: '2026-10-22T08:00:00Z', hours: 30, launched_at: '2026-10-21T00:00:00Z', divine_chaos: null }] } }

const card = (name: string, margin: number, extra: Partial<MissedCard> = {}): MissedCard => ({
  item_id: `currency:${name.toLowerCase().replace(/\W+/g, '-')}`,
  name,
  reward: '1× Exalted Orb',
  worst_roll: false,
  missed: margin * 3,
  margin,
  set_cost: 40,
  sets: 2.5,
  hours_paid: 1,
  tries: 20,
  through: 15,
  chance: 0.75,
  ...extra,
})

const window = (over: Partial<MissedWindow> = {}): MissedWindow => ({
  hours: 1,
  latest_hour: '2026-10-22T08:00:00Z',
  rising: [{ item_id: 'currency:regret', name: 'Orb of Regret', price: 1.14, before: 1, change: 0.14, volume: 5000, streak: 1 }],
  falling: [{ item_id: 'currency:gcp', name: "Gemcutter's Prism", price: 0.91, before: 1, change: -0.09, volume: 3000, streak: -1 }],
  volatile: [],
  flips: [],
  ticker: [],
  loops: [],
  cards: [card('The Chains that Bind', 12)],
  loops_paid: 0,
  cards_paid: 1,
  ...over,
})

const section = async (name: string) => (await screen.findByRole('heading', { level: 2, name })).closest('section')!

afterEach(() => vi.unstubAllGlobals())

describe('Market recap: card turn-ins', () => {
  it('opens with the first card in list order that went through', async () => {
    const cards = [
      card('Never Filled', 90, { through: 0, chance: 0 }), // its orders never went through
      card('Skip Card', 50, { order_ok: false }), // its orders are to be skipped this hour
      card('The Chains that Bind', 12),
      card('Small One', 5),
      card('Later Card', 60), // beyond the top 3 and larger, but listed later
    ]
    serve({ '/api/status': status, '/api/missed/Allflame': { body: [window({ cards })] } })
    renderPage()
    const cardsBlock = await section('Card turn-ins that paid')
    expect(within(cardsBlock).getByText('Best turn-in last hour: +12.0c a set on The Chains that Bind')).toBeInTheDocument()
  })

  it('has no takeaway when no card qualifies', async () => {
    const cards = [card('First Card', 3, { chance: 0, through: 0 }), card('Second Card', 8, { order_ok: false })]
    serve({ '/api/status': status, '/api/missed/Allflame': { body: [window({ cards })] } })
    renderPage()
    const cardsBlock = await section('Card turn-ins that paid')
    expect(within(cardsBlock).getAllByText('First Card').length).toBeGreaterThan(0) // listed, but not named
    expect(within(cardsBlock).queryByText(/Best turn-in/)).not.toBeInTheDocument()
  })

  it('keeps the odds behind Details and the price on the card', async () => {
    serve({ '/api/status': status, '/api/missed/Allflame': { body: [window()] } })
    renderPage()
    const cardsBlock = await section('Card turn-ins that paid')
    expect(within(cardsBlock).getByText('set costs 40.0c')).toBeInTheDocument()
    expect(within(cardsBlock).getByText('1× Exalted Orb')).toBeInTheDocument()
    expect(within(cardsBlock).queryByText(/15 of 20 tries/)).not.toBeInTheDocument()
    expect(within(cardsBlock).queryByText('Went through')).not.toBeInTheDocument()
    expect(within(cardsBlock).queryByText(/sets traded/)).not.toBeInTheDocument()
    const details = within(cardsBlock).getByRole('button', { name: 'Details' })
    expect(details).toHaveAttribute('aria-expanded', 'false')
    fireEvent.click(details)
    expect(details).toHaveAttribute('aria-expanded', 'true')
    expect(within(cardsBlock).getByText(/15 of 20 tries in the last 3 days/)).toBeInTheDocument()
    expect(within(cardsBlock).getByText('Went through')).toBeInTheDocument()
    expect(within(cardsBlock).getByText(/sets traded/)).toBeInTheDocument()
  })

  it('warns about a profit that never went through without opening Details', async () => {
    serve({ '/api/status': status, '/api/missed/Allflame': { body: [window({ cards: [card('Never Filled', 9, { through: 0, chance: 0 })] })] } })
    renderPage()
    const cardsBlock = await section('Card turn-ins that paid')
    expect(within(cardsBlock).getByText(/Its orders never went through lately/)).toBeInTheDocument()
    expect(within(cardsBlock).getByRole('button', { name: 'Details' })).toHaveAttribute('aria-expanded', 'false')
  })

  it('says what to try when no card paid, with no takeaway', async () => {
    serve({ '/api/status': status, '/api/missed/Allflame': { body: [window({ cards: [], cards_paid: 0 })] } })
    renderPage()
    const cardsBlock = await section('Card turn-ins that paid')
    expect(within(cardsBlock).getByText(/No card turn-in paid/)).toBeInTheDocument()
    expect(within(cardsBlock).getByText('Try the loops and flips above, or check back after the next hour.')).toBeInTheDocument()
    expect(within(cardsBlock).queryByText(/Best turn-in/)).not.toBeInTheDocument()
  })
})

describe('Market recap: Market Movers', () => {
  it('opens with the biggest rise and fall', async () => {
    serve({ '/api/status': status, '/api/missed/Allflame': { body: [window()] } })
    renderPage()
    const movers = await section('Market Movers')
    expect(within(movers).getByText("Biggest rise last hour: +14% on Orb of Regret; biggest fall: −9% on Gemcutter's Prism")).toBeInTheDocument()
    expect(within(movers).queryByText(/held steady/)).not.toBeInTheDocument()
  })

  it('names only the side that moved', async () => {
    serve({ '/api/status': status, '/api/missed/Allflame': { body: [window({ rising: [] })] } })
    renderPage()
    const movers = await section('Market Movers')
    expect(within(movers).getByText("Biggest fall last hour: −9% on Gemcutter's Prism")).toBeInTheDocument()
    expect(within(movers).getByText('Nothing liquid rose.')).toBeInTheDocument()
    expect(within(movers).queryByText(/held steady/)).not.toBeInTheDocument() // the other side moved
  })

  it('says prices held steady when nothing moved, as its takeaway', async () => {
    serve({ '/api/status': status, '/api/missed/Allflame': { body: [window({ rising: [], falling: [] })] } })
    renderPage()
    const movers = await section('Market Movers')
    expect(within(movers).getAllByText('Prices held steady last hour')).toHaveLength(1) // the takeaway; no hint in the boxes
    expect(within(movers).getByText('Nothing liquid rose.')).toBeInTheDocument()
    expect(within(movers).getByText('Nothing liquid fell.')).toBeInTheDocument()
    expect(within(movers).queryByText(/Biggest/)).not.toBeInTheDocument()
  })
})

describe('Market recap: nothing to recap', () => {
  it('points to Price check and Launch market meanwhile', async () => {
    serve({ '/api/status': status, '/api/missed/Allflame': { body: [] } })
    renderPage()
    expect(await screen.findByText('Nothing to recap yet')).toBeInTheDocument()
    expect(screen.getByText(/about an hour after the last one/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: 'Price check' })).toHaveAttribute('href', '/price-check')
    expect(screen.getByRole('link', { name: 'Launch market' })).toHaveAttribute('href', '/launch')
  })
})
