import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'
import { pageTitle } from './components/Layout'
import { NOTES } from './research/notes'

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

  it.each([
    ['/backtest', 'Backtest', 'Backtest · Research · ExiledBroker'],
    ['/conversions', 'Multi-layered conversions', 'Multi-layered conversions · Research · ExiledBroker'],
    ['/about', 'About ExiledBroker', 'About · Research · ExiledBroker'],
  ])('sends %s to its page in Research', async (url, heading, title) => {
    renderApp(url)
    expect(await screen.findByRole('heading', { name: heading, level: 1 }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByRole('navigation', { name: 'Research' })).toBeInTheDocument()
    // The way back to trading.
    expect(screen.getByRole('link', { name: /To trade, start from the Market recap/ })).toHaveAttribute('href', '/')
    await waitFor(() => expect(document.title).toBe(title))
  })

  it('opens Research on its journal, newest note first', async () => {
    renderApp('/research')
    expect(await screen.findByRole('heading', { name: 'Research journal', level: 1 }, { timeout: 5000 })).toBeInTheDocument()
    const notes = within(screen.getByRole('list')).getAllByRole('link')
    expect(notes[0]).toHaveAttribute('href', `/research/notes/${NOTES[0]!.n}`)
    expect(notes).toHaveLength(NOTES.length)
    await waitFor(() => expect(document.title).toBe('Research · ExiledBroker'))
  })

  it('reads a note, with the notes either side and where to use it', async () => {
    renderApp('/research/notes/10')
    expect(await screen.findByRole('heading', { name: 'What repeats across the five exchange-era leagues', level: 1 }, { timeout: 5000 })).toBeInTheDocument()
    expect(screen.getByText(/How it was computed/)).toBeInTheDocument()
    expect(screen.getByRole('link', { name: /Use it: Launch market/ })).toHaveAttribute('href', '/launch')
    const more = within(screen.getByRole('navigation', { name: 'More notes' })).getAllByRole('link')
    expect(more.map((a) => a.getAttribute('href'))).toEqual(['/research/notes/9', '/research/notes/11'])
    // A link inside the note to another note stays in the app.
    fireEvent.click(screen.getAllByRole('link', { name: '3' })[0]!)
    expect(await screen.findByRole('heading', { name: /^Currency and cards hold their value best/, level: 1 })).toBeInTheDocument()
    await waitFor(() => expect(document.title).toBe('Note 3 · Research · ExiledBroker'))
  })

  it('says so for a note that does not exist', async () => {
    renderApp('/research/notes/999')
    expect(await screen.findByRole('heading', { name: 'No such note' }, { timeout: 5000 })).toBeInTheDocument()
  })

  it('links each method section back to its trading page', async () => {
    renderApp('/research/method')
    expect(await screen.findByRole('heading', { name: 'How the tools work', level: 1 }, { timeout: 5000 })).toBeInTheDocument()
    for (const id of ['loops', 'cards', 'flips', 'launch-picks', 'price-check']) expect(document.getElementById(id)).not.toBeNull()
    expect(screen.getAllByRole('link', { name: /Use it: Market recap/ })[0]).toHaveAttribute('href', '/#loops')
  })

})

describe('page titles', () => {
  it("name the page first, so tabs and bookmarks tell pages apart", () => {
    expect(pageTitle('/')).toBe('Market recap · ExiledBroker')
    expect(pageTitle('/price-check')).toBe('Price check · ExiledBroker')
    expect(pageTitle('/launch')).toBe('Launch market · ExiledBroker')
    expect(pageTitle('/research')).toBe('Research · ExiledBroker')
    expect(pageTitle('/research/backtest')).toBe('Backtest · Research · ExiledBroker')
    expect(pageTitle('/research/notes/4')).toBe('Note 4 · Research · ExiledBroker')
    expect(pageTitle('/nowhere')).toBe('ExiledBroker')
  })
})
