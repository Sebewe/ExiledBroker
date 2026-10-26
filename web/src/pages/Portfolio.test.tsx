import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { ChartTokens } from '../lib/chartOptions'
import { portfolio } from '../lib/portfolio'
import { previewRoutes, previewStatus } from '../test/preview'
import Portfolio from './Portfolio'

// ECharts needs a canvas: stand in for the chart, building its option, exposing its series.
vi.mock('../components/Chart', () => ({
  default: ({ build, label }: { build: (t: ChartTokens) => { series: { name: string; data: unknown[] }[] }; label: string }) => {
    const t = { text: '', muted: '', faint: '', border: '', surface: '', surface2: '', accent: '#e3ac72', info: '#93b8f5' }
    const option = build(t)
    return <div role="img" aria-label={label} data-series={option.series.map((s) => `${s.name}:${s.data.length}`).join(',')} />
  },
}))

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

const routes = () => ({ ...previewRoutes(), '/api/status': { body: previewStatus() } })

afterEach(() => {
  vi.unstubAllGlobals()
  localStorage.clear()
  portfolio.reload()
})

describe('Paper portfolio', () => {
  it('says it was part of the preview once the preview is off', async () => {
    serve({ '/api/status': { body: previewStatus({ preview: null }) } })
    renderPage()
    expect(await screen.findByText('Part of the pre-launch preview')).toBeInTheDocument()
  })

  it('starts empty, and stakes an item picked from the search', async () => {
    serve(routes())
    renderPage()
    expect(await screen.findByText('Nothing staked yet')).toBeInTheDocument()
    const box = await screen.findByRole('combobox', { name: 'Add an item' })
    fireEvent.focus(box)
    fireEvent.change(box, { target: { value: 'Exalted' } })
    fireEvent.click(await screen.findByRole('option', { name: /Exalted Orb/ }))
    const row = (await screen.findByText('Exalted Orb')).closest('tr')!
    expect(within(row).getByRole('spinbutton', { name: /Stake on Exalted Orb/ })).toHaveValue(10)
    expect(JSON.parse(localStorage.getItem('eb-portfolio')!).positions).toEqual([{ item_id: 'currency:exalted-orb', name: 'Exalted Orb', stake: 10 }])
  })

  it('steps the clock forward and values the stakes then', async () => {
    portfolio.add({ item_id: 'currency:exalted-orb', name: 'Exalted Orb' })
    portfolio.add({ item_id: 'currency:not-in-snapshot', name: 'Gone Orb' })
    serve(routes())
    renderPage('/portfolio?day=2')
    const row = (await screen.findByText('Exalted Orb')).closest('tr')!
    expect(await within(row).findByText('10.0div')).toBeInTheDocument()
    expect(await screen.findByText("Not in the preview's data")).toBeInTheDocument()
    expect(screen.getByText(/Bought at the end of/)).toBeInTheDocument()
    expect(screen.getByRole('img').dataset.series).toBe('Your portfolio:1,Kept as Divines:1,Kept as Chaos:1')

    fireEvent.click(screen.getByRole('button', { name: 'Next hour' }))
    expect(screen.getByText('1 h')).toBeInTheDocument()
    expect(screen.getByText('Worth after 1 h')).toBeInTheDocument()
    expect(screen.getByRole('img').dataset.series).toBe('Your portfolio:2,Kept as Divines:2,Kept as Chaos:2')
    // The sample runs two hours past day 2: then the clock stops.
    fireEvent.click(screen.getByRole('button', { name: 'Next day' }))
    expect(screen.getByText("That's as far as the preview goes.")).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next hour' })).toBeDisabled()
    // The Exalt fell after day 2 (sample data), and the Divine rose: both read as a loss.
    expect(within(row).getByText(/^−|^-/)).toHaveClass('text-negative')
    expect(JSON.parse(localStorage.getItem('eb-portfolio')!).at).toBe(2)

    fireEvent.click(screen.getByRole('button', { name: 'Remove Gone Orb' }))
    expect(screen.queryByText('Gone Orb')).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Empty the portfolio/ }))
    expect(screen.getByText('Nothing staked yet')).toBeInTheDocument()
  })
})
