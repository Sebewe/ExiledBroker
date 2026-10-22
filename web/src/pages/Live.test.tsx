import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Live from './Live'

// The page as a visitor sees it, against a fake API: no data, a league waiting for its
// first trades, a stale feed, and a normal hour.
function serve(routes: Record<string, { status?: number; body: unknown }>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === 'string' ? input : input.url, 'http://test')
      const hit = Object.entries(routes).find(([path]) => url.pathname === path)
      const { status = 200, body } = hit?.[1] ?? { status: 404, body: { detail: 'not found' } }
      return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
    }),
  )
}

function renderLive() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Live />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const NOW = '2026-10-22T09:30:00Z'
const league = (latest: string | null) => ({ name: 'Allflame', latest_hour: latest, hours: 30, launched_at: '2026-10-21T00:00:00Z' })
const loop = {
  item_id: 'currency:x', name: 'Legion Scarab', hours: 6, paying_share: 1, overlap_chaos: 900, last_edge: 0.35,
  last_gap: 0.4, price: 2.06, last_hour: '2026-10-22T08:00:00Z', hours_since: 0, edge_now_rank: 1,
  consistency_rank: 1, volume_rank: 1, freshness_rank: 1, score: 0.79,
}

afterEach(() => vi.unstubAllGlobals())

describe('Live market', () => {
  it('explains when nothing is loaded yet', async () => {
    serve({ '/api/status': { status: 503, body: { detail: 'no data loaded yet' } } })
    renderLive()
    expect(await screen.findByText('No data yet')).toBeInTheDocument()
  })

  it('waits for the first trades of a new league', async () => {
    serve({ '/api/status': { body: { now: NOW, data_version: null, leagues: [league(null)] } } })
    renderLive()
    expect(await screen.findByText('Waiting for the first trades')).toBeInTheDocument()
    expect(screen.queryByRole('table')).not.toBeInTheDocument()
  })

  it('warns when the feed looks stopped', async () => {
    serve({
      '/api/status': { body: { now: NOW, data_version: 'v1', leagues: [league('2026-10-22T05:00:00Z')] } },
      '/api/live/Allflame/loops': { body: [] },
      '/api/live/Allflame/card-flips': { body: [] },
    })
    renderLive()
    expect(await screen.findByText('Data may be out of date')).toBeInTheDocument()
    expect(await screen.findByText(/Nothing beat the 2% buffer/)).toBeInTheDocument()
  })

  it('ranks the loops paying now', async () => {
    serve({
      '/api/status': { body: { now: NOW, data_version: 'v1', leagues: [league('2026-10-22T08:00:00Z')] } },
      '/api/live/Allflame/loops': { body: [loop] },
      '/api/live/Allflame/card-flips': { body: [] },
      '/api/arbitrage/hourly': { body: [] },
    })
    renderLive()
    expect(await screen.findByRole('cell', { name: 'Legion Scarab' })).toBeInTheDocument()
    expect(screen.getByText('+35.0%')).toBeInTheDocument()
    expect(screen.queryByText('Data may be out of date')).not.toBeInTheDocument()
  })
})
