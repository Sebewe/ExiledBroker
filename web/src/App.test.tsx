import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { pageTitle } from './components/Layout'

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

describe('routes', () => {
  it('sends the retired Farming page to Price check', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(JSON.stringify({ detail: 'no data' }), { status: 503, headers: { 'Content-Type': 'application/json' } })),
    )
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
    render(
      <QueryClientProvider client={client}>
        <MemoryRouter initialEntries={['/farming']}>
          <App />
        </MemoryRouter>
      </QueryClientProvider>,
    )
    // Price check is a lazy chunk: under a busy test run its import can take over a second.
    expect(await screen.findByRole('heading', { name: 'Price check', level: 1 }, { timeout: 5000 })).toBeInTheDocument()
    expect(document.title).toBe('Price check · ExiledBroker')
  })
})

describe('page titles', () => {
  it("name the page first, so tabs and bookmarks tell pages apart", () => {
    expect(pageTitle('/')).toBe('Market recap · ExiledBroker')
    expect(pageTitle('/price-check')).toBe('Price check · ExiledBroker')
    expect(pageTitle('/launch')).toBe('Launch market · ExiledBroker')
    expect(pageTitle('/nowhere')).toBe('ExiledBroker')
  })
})
