import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { useBacktest, useLeagues, useMissed, usePreviewItemNext, usePreviewRecapNext, usePriceCheckItem } from '../api/queries'
import { PREVIEW_DOCS, PREVIEW_MANIFEST, previewRoutes, previewStatus } from '../test/preview'
import { chooseDay, usePreview } from './preview'

let requested: string[] = []

function serve(routes: Record<string, { status?: number; body: unknown }>) {
  requested = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: Request | string) => {
      const url = new URL(typeof input === 'string' ? input : input.url, 'http://test')
      requested.push(url.pathname + url.search)
      const { status = 200, body } = routes[url.pathname] ?? { status: 404, body: { detail: 'not found' } }
      return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
    }),
  )
}

afterEach(() => vi.unstubAllGlobals())

function Probe() {
  const preview = usePreview()
  const leagues = useLeagues()
  const missed = useMissed(leagues[0]?.name)
  const item = usePriceCheckItem(leagues[0]?.name, 'currency:divine-orb')
  const next = usePreviewItemNext('currency:divine-orb')
  const recap = usePreviewRecapNext()
  useBacktest()
  return (
    <dl>
      <dt>on</dt>
      <dd data-testid="on">{String(preview.on)}</dd>
      <dd data-testid="day">{preview.day}</dd>
      <dd data-testid="league">{leagues.map((l) => `${l.name}@${l.latest_hour}`).join()}</dd>
      <dd data-testid="missed">{missed.data ? missed.data.map((w) => w.latest_hour).join() : 'none'}</dd>
      <dd data-testid="item">{item.data ? item.data.latest_hour : 'none'}</dd>
      <dd data-testid="next">{next.data ? next.data.series.length : next.fetchStatus}</dd>
      <dd data-testid="recap">{recap.data ? recap.data.latest_hour : recap.fetchStatus}</dd>
    </dl>
  )
}

function renderProbe(path = '/') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <Probe />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const doc = <T,>(key: string) => PREVIEW_DOCS[key] as T

describe('the preview switch', () => {
  it('reads the chosen day from the snapshot, and the Backtest live', async () => {
    serve({ '/api/status': { body: previewStatus() }, '/api/backtest': { body: [] }, ...previewRoutes() })
    renderProbe('/?day=3')
    const day3 = PREVIEW_MANIFEST.days.find((d) => d.day === 3)!.league
    await waitFor(() => expect(screen.getByTestId('missed')).not.toHaveTextContent('none'))
    expect(screen.getByTestId('day')).toHaveTextContent('3')
    expect(screen.getByTestId('league')).toHaveTextContent(`Mirage@${day3.latest_hour}`)
    const missed = doc<{ latest_hour: string }[]>('d3/missed')
    expect(screen.getByTestId('missed')).toHaveTextContent(missed[0]!.latest_hour)
    await waitFor(() => expect(screen.getByTestId('next')).not.toHaveTextContent('idle'))
    await waitFor(() => expect(screen.getByTestId('recap')).toHaveTextContent(doc<{ latest_hour: string }>('d3/recap-next').latest_hour))
    const v = `?v=${PREVIEW_MANIFEST.version}`
    expect(requested).toEqual(
      expect.arrayContaining([
        `/api/preview/d3/missed${v}`,
        `/api/preview/d3/price-check/currency:divine-orb${v}`,
        `/api/preview/next/price-check/currency:divine-orb${v}`,
        `/api/preview/d3/recap-next${v}`,
        '/api/backtest?v=v1',
      ]),
    )
    expect(requested.filter((r) => r.startsWith('/api/missed') || r.startsWith('/api/price-check'))).toEqual([])
  })

  it('falls back to the default day for a day the snapshot lacks', () => {
    expect(chooseDay(PREVIEW_MANIFEST, '9')).toBe(PREVIEW_MANIFEST.default_day)
    expect(chooseDay(PREVIEW_MANIFEST, 'x')).toBe(PREVIEW_MANIFEST.default_day)
    expect(chooseDay(PREVIEW_MANIFEST, '1')).toBe(1)
    expect(chooseDay(undefined, '1')).toBe(0)
  })

  it('stays live, and asks nothing of the preview, while it is off', async () => {
    const league = { name: 'Live', latest_hour: '2026-10-22T08:00:00Z', hours: 10, launched_at: '2026-10-21T20:00:00Z', divine_chaos: 150 }
    serve({
      '/api/status': { body: previewStatus({ preview: null, upcoming: null, leagues: [league] }) },
      '/api/missed/Live': { body: [] },
      '/api/backtest': { body: [] },
    })
    renderProbe('/?day=3')
    await waitFor(() => expect(screen.getByTestId('missed')).toHaveTextContent(''))
    await waitFor(() => expect(requested).toContain('/api/missed/Live?v=v1'))
    expect(screen.getByTestId('on')).toHaveTextContent('false')
    expect(screen.getByTestId('day')).toHaveTextContent('0')
    expect(screen.getByTestId('league')).toHaveTextContent('Live@')
    expect(screen.getByTestId('next')).toHaveTextContent('idle')
    expect(requested.filter((r) => r.startsWith('/api/preview'))).toEqual([])
  })
})
