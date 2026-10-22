import { useCallback } from 'react'
import { useSearchParams } from 'react-router'

/** A control's value kept in the URL, so every view can be linked and survives reloads.
 *  The default isn't written to the URL. Pass the type for a set of choices:
 *  `useParam<'chaos' | 'divine'>('unit', 'chaos')`. */
export function useParam<T extends string>(name: string, fallback: T) {
  const [params, setParams] = useSearchParams()
  const value = (params.get(name) ?? fallback) as T
  const set = useCallback(
    (next: T) =>
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev)
          if (next === fallback) p.delete(name)
          else p.set(name, next)
          return p
        },
        { replace: true },
      ),
    [name, fallback, setParams],
  )
  return [value, set] as const
}

/** A numeric control kept in the URL; anything unparsable reads as the default. */
export function useNumberParam(name: string, fallback: number) {
  const [raw, setRaw] = useParam<string>(name, String(fallback))
  const parsed = Number(raw)
  const value = Number.isFinite(parsed) ? parsed : fallback
  const set = useCallback((next: number) => setRaw(String(next)), [setRaw])
  return [value, set] as const
}

/** A multi-value control (repeated URL parameter). */
export function useListParam(name: string, fallback: string[]) {
  const [params, setParams] = useSearchParams()
  const raw = params.getAll(name)
  const value = raw.length ? raw : fallback
  const set = useCallback(
    (next: string[]) =>
      setParams(
        (prev) => {
          const p = new URLSearchParams(prev)
          p.delete(name)
          if (next.join() !== fallback.join()) next.forEach((v) => p.append(name, v))
          return p
        },
        { replace: true },
      ),
    [name, fallback, setParams],
  )
  return [value, set] as const
}
