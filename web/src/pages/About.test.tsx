import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Status } from '../api/client'
import { PREVIEW_MANIFEST, previewStatus } from '../test/preview'
import About from './About'

function serveStatus(status: Status) {
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify(status), { headers: { 'Content-Type': 'application/json' } })),
  )
}

function renderAbout() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <About />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

afterEach(() => vi.unstubAllGlobals())

describe('About', () => {
  it('explains the preview while it is on', async () => {
    serveStatus(previewStatus())
    renderAbout()
    expect(await screen.findByRole('heading', { name: 'The preview' })).toBeInTheDocument()
    expect(screen.getByText(new RegExp(`${PREVIEW_MANIFEST.league} rewound`))).toBeInTheDocument()
  })

  it('says nothing about it once the league is live', async () => {
    serveStatus(previewStatus({ preview: null, upcoming: null }))
    renderAbout()
    await waitFor(() => expect(globalThis.fetch).toHaveBeenCalled())
    await new Promise((resolve) => setTimeout(resolve, 20))
    expect(screen.queryByRole('heading', { name: 'The preview' })).not.toBeInTheDocument()
  })
})
