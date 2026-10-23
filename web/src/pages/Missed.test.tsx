import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { MissedWindow } from '../api/client'
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
  loops: [{ item_id: 'currency:d', name: 'Reverent Fragment', direction: 'chaos_first', missed: 2000 * scale, best_edge: 1.2, hours_paid: hours, price: 50 }],
  cards: [
    { item_id: 'currency:e', name: 'The Sephirot', reward: '10× Divine Orb', missed: 1000 * scale, margin: 400, set_cost: 1600, sets: 2.5, hours_paid: 1 },
  ],
  loops_missed: 3000 * scale,
  cards_missed: 1000 * scale,
})
const RECAP = [recap(1, 1), recap(2, 2), recap(3, 3)]

afterEach(() => vi.unstubAllGlobals())

describe('Missed opportunities', () => {
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

  it('recaps the last hour, in Divines', async () => {
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body: RECAP } })
    renderPage()
    const hero = await screen.findByRole('region', { name: 'Recap' })
    expect(within(hero).getByText('20.0div')).toBeInTheDocument() // (3000 + 1000)c at 200c
    expect(screen.getByText('Domination Scarab')).toBeInTheDocument()
    expect(screen.getByText(/up 3h running · momentum/)).toBeInTheDocument()
    expect(screen.getByText(/down 2h running · still sliding/)).toBeInTheDocument()
    expect(screen.getByText('600% range')).toBeInTheDocument()
    expect(screen.getByText('10.0div')).toBeInTheDocument() // the best loop, 2000c
    expect(screen.getByText('40.0c → 60.0c')).toBeInTheDocument() // under a Divine: Chaos
    expect(screen.getByText('10× Divine Orb')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('switches look-back without asking the server again', async () => {
    serve({ '/api/status': status('2026-10-22T08:00:00Z'), '/api/missed/Allflame': { body: RECAP } })
    renderPage()
    await screen.findByRole('region', { name: 'Recap' })
    const calls = vi.mocked(fetch).mock.calls.length
    fireEvent.change(screen.getByRole('slider'), { target: { value: '3' } })
    expect(await screen.findByText('60.0div')).toBeInTheDocument() // 3 × 20 div
    expect(screen.getByText('paid every hour')).toBeInTheDocument()
    expect(vi.mocked(fetch).mock.calls.length).toBe(calls)
  })
})
