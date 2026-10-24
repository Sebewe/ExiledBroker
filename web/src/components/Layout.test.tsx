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
    renderAt('/launch?window=days2_4')
    fireEvent.click(screen.getByRole('link', { name: /Backtest/ }))
    expect(screen.getByTestId('where').textContent).toBe('/backtest')
    fireEvent.click(screen.getByRole('link', { name: /Launch market/ }))
    expect(screen.getByTestId('where').textContent).toBe('/launch?window=days2_4')
  })

  it('brings them back on a later visit to the bare address', () => {
    localStorage.setItem('eb-settings', JSON.stringify({ '/launch': '?window=days5_10' }))
    renderAt('/launch')
    expect(screen.getByTestId('where').textContent).toBe('/launch?window=days5_10')
  })
})

describe('theme', () => {
  it('opens dark, switches to light and remembers it', () => {
    renderAt('/')
    expect(document.documentElement.dataset.theme).toBe('dark')
    fireEvent.click(screen.getByRole('button', { name: 'Switch to light mode' }))
    expect(document.documentElement.dataset.theme).toBe('light')
    expect(localStorage.getItem('eb-theme')).toBe('light')
    fireEvent.click(screen.getByRole('button', { name: 'Switch to dark mode' }))
    expect(document.documentElement.dataset.theme).toBe('dark')
  })
})
