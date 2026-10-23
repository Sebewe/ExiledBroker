import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { BacktestLimit, BacktestHourly, BacktestLaunch, BacktestReport } from '../api/client'
import Backtest from './Backtest'

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

function renderBacktest() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Backtest />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const STATUS = { now: '2026-10-23T12:00:00Z', data_version: 'v1', leagues: [], upcoming: null }

const hourly = (strategy: string, rule: string, scenario: string, per_hour: number): BacktestHourly => ({
  league: 'Mirage',
  segment: 'launch',
  strategy,
  rule,
  scenario,
  hours: 336,
  signals: 900,
  filled: 400,
  won: 200,
  total: per_hour * 336,
  per_hour,
  best_hour: 3,
  worst_hour: -3,
  daily: [1, 2],
})

const launch = (window_id: string, harsh: number): BacktestLaunch => ({
  league: 'Mirage',
  window_id,
  references: ['Keepers', 'Mercenaries', 'Settlers'],
  staked: 75,
  fair: harsh * 1.6,
  harsh,
  fair_profit: 75 * (harsh * 1.6 - 1),
  harsh_profit: 75 * (harsh - 1),
  typical_fair: 0.43,
  typical_harsh: 0.2,
  picks: [{ name: 'Gemcutter’s Prism', rank: 1, stake: 10, fair: 4, harsh: 2.5 }],
})

const limit = (strategy: string, method: string, fill: string, per_hour: number, filled: number): BacktestLimit => ({
  league: 'Mirage',
  segment: 'launch',
  strategy,
  method,
  fill,
  hours: 336,
  signals: 300,
  filled,
  won: filled,
  total: per_hour * 336,
  per_hour,
  best_hour: 1,
  worst_hour: -1,
  daily: [1],
})

const REPORT: BacktestReport = {
  built_at: '2026-10-23T10:00:00Z',
  leagues: ['Settlers', 'Mercenaries', 'Keepers', 'Mirage'],
  assumptions: {
    bank_divines: 100,
    trade_divines: 10,
    top: 3,
    capture: 0.1,
    slippage: 0.01,
    steady_hours: 3,
    hold_hours: 2,
    launch_stake: 10,
  },
  hourly: ['fair', 'harsh'].flatMap((s) => [
    hourly('loops', 'top', s, s === 'fair' ? 0.8 : 0.05),
    hourly('loops', 'steady', s, s === 'fair' ? 0.94 : 0.27),
    hourly('cards', 'top', s, s === 'fair' ? 0.33 : -0.94),
    hourly('cards', 'steady', s, s === 'fair' ? 0.32 : -0.89),
    hourly('rising', 'top', s, s === 'fair' ? -0.76 : -6.17),
    hourly('rising', 'steady', s, s === 'fair' ? -0.93 : -9.7),
  ]),
  persistence: [{ league: 'Mirage', segment: 'launch', flagged: 0.63, others: 0.09 }],
  limits: [
    limit('cards', 'market', 'touch', -1.01, 150),
    limit('cards', 'limit', 'touch', 0.66, 100),
    limit('cards', 'limit', 'strict', 0, 4),
    limit('loops', 'market', 'touch', -1.23, 250),
    limit('loops', 'limit', 'touch', 0.29, 100),
    limit('loops', 'limit', 'strict', 0.02, 4),
    limit('loops', 'limit_mid', 'touch', 0.78, 200),
    limit('loops', 'limit_mid', 'strict', 0.32, 90),
  ],
  launch: [launch('day1', 3.49), launch('days2_4', 1.31), launch('days5_10', 0.84)],
}

afterEach(() => vi.unstubAllGlobals())

describe('Backtest', () => {
  it('explains that nothing has been built yet', async () => {
    serve({ '/api/status': { body: STATUS }, '/api/backtest': { body: [] } })
    renderBacktest()
    expect(await screen.findByText('No backtest yet')).toBeTruthy()
  })

  it('leads with the verdicts, from the report’s numbers', async () => {
    serve({ '/api/status': { body: STATUS }, '/api/backtest': { body: [REPORT] } })
    renderBacktest()
    // The best option for each strategy, with the strategy named.
    const verdict = await screen.findByRole('region', { name: 'Verdict' })
    expect(within(verdict).getByText('Hold for days · Launch picks')).toBeTruthy()
    expect(within(verdict).getByText('Buy the day-1 picks, sell in days 12–14')).toBeTruthy()
    expect(screen.getAllByText('×3.49').length).toBeGreaterThan(0) // the day-1 picks, harsh
    expect(within(verdict).getByText('+0.78 div/h')).toBeTruthy() // loops, mid-range orders
    expect(within(verdict).getByText(/\+0\.32 if the hour's average has to cross it/)).toBeTruthy()
    expect(within(verdict).getByText('+0.66 div/h')).toBeTruthy() // cards, limit orders at the low
    expect(screen.getByText(/63% of the time, against 9%/)).toBeTruthy()
    expect(screen.getByText("Mirage's day-1 picks")).toBeTruthy()
    expect(screen.getByText('Loops, worst case')).toBeTruthy()
    // One table for both strategies, each limit cell with both fill models.
    const table = screen.getByRole('table', { name: 'Card turn-ins and loops with limit orders' })
    expect(within(table).getByText('Loops, limit orders mid-range')).toBeTruthy()
    expect(within(table).getByText('+0.32')).toBeTruthy() // strict fill, under +0.78
    expect(screen.getByText(/Loops did best bidding mid-range \(\+0\.78/)).toBeTruthy()
  })
})
