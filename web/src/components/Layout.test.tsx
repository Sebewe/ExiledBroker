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
    fireEvent.click(screen.getByRole('link', { name: /About/ }))
    expect(screen.getByTestId('where').textContent).toBe('/about')
    fireEvent.click(screen.getByRole('link', { name: /Launch market/ }))
    expect(screen.getByTestId('where').textContent).toBe('/launch?window=days2_4')
  })

  it('brings them back on a later visit to the bare address', () => {
    localStorage.setItem('eb-settings', JSON.stringify({ '/launch': '?window=days5_10' }))
    renderAt('/launch')
    expect(screen.getByTestId('where').textContent).toBe('/launch?window=days5_10')
  })
})

describe('menu', () => {
  it('puts Market recap first, then Price check, both lit up, and has no Farming tab', () => {
    renderAt('/')
    const links = screen.getAllByRole('link').filter((a) => a.closest('nav'))
    expect(links.slice(0, 2).map((a) => a.textContent)).toEqual(['Market recap', 'Price check'])
    expect(links[1]!.getAttribute('href')).toBe('/price-check')
    expect(links[1]!.className).toMatch(/border-accent/)
    expect(screen.queryByRole('link', { name: /Farming/ })).not.toBeInTheDocument()
  })

  it('fills the page you are on solid, so it never looks like just another lit-up page', () => {
    renderAt('/price-check')
    const recap = screen.getByRole('link', { name: /Market recap/ })
    const here = screen.getByRole('link', { name: /Price check/ })
    expect(here).toHaveAttribute('aria-current', 'page')
    expect(here.className).toMatch(/(^| )bg-accent( |$)/)
    expect(recap.className).not.toMatch(/(^| )bg-accent( |$)/)
  })

  it('keeps the Backtest out of the trading menu, behind Research, set apart in blue', () => {
    renderAt('/')
    expect(screen.queryByRole('link', { name: /Backtest/ })).not.toBeInTheDocument()
    const research = screen.getByRole('link', { name: /Research/ })
    expect(research).toHaveAttribute('href', '/research')
    expect(research.className).toMatch(/border-info/)
    expect(research.className).not.toMatch(/accent/)
    expect(research).toHaveAttribute('title', expect.stringMatching(/^The proof behind the tools/))
  })

  it('lights Research on every page under it', () => {
    renderAt('/research/backtest')
    expect(screen.getByRole('link', { name: /Research/ })).toHaveAttribute('aria-current', 'page')
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

describe('social links', () => {
  it('links the X and Discord logos, opening in a new tab', () => {
    renderAt('/')
    expect(screen.getByRole('link', { name: 'ExiledBroker on X' }).getAttribute('href')).toBe('https://x.com/BBagoza')
    const discord = screen.getByRole('link', { name: 'Join the ExiledBroker Discord' })
    expect(discord.getAttribute('href')).toBe('https://discord.gg/wK7uR32gx')
    expect(discord.getAttribute('target')).toBe('_blank')
  })
})
