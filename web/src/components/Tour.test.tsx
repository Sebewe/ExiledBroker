import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { useState } from 'react'
import { MemoryRouter, Route, Routes } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Status } from '../api/client'
import { resetTour } from '../lib/tour'
import { PREVIEW_MANIFEST, previewStatus } from '../test/preview'
import { Layout } from './Layout'

// The trading game's first-visit tour (Tour.tsx, lib/tour.ts). The game's own buttons are
// stood in for by their `data-tour` marks; the Portfolio link is the real menu's.

function Targets({ trade = true, next = true }: { trade?: boolean; next?: boolean }) {
  return (
    <div>
      {trade && (
        <button type="button" data-tour="trade">
          Trade this hour
        </button>
      )}
      {next && (
        <button type="button" data-tour="next-hour">
          Next hour
        </button>
      )}
    </div>
  )
}

function Leaving() {
  const [here, setHere] = useState(true)
  return (
    <>
      {here && <Targets />}
      <button type="button" onClick={() => setHere(false)}>
        Leave
      </button>
    </>
  )
}

function renderAt(status: Status, child = <Targets />) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (input: RequestInfo | URL) => {
      const path = new URL(typeof input === 'string' ? input : input instanceof URL ? input.href : input.url).pathname
      if (path === '/api/status') return Response.json(status)
      return new Response('{"detail":"no data"}', { status: 503 })
    }),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/']}>
        <Layout>
          <Routes>
            <Route path="*" element={child} />
          </Routes>
        </Layout>
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

/** The preview's welcome, accepted just now: the tour can start at once. */
const welcomed = () => localStorage.setItem('eb-preview-seen', JSON.stringify({ league: PREVIEW_MANIFEST.league, at: Date.now() }))
const tour = () => screen.findByRole('dialog', { name: 'Trading game tour' }, { timeout: 3000 })
/** Long enough for the tour to have started, had it been due. */
const settle = () => act(() => new Promise((r) => setTimeout(r, 900)))

afterEach(() => {
  localStorage.clear()
  resetTour()
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

describe('first-visit tour', () => {
  it('waits for the welcome, then points at Trade this hour, Next hour and Portfolio, once', async () => {
    const { unmount } = renderAt(previewStatus())
    fireEvent.click(await screen.findByRole('button', { name: 'Got it' })) // the welcome
    // Never on top of the welcome: it starts only once that's closed.
    let dialog = await tour()
    expect(dialog).toHaveAttribute('aria-modal', 'false')
    expect(dialog.textContent).toMatch(/Trade this hour/)
    expect(dialog.textContent).toMatch(/1 of 3/)
    expect(screen.getByRole('button', { name: 'Next' })).toHaveFocus()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    dialog = screen.getByRole('dialog', { name: 'Trading game tour' })
    expect(dialog.textContent).toMatch(/Next hour/)
    expect(dialog.textContent).toMatch(/2 of 3/)
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByRole('dialog', { name: 'Trading game tour' }).textContent).toMatch(/Portfolio shows/)
    fireEvent.click(screen.getByRole('button', { name: 'Got it' }))
    expect(screen.queryByRole('dialog', { name: 'Trading game tour' })).not.toBeInTheDocument()
    expect(localStorage.getItem('eb-tour-done')).not.toBeNull()
    unmount()

    // A later visit: never again.
    resetTour()
    renderAt(previewStatus())
    await screen.findByText('Preview')
    await settle()
    expect(screen.queryByRole('dialog', { name: 'Trading game tour' })).not.toBeInTheDocument()
  })

  it('does not show while the welcome is open', async () => {
    renderAt(previewStatus())
    await screen.findByRole('button', { name: 'Got it' })
    await settle()
    expect(screen.queryByRole('dialog', { name: 'Trading game tour' })).not.toBeInTheDocument()
  })

  it('starts at once when the welcome was accepted earlier, leaving out targets not on the page', async () => {
    welcomed()
    renderAt(previewStatus(), <Targets trade={false} />)
    const dialog = await tour()
    expect(dialog.textContent).toMatch(/Next hour/)
    expect(dialog.textContent).toMatch(/1 of 2/)
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByRole('dialog', { name: 'Trading game tour' }).textContent).toMatch(/2 of 2/)
  })

  it('moves past targets that went away mid-tour', async () => {
    welcomed()
    renderAt(previewStatus(), <Leaving />)
    expect((await tour()).textContent).toMatch(/Trade this hour/)
    // The visitor moves on: the trade and Next hour are gone, the Portfolio link stays.
    fireEvent.click(screen.getByRole('button', { name: 'Leave' }))
    await waitFor(() => expect(screen.getByRole('dialog', { name: 'Trading game tour' }).textContent).toMatch(/Portfolio shows/))
    expect(screen.getByRole('dialog', { name: 'Trading game tour' }).textContent).toMatch(/3 of 3/)
  })

  it('ends for good on Skip, or on Escape', async () => {
    welcomed()
    const { unmount } = renderAt(previewStatus())
    await tour()
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }))
    expect(screen.queryByRole('dialog', { name: 'Trading game tour' })).not.toBeInTheDocument()
    expect(localStorage.getItem('eb-tour-done')).not.toBeNull()
    unmount()

    localStorage.removeItem('eb-tour-done')
    resetTour()
    welcomed()
    renderAt(previewStatus())
    await tour()
    fireEvent.keyDown(document.body, { key: 'Escape' })
    expect(screen.queryByRole('dialog', { name: 'Trading game tour' })).not.toBeInTheDocument()
    expect(localStorage.getItem('eb-tour-done')).not.toBeNull()
  })

  it('shows at most once per page load without storage', async () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new Error('blocked')
    })
    const { unmount } = renderAt(previewStatus())
    fireEvent.click(await screen.findByRole('button', { name: 'Got it' })) // the welcome
    await tour()
    fireEvent.click(screen.getByRole('button', { name: 'Skip' }))
    unmount()
    renderAt(previewStatus())
    await screen.findByText('Preview')
    await settle()
    expect(screen.queryByRole('dialog', { name: 'Trading game tour' })).not.toBeInTheDocument()
  })

  it('is not shown when the preview is off or has no game', async () => {
    welcomed()
    const { unmount } = renderAt(previewStatus({ preview: null }))
    await settle()
    expect(screen.queryByRole('dialog', { name: 'Trading game tour' })).not.toBeInTheDocument()
    unmount()
    renderAt(previewStatus({ preview: { ...PREVIEW_MANIFEST, game: null } }))
    await screen.findByText('Preview')
    await settle()
    expect(screen.queryByRole('dialog', { name: 'Trading game tour' })).not.toBeInTheDocument()
    expect(localStorage.getItem('eb-tour-done')).toBeNull()
  })
})
