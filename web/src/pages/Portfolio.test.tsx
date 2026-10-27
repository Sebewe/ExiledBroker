import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { placeFlip, placeOrder, startGame, step } from '../lib/game'
import { reloadGame, setGame, type GameState } from '../lib/gameStore'
import { gameHourDoc, previewRoutes, previewStatus } from '../test/preview'
import Portfolio from './Portfolio'

function serve(routes: Record<string, { status?: number; body: unknown }>) {
  const fetch = vi.fn(async (input: Request | string) => {
    const url = new URL(typeof input === 'string' ? input : input.url, 'http://test')
    const { status = 200, body } = routes[url.pathname] ?? { status: 404, body: { detail: 'not found' } }
    return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
  })
  vi.stubGlobal('fetch', fetch)
  return fetch
}

function renderPage(url = '/portfolio') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Portfolio />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const ok = (x: GameState | string) => {
  if (typeof x === 'string') throw new Error(x)
  return x
}

const FLIP = {
  item_id: 'currency:f',
  name: 'Orb of Conflict',
  price: 100,
  low: 80,
  high: 120,
  range: 0.4,
  volume: 50000,
  bid: 80,
  ask: 110,
  bid_lot: 1,
  bid_total: 80,
  ask_lot: 1,
  ask_total: 110,
  cut: 0.1,
}
const LOOP = { kind: 'loop' as const, item_id: 'currency:d', direction: 'chaos_first', filled: true, spent: 500, pnl: 50, settle_at: gameHourDoc(25).latest_hour, lot: 100 }
const H25 = gameHourDoc(25, { prices: { 'currency:f': [78, 90, 100, 1000] } })

/** A game at hour 25: a loop bought and sold at +10%, and 5 Orbs of Conflict held. */
function played() {
  let s = ok(placeOrder(startGame('Mirage', 24), gameHourDoc(24), LOOP, 'Reverent Fragment', 2))
  s = ok(placeFlip(s, gameHourDoc(24), FLIP, 5))
  setGame(step(s, H25))
}

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
  reloadGame()
})

describe('Portfolio (the trading game)', () => {
  it('says it was part of the preview once the preview is off', async () => {
    serve({ '/api/status': { body: previewStatus({ preview: null }) } })
    renderPage()
    expect(await screen.findByText('Part of the pre-launch preview')).toBeInTheDocument()
  })

  it('says how to start before any trade', async () => {
    serve({ ...previewRoutes(), '/api/status': { body: previewStatus() } })
    renderPage()
    expect(await screen.findByText('No trades yet')).toBeInTheDocument()
  })

  it('lists the closed trades with what they made, and the flips held', async () => {
    played()
    serve({ ...previewRoutes(), '/api/status': { body: previewStatus() }, '/api/preview/game/25': { body: H25 } })
    renderPage()
    const history = await screen.findByRole('table')
    const row = within(history).getAllByRole('row')[1]!
    expect(row).toHaveTextContent('+20.0c')
    expect(row).toHaveTextContent('Loop: Reverent Fragment (Chaos first)')
    expect(row).toHaveTextContent('Sold, Day 2, 20:00 UTC')
    expect(screen.getByText('Orb of Conflict', { exact: false })).toBeInTheDocument()
    expect(screen.getByText(/Holding 5 of 5/)).toBeInTheDocument()
    // What it was bought at, and the wallet: 2 loop purchases and 5 bids took the 200c and 4 div exchanged.
    expect(screen.getByText('80.0c each')).toBeInTheDocument()
    expect(screen.getAllByText('6.00div · 220.0c')).toHaveLength(2) // the Wallet stat and the bar
    // The bar steps the clock from here too.
    const bar = within(screen.getByRole('region', { name: 'Trading game' }))
    expect(bar.getByRole('button', { name: 'Next hour' })).toBeEnabled()
    expect(bar.queryByRole('link', { name: 'Your trades' })).toBeNull()
    // Listed at the recap's ask (auto), or a price of the player's.
    expect(screen.getByText('110.0c')).toBeInTheDocument()
    fireEvent.change(screen.getByPlaceholderText('c each'), { target: { value: '150' } })
    fireEvent.click(screen.getByRole('button', { name: 'Set' }))
    expect(await screen.findByText('150.0c')).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('eb-game')!).open[0].listing).toBe(150)
    // Sold now at the hour's lowest trade: 5 × 78c.
    fireEvent.click(screen.getByRole('button', { name: /Sell now/ }))
    expect(await screen.findByText('Nothing open.')).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('eb-game')!).chaos).toBeCloseTo(220 + 390)
  })

  it('flags what never sold as Dump now, and sells it now', async () => {
    const stuck = { ...LOOP, pnl: -100, unsold: true, hold: 'currency:d', units: 4 }
    const h25 = gameHourDoc(25, { prices: { 'currency:d': [20, 22, 25, 100] } })
    setGame(step(ok(placeOrder(startGame('Mirage', 24), gameHourDoc(24), stuck, 'Reverent Fragment', 1)), h25))
    serve({ ...previewRoutes(), '/api/status': { body: previewStatus() }, '/api/preview/game/25': { body: h25 } })
    renderPage()
    expect(await screen.findByText('Dump now')).toBeInTheDocument()
    expect(screen.getByText(/Its sale didn't fill: holding 4 Reverent Fragment, averaging 22\.0c/)).toBeInTheDocument()
    // Worth what Sell now gets (4 × 20c), not the average.
    expect(document.body.textContent).toContain('worth 80.0c')
    fireEvent.click(await screen.findByRole('button', { name: /Sell now/ }))
    expect(await screen.findByText('Nothing open.')).toBeInTheDocument()
    expect(JSON.parse(localStorage.getItem('eb-game')!).chaos).toBeCloseTo(100 + 80)
  })

  it('resets the game', async () => {
    played()
    serve({ ...previewRoutes(), '/api/status': { body: previewStatus() }, '/api/preview/game/25': { body: H25 } })
    renderPage()
    fireEvent.click(await screen.findByRole('button', { name: 'Reset game' }))
    fireEvent.click(screen.getByRole('button', { name: 'Reset' }))
    expect(await screen.findByText('No trades yet')).toBeInTheDocument()
  })
})
