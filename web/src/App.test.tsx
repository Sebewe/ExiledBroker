import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { pageTitle } from './components/Layout'

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

function renderApp(url: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ detail: 'no data' }), { status: 503, headers: { 'Content-Type': 'application/json' } })),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <App />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('routes', () => {
  it('sends the retired Farming page to Price check', async () => {
    renderApp('/farming')
    // Price check is a lazy chunk: under a busy test run its import can take over a second.
    expect(await screen.findByRole('heading', { name: 'Price check', level: 1 }, { timeout: 5000 })).toBeInTheDocument()
    // The title is set in an effect after the redirect, which can land after the heading shows.
    await waitFor(() => expect(document.title).toBe('Price check · ExiledBroker'))
  })

  it.each(['/backtest', '/research'])('sends %s to the Backtest, in Research', async (url) => {
    renderApp(url)
    expect(await screen.findByRole('heading', { name: 'Backtest', level: 1 }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Research' })).toBeInTheDocument()
    // The way back to trading: the Research banner points at the Market recap.
    expect(screen.getByText(/To trade, start from the/)).toContainElement(screen.getAllByRole('link', { name: 'Market recap' }).at(-1)!)
    await waitFor(() => expect(document.title).toBe('Backtest · Research · ExiledBroker'))
  })
})

describe('page titles', () => {
  it("name the page first, so tabs and bookmarks tell pages apart", () => {
    expect(pageTitle('/')).toBe('Market recap · ExiledBroker')
    expect(pageTitle('/price-check')).toBe('Price check · ExiledBroker')
    expect(pageTitle('/launch')).toBe('Launch market · ExiledBroker')
    expect(pageTitle('/research/backtest')).toBe('Backtest · Research · ExiledBroker')
    expect(pageTitle('/nowhere')).toBe('ExiledBroker')
  })
})
