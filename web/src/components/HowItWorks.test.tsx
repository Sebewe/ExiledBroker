import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import type { ComponentType } from 'react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import Backtest from '../pages/Backtest'
import Launch from '../pages/Launch'
import Missed from '../pages/Missed'
import PriceCheck from '../pages/PriceCheck'

// Each trading page opens with one sentence and a "How this works" link to its section of
// Research's How the tools work. The header shows before any data arrives, so the server
// here never answers.

afterEach(() => vi.unstubAllGlobals())

function renderPage(Page: ComponentType) {
  vi.stubGlobal(
    'fetch',
    vi.fn(() => new Promise<Response>(() => {})),
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Page />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

describe('How this works', () => {
  it.each([
    ['Market recap', Missed, 'prices'],
    ['Price check', PriceCheck, 'price-check'],
    ['Launch market', Launch, 'launch-picks'],
    ['Backtest', Backtest, 'backtest'],
  ] as const)('%s links its intro to the method', (_, Page, anchor) => {
    renderPage(Page)
    const link = screen.getByRole('link', { name: 'How this works' })
    expect(link.getAttribute('href')).toBe(`/research/method#${anchor}`)
  })
})
