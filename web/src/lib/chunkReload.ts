// After a deploy, an open tab still runs the previous build, whose lazy chunks (the
// other pages, the chart) are gone from the server, which answers 404 for them (api/app.py).
// Opening another page then fails to load its chunk. Reloading picks up the new build, so
// that's what happens, once: a chunk that still fails within a minute (offline, a broken
// deploy) shows the error page (components/PageError) instead of reloading in a loop.

const KEY = 'eb-chunk-reload'
const WINDOW_MS = 60_000

/** True for the errors browsers throw when a dynamic import or its CSS can't be loaded. */
export function isChunkError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error ?? '')
  return /dynamically imported module|Importing a module script failed|Unable to preload CSS|Loading (CSS )?chunk/i.test(message)
}

/** Reload the page for the new build, unless that was already tried in the last minute.
 *  True when it reloads. */
export function reloadForNewBuild(now = Date.now(), reload = () => window.location.reload()): boolean {
  try {
    const last = Number(sessionStorage.getItem(KEY) ?? 0)
    if (now - last < WINDOW_MS) return false
    sessionStorage.setItem(KEY, String(now))
  } catch {
    return false // no storage: can't tell a loop from a first try, so don't reload
  }
  reload()
  return true
}

/** Vite's own signal that a lazy chunk failed to load: reload instead of throwing. */
export function installChunkReload() {
  window.addEventListener('vite:preloadError', (event) => {
    if (reloadForNewBuild()) event.preventDefault()
  })
}
