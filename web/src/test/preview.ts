import sample from './preview_sample.json'
import type { PreviewManifest, Status } from '../api/client'

// The sample pre-launch preview snapshot (preview_sample.json here, made by tests/fixtures/
// make_preview_sample.py from the Mirage replay): every key kind, days 1–3 (default 2),
// a few Price check items. For the preview's page tests: serve `previewRoutes()` with the
// stubbed fetch, and `previewStatus()` as /api/status.

/** The snapshot's documents by key (`manifest`, `d2/missed`, `next/price-check/…`). */
export const PREVIEW_DOCS = sample as unknown as Record<string, unknown>
export const PREVIEW_MANIFEST = PREVIEW_DOCS.manifest as PreviewManifest

/** Every document at its URL path (`/api/preview/d2/missed`), for a `serve` helper. */
export function previewRoutes(): Record<string, { body: unknown }> {
  return Object.fromEntries(Object.entries(PREVIEW_DOCS).map(([key, body]) => [`/api/preview/${key}`, { body }]))
}

/** /api/status while the preview is on: the next league announced by its day only. */
export function previewStatus(over: Partial<Status> = {}): Status {
  return {
    now: '2026-11-01T12:00:00Z',
    data_version: 'v1',
    leagues: [],
    upcoming: { name: null, start_date: '2026-11-13', time_known: false, start_at: null, first_data_at: null },
    preview: PREVIEW_MANIFEST,
    ...over,
  }
}
