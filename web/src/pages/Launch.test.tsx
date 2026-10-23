import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { LaunchPick, LaunchWindow } from '../api/client'
import Launch from './Launch'

function serve(routes: Record<string, { status?: number; body: unknown }>) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === 'string' ? input : input.url, 'http://test')
      const { status = 200, body } = routes[url.pathname] ?? {
        status: 404,
        body: { detail: 'not found' },
      }
      return new Response(JSON.stringify(body), {
        status,
        headers: { 'Content-Type': 'application/json' },
      })
    }),
  )
}

function renderLaunch() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Launch />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const LEAGUES = ['Allflame', 'Mirage', 'Keepers', 'Mercenaries', 'Settlers']
const pick = (rank: number, name: string, growth: number, live: number | null = null): LaunchPick => ({
  rank,
  item_id: `currency:${name}`,
  name,
  group_id: 'currency',
  score: 1 - rank / 10,
  growth,
  worst: growth * 0.8,
  rose: 4,
  traded: 5,
  buy_divine: 0.4,
  liquidity: 500,
  live_divine: live,
  leagues: LEAGUES.map((league, i) => ({
    league,
    growth: i === 4 ? null : i === 3 ? 0.9 : growth,
  })),
})
const window_ = (id: string, first: number, last: number, picks: LaunchPick[]): LaunchWindow => ({
  window_id: id,
  first_day: first,
  last_day: last,
  sell_first: 12,
  sell_last: 14,
  leagues: LEAGUES,
  chaos_growth: 0.45,
  typical_growth: 0.5,
  candidates: 70,
  built_at: '2026-10-22T00:00:00Z',
  live_league: 'Allflame',
  picks,
})
const BOARD = [
  window_('day1', 1, 1, [pick(1, 'Tempering Orb', 5.2, 0.3), pick(2, 'Orb of Conflict', 4.1), pick(3, 'Tainted Oil', 3.9), pick(4, 'Sacred Orb', 3.5)]),
  window_('days2_4', 2, 4, [pick(1, 'Orb of Dominance', 3.2)]),
  window_('days5_10', 5, 10, []),
]
const status = (launched: string, latest: string) => ({
  body: {
    now: latest,
    data_version: 'v1',
    leagues: [
      {
        name: 'Allflame',
        latest_hour: latest,
        hours: 30,
        launched_at: launched,
        divine_chaos: 200,
      },
    ],
  },
})

afterEach(() => vi.unstubAllGlobals())

describe('Launch market', () => {
  it('explains when nothing is loaded yet', async () => {
    serve({
      '/api/status': { status: 503, body: { detail: 'no data loaded yet' } },
    })
    renderLaunch()
    expect(await screen.findByText('No data yet')).toBeInTheDocument()
  })

  it('says when no picks have been built', async () => {
    serve({
      '/api/status': status('2026-10-22T00:00:00Z', '2026-10-22T05:00:00Z'),
      '/api/launch/picks': { body: [] },
    })
    renderLaunch()
    expect(await screen.findByText('No picks yet')).toBeInTheDocument()
  })

  it("opens on the live league's window, with live prices", async () => {
    serve({
      '/api/status': status('2026-10-22T00:00:00Z', '2026-10-22T05:00:00Z'),
      '/api/launch/picks': { body: BOARD },
    })
    renderLaunch()
    expect(await screen.findByText(/Allflame is on day 1: First grab is open now/)).toBeInTheDocument()
    expect(screen.getByRole('tab', { name: /First grab/ })).toHaveAttribute('aria-selected', 'true')
    const top = within(screen.getByRole('list', { name: 'Top picks' }))
    expect(top.getAllByRole('heading').map((h) => h.textContent)).toEqual(['Tempering Orb', 'Orb of Conflict', 'Tainted Oil'])
    expect(top.getByText('×5.2')).toBeInTheDocument()
    expect(top.getByText('(below usual)')).toBeInTheDocument() // 0.3 now against 0.4 usually
    expect(within(screen.getByRole('list', { name: 'Also good' })).getByText('Sacred Orb')).toBeInTheDocument()
    // 2 div held as Chaos: 0.9 div; in the #1 pick: 10.4 div.
    expect(screen.getByText('0.90div')).toBeInTheDocument()
    expect(screen.getAllByText('10.4div').length).toBeGreaterThan(0)
    expect(screen.getByText(/Chaos lost 55% of its value/)).toBeInTheDocument()
    expect(screen.getAllByLabelText('Beat holding Divines in 4 of 5 leagues')).toHaveLength(4)
  })

  it('is the playbook for the next league once the windows have passed', async () => {
    serve({
      '/api/status': status('2026-07-24T00:00:00Z', '2026-10-22T05:00:00Z'),
      '/api/launch/picks': { body: BOARD },
    })
    renderLaunch()
    expect(await screen.findByText(/past these windows/)).toBeInTheDocument()
    expect(screen.queryByText('(below usual)')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /Early climb/ }))
    expect(within(screen.getByRole('list', { name: 'Top picks' })).getByText('Orb of Dominance')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('tab', { name: /Last call/ }))
    expect(screen.getByText('No item passed the filters for this window.')).toBeInTheDocument()
  })
})
