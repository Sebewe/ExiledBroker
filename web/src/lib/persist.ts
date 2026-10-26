import { dehydrate, hydrate, type QueryClient } from '@tanstack/react-query'

// The query cache, saved in this browser between visits: a reload, or coming back
// later, shows what was loaded without asking the server, until the status check says a
// new hour is due (lib/schedule). Only the current data version is kept (and the
// preview's current snapshot), so it stays small. Storage can be missing or full
// (private windows, quotas): then it's skipped.

const KEY = 'eb-cache'
const MAX_AGE = 6 * 3_600_000 // older than this, start fresh

interface Saved {
  build: string
  savedAt: number
  state: ReturnType<typeof dehydrate>
}

function status(client: QueryClient) {
  return client.getQueryData(['status']) as { data_version?: string | null; preview?: { version: string } | null } | undefined
}

function version(client: QueryClient): string | undefined {
  return status(client)?.data_version ?? undefined
}

export function restore(client: QueryClient, build: string, now = Date.now()) {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return
    const saved = JSON.parse(raw) as Saved
    // A new deploy may change what the API sends: don't reuse an old build's cache.
    if (saved.build !== build || now - saved.savedAt > MAX_AGE) {
      localStorage.removeItem(KEY)
      return
    }
    hydrate(client, saved.state)
  } catch {
    // unreadable or blocked storage: start fresh
  }
}

export function save(client: QueryClient, build: string, now = Date.now()) {
  const current = version(client)
  const preview = status(client)?.preview?.version // the preview's documents: its snapshot's
  const last = (key: readonly unknown[]) => key[key.length - 1]
  const state = dehydrate(client, {
    shouldDehydrateQuery: (q) =>
      q.state.status === 'success' &&
      (q.queryKey[0] === 'status' || (q.queryKey[0] === 'preview' ? !!preview && last(q.queryKey) === preview : last(q.queryKey) === (current ?? 'none'))),
  })
  try {
    localStorage.setItem(KEY, JSON.stringify({ build, savedAt: now, state } satisfies Saved))
  } catch {
    // full or blocked: the in-memory cache still works for this visit
  }
}

/** Save shortly after each successful fetch. Returns the unsubscribe function. */
export function persist(client: QueryClient, build: string, delay = 1000) {
  let timer: ReturnType<typeof setTimeout> | undefined
  return client.getQueryCache().subscribe((event) => {
    if (event.type !== 'updated' || event.action.type !== 'success') return
    clearTimeout(timer)
    timer = setTimeout(() => save(client, build), delay)
  })
}
