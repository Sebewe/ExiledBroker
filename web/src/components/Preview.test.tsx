import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { LiveLeague, Status } from '../api/client'
import { PREVIEW_MANIFEST, previewStatus } from '../test/preview'
import { FreshnessBanner } from './Freshness'
import { Layout } from './Layout'
import { clock } from '../lib/countdown'
import { trackPage } from '../lib/usage'

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}

function renderAt(url: string, status: Status | null, child = <Where />) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url).pathname
      if (path === '/api/status' && status) return Response.json(status)
      return new Response('{"detail":"no data"}', { status: 503 })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Layout>
          <Routes>
            <Route path="*" element={child} />
          </Routes>
        </Layout>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

const LIVE: LiveLeague = { name: 'Allflame', latest_hour: '2026-10-01T00:00:00Z', hours: 300, launched_at: '2026-09-20T20:00:00Z', divine_chaos: 200 }
const liveStatus = (over: Partial<Status> = {}): Status => ({ now: '2026-11-01T12:00:00Z', data_version: 'v1', leagues: [LIVE], upcoming: null, preview: null, ...over })

afterEach(() => {
  localStorage.clear()
  vi.useRealTimers()
  vi.unstubAllGlobals()
})

describe('preview shell', () => {
  it('shows the Preview pill and the strip, with the launch day when only the date is known', async () => {
    renderAt('/', previewStatus())
    expect(await screen.findByText('Preview')).toBeInTheDocument()
    const strip = screen.getByRole('region', { name: 'Preview' })
    // The sample's default day is 2 (the real snapshot's is 5).
    expect(strip.textContent).toMatch(/looking at Mirage on day 2/)
    expect(strip.textContent).toMatch(/The next league launches Nov 13\. This switches to it live\./)
    expect(screen.queryByRole('timer')).not.toBeInTheDocument()
  })

  it('names the league once announced, and counts down once the time is known', async () => {
    const upcoming = { name: 'Keepers', start_date: '2026-11-13', time_known: true, start_at: '2026-11-13T20:00:00Z', first_data_at: '2026-11-13T21:08:00Z' }
    renderAt('/', previewStatus({ now: '2026-11-12T18:00:00Z', upcoming }))
    const timer = await screen.findByRole('timer')
    expect(screen.getByRole('region', { name: 'Preview' }).textContent).toMatch(/Keepers launches in/)
    // The server's clock, not the browser's: 26 hours (give or take the test's runtime).
    expect(timer.textContent).toMatch(/^1d 0[12]:\d\d:\d\d$/)
  })

  it('says the league is live while its first trades are still due', async () => {
    const upcoming = { name: null, start_date: '2026-11-13', time_known: true, start_at: '2026-11-13T20:00:00Z', first_data_at: '2026-11-13T21:08:00Z' }
    renderAt('/', previewStatus({ now: '2026-11-13T20:30:00Z', upcoming }))
    expect(await screen.findByText(/The next league is live/)).toBeInTheDocument()
  })

  it('picks the day in the URL, per page, and offers it only on the pages that read the snapshot', async () => {
    renderAt('/', previewStatus())
    const picker = await screen.findByRole('radiogroup', { name: 'League day' })
    expect(picker).toBeInTheDocument()
    expect(screen.getByRole('radio', { name: 'Day 2' })).toHaveAttribute('aria-checked', 'true')
    fireEvent.click(screen.getByRole('radio', { name: 'Day 3' }))
    expect(screen.getByTestId('where').textContent).toBe('/?day=3')
    expect(screen.getByRole('radio', { name: 'Day 3' })).toHaveAttribute('aria-checked', 'true')
    expect(screen.getByRole('region', { name: 'Preview' }).textContent).toMatch(/on day 3/)
    // The default isn't written to the URL.
    fireEvent.click(screen.getByRole('radio', { name: 'Day 2' }))
    expect(screen.getByTestId('where').textContent).toBe('/')
    fireEvent.click(screen.getByRole('link', { name: /Research/ }))
    expect(screen.queryByRole('radiogroup')).not.toBeInTheDocument()
    expect(screen.getByRole('region', { name: 'Preview' })).toBeInTheDocument()
  })

  it('counts picking another day as a preview-day use', async () => {
    const beacon = vi.fn((_url: string) => true)
    Object.defineProperty(navigator, 'sendBeacon', { value: beacon, configurable: true })
    trackPage('/') // a new page view: features count afresh
    renderAt('/', previewStatus())
    const days = () => beacon.mock.calls.filter(([url]) => url.includes('preview-day'))
    fireEvent.click(await screen.findByRole('radio', { name: 'Day 2' })) // already shown
    expect(days()).toHaveLength(0)
    fireEvent.click(screen.getByRole('radio', { name: 'Day 3' }))
    expect(days()).toEqual([['/api/hit?e=feature%3Apreview-day']])
    Object.defineProperty(navigator, 'sendBeacon', { value: undefined, configurable: true })
  })

  it('ignores a day the snapshot does not have', async () => {
    renderAt('/price-check?day=9', previewStatus())
    expect(await screen.findByRole('radio', { name: 'Day 2' })).toHaveAttribute('aria-checked', 'true')
  })

  it('replaces the freshness badge while on', async () => {
    renderAt('/', previewStatus({ leagues: [LIVE] }))
    await screen.findByText('Preview')
    expect(screen.queryByText(/data .* old/)).not.toBeInTheDocument()
  })

  it('adds the paper portfolio to the menu', async () => {
    renderAt('/', previewStatus())
    expect(await screen.findByRole('link', { name: 'Paper portfolio' })).toHaveAttribute('href', '/portfolio')
  })

  it('is absent while the preview is off', async () => {
    renderAt('/', liveStatus())
    expect(await screen.findByText(/Allflame · data/)).toBeInTheDocument()
    expect(screen.queryByText('Preview')).not.toBeInTheDocument()
    expect(screen.queryByRole('link', { name: 'Paper portfolio' })).not.toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Preview' })).not.toBeInTheDocument()
  })
})

describe('freshness banner in the preview', () => {
  const upcoming = { name: null, start_date: '2026-11-13', time_known: false, start_at: null, first_data_at: null }
  const old = PREVIEW_MANIFEST.days[0]!.league
  const banner = <FreshnessBanner league={old} now={Date.parse('2026-11-01T12:00:00Z')} upcoming={upcoming} />

  it('says neither "stale" nor "has ended" while the preview is on', async () => {
    renderAt('/', previewStatus(), banner)
    await screen.findByText('Preview')
    expect(screen.queryByText(/has ended/)).not.toBeInTheDocument()
    expect(screen.queryByText(/out of date/)).not.toBeInTheDocument()
  })

  it('still says the league has ended when it is off', async () => {
    renderAt('/', liveStatus({ upcoming }), banner)
    expect(await screen.findByText(/Mirage has ended/)).toBeInTheDocument()
  })
})

describe('clock', () => {
  it('formats days, hours, minutes and seconds', () => {
    expect(clock(0)).toBe('00:00')
    expect(clock(42 * 60_000 + 13_000)).toBe('42:13')
    expect(clock(((3 * 24 + 4) * 3600 + 12 * 60 + 9) * 1000)).toBe('3d 04:12:09')
    expect(clock(-5)).toBe('00:00')
  })
})
