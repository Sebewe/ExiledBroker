import { QueryClient } from '@tanstack/react-query'
import { afterEach, describe, expect, it } from 'vitest'
import { restore, save } from './persist'

const client = () => new QueryClient({ defaultOptions: { queries: { gcTime: Infinity } } })

afterEach(() => localStorage.clear())

describe('the saved cache', () => {
  it("comes back on the next visit: the status and the current version's data only", () => {
    const a = client()
    a.setQueryData(['status'], { data_version: 'v2' })
    a.setQueryData(['missed', 'Allflame', 'v2'], [{ hours: 1 }])
    a.setQueryData(['missed', 'Allflame', 'v1'], [{ hours: 1, old: true }]) // superseded
    save(a, 'build1')

    const b = client()
    restore(b, 'build1')
    expect(b.getQueryData(['status'])).toEqual({ data_version: 'v2' })
    expect(b.getQueryData(['missed', 'Allflame', 'v2'])).toEqual([{ hours: 1 }])
    expect(b.getQueryData(['missed', 'Allflame', 'v1'])).toBeUndefined()
  })

  it('is dropped after a new deploy or when old', () => {
    const a = client()
    a.setQueryData(['status'], { data_version: 'v2' })
    save(a, 'build1', 0)
    const b = client()
    restore(b, 'build2', 0)
    expect(b.getQueryData(['status'])).toBeUndefined()
    save(a, 'build1', 0)
    restore(b, 'build1', 7 * 3_600_000)
    expect(b.getQueryData(['status'])).toBeUndefined()
  })

  it('copes with storage that is broken', () => {
    localStorage.setItem('eb-cache', '{not json')
    expect(() => restore(client(), 'build1')).not.toThrow()
  })
})
