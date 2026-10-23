import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { Layout } from './Layout'

function Where() {
  const l = useLocation()
  return <p data-testid="where">{l.pathname + l.search}</p>
}

function renderAt(url: string) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response('{}', { status: 503 })),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>
        <Layout>
          <Routes>
            <Route path="*" element={<Where />} />
          </Routes>
        </Layout>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

describe('remembered settings', () => {
  it('keeps each page’s settings when switching pages from the menu', () => {
    renderAt('/arbitrage?capital=20&sort=margin')
    fireEvent.click(screen.getByRole('link', { name: /Card turn-ins/ }))
    expect(screen.getByTestId('where').textContent).toBe('/cards')
    fireEvent.click(screen.getByRole('link', { name: /Arbitrage/ }))
    expect(screen.getByTestId('where').textContent).toBe('/arbitrage?capital=20&sort=margin')
  })

  it('brings them back on a later visit to the bare address', () => {
    localStorage.setItem('eb-settings', JSON.stringify({ '/arbitrage': '?capital=5' }))
    renderAt('/arbitrage')
    expect(screen.getByTestId('where').textContent).toBe('/arbitrage?capital=5')
  })
})
