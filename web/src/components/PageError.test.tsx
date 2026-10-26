import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { isChunkError, reloadForNewBuild } from '../lib/chunkReload'
import { PageError } from './PageError'

afterEach(() => {
  sessionStorage.clear()
  vi.restoreAllMocks()
})

function Boom({ error }: { error: Error }): never {
  throw error
}

function renderAt(key: string, error: Error | null) {
  return (
    <MemoryRouter>
      <PageError resetKey={key}>{error ? <Boom error={error} /> : <p>the page</p>}</PageError>
    </MemoryRouter>
  )
}

describe('a page that fails', () => {
  it('keeps the site up with a way out, and clears on the next page', () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    const { rerender } = render(renderAt('/launch', new Error('x is undefined')))
    expect(screen.getByRole('alert')).toHaveTextContent('Something went wrong on this page')
    expect(screen.getByRole('link', { name: 'go to the Market recap' })).toHaveAttribute('href', '/')
    rerender(renderAt('/', null))
    expect(screen.getByText('the page')).toBeInTheDocument()
  })

  it("says a chunk that couldn't load may be a new deploy", () => {
    vi.spyOn(console, 'error').mockImplementation(() => {})
    sessionStorage.setItem('eb-chunk-reload', String(Date.now())) // already reloaded once
    render(renderAt('/launch', new TypeError('Failed to fetch dynamically imported module: /assets/Launch-abc.js')))
    expect(screen.getByRole('alert')).toHaveTextContent("This page couldn't load")
    expect(screen.getByRole('button', { name: 'Reload' })).toBeInTheDocument()
  })
})

describe('reloading for a new build', () => {
  it('recognises the browsers’ chunk errors', () => {
    expect(isChunkError(new TypeError('Failed to fetch dynamically imported module: https://x/a.js'))).toBe(true)
    expect(isChunkError(new TypeError('Importing a module script failed.'))).toBe(true) // Safari
    expect(isChunkError(new Error('error loading dynamically imported module'))).toBe(true) // Firefox
    expect(isChunkError(new Error('Unable to preload CSS for /assets/a.css'))).toBe(true)
    expect(isChunkError(new Error('x is undefined'))).toBe(false)
  })

  it('reloads once a minute at most, so a broken deploy never loops', () => {
    const reload = vi.fn()
    expect(reloadForNewBuild(1_000_000, reload)).toBe(true)
    expect(reloadForNewBuild(1_030_000, reload)).toBe(false)
    expect(reloadForNewBuild(1_070_000, reload)).toBe(true)
    expect(reload).toHaveBeenCalledTimes(2)
  })
})
