import { useCallback } from 'react'
import { useStatus } from '../api/queries'
import { ApiError, type LiveLeague, type PreviewManifest } from '../api/client'
import { useParam } from './useParam'

// The pre-launch preview (docs/preview.md): the site rewound to a past league's early
// days. /api/status says whether it's on and carries its manifest; it turns itself off
// once the announced league's first trades load, so a page reload is all launch takes.
// While it's on, the data hooks (api/queries.ts) read the snapshot for the chosen day
// from /api/preview/{key} instead of the live tables.

export interface Preview {
  /** The preview is on: the pages show `league` on `day`, not the live leagues. */
  on: boolean
  /** The chosen launch day (URL `day`, else the manifest's default); 0 when off. */
  day: number
  days: number[]
  setDay: (day: number) => void
  /** The snapshot's league as /api/status listed it at the end of `day`. */
  league: LiveLeague | undefined
  /** The day's last loaded hour (ISO, UTC). */
  hour: string | undefined
  /** The snapshot's version: sent as `v`, and keys the preview's queries. */
  version: string | undefined
  manifest: PreviewManifest | undefined
}

/** The day to show: the URL's, if the snapshot has it, else its default. */
export function chooseDay(manifest: PreviewManifest | null | undefined, wanted: string): number {
  if (!manifest) return 0
  const n = Number(wanted)
  return manifest.days.some((d) => d.day === n) ? n : manifest.default_day
}

export function usePreview(): Preview {
  const manifest = useStatus().data?.preview ?? undefined
  const [wanted, setWanted] = useParam<string>('day', String(manifest?.default_day ?? ''))
  const day = chooseDay(manifest, wanted)
  const setDay = useCallback((next: number) => setWanted(String(next)), [setWanted])
  const league = manifest?.days.find((d) => d.day === day)?.league
  return {
    on: !!manifest,
    day,
    days: manifest?.days.map((d) => d.day) ?? [],
    setDay,
    league,
    hour: league?.latest_hour ?? undefined,
    version: manifest?.version,
    manifest,
  }
}

/** The snapshot's keys (src/exiledbroker/preview/snapshot.py). */
export const previewKey = {
  missed: (day: number) => `d${day}/missed`,
  priceCheck: (day: number) => `d${day}/price-check`,
  priceCheckItem: (day: number, itemId: string) => `d${day}/price-check/${itemId}`,
  launchPicks: (day: number) => `d${day}/launch-picks`,
  game: (n: number) => `game/${n}`,
  itemNext: (itemId: string) => `next/price-check/${itemId}`,
}

/** One of the snapshot's documents. Typed by the caller: the route serves every kind. */
export async function fetchPreview<T>(key: string, version: string | undefined): Promise<T> {
  const path = encodeURI(key) // keys are path-safe (letters, digits, `:._-/`)
  const query = version ? `?v=${encodeURIComponent(version)}` : ''
  const response = await globalThis.fetch(`${globalThis.location?.origin ?? ''}/api/preview/${path}${query}`)
  if (!response.ok) {
    let detail = response.statusText
    try {
      const body = (await response.json()) as { detail?: unknown }
      if (body.detail !== undefined) detail = String(body.detail)
    } catch {
      // not JSON: keep the status text
    }
    throw new ApiError(response.status, detail)
  }
  return (await response.json()) as T
}
