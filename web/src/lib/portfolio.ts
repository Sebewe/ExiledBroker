import { useSyncExternalStore } from 'react'
import type { PreviewItemNext } from '../api/client'
import { HOUR } from './chartOptions'
import { typicalAt } from './revealItem'

// The preview's paper portfolio (docs/preview.md): Divines staked on a few items as the
// league stood at the end of the chosen day, valued hour by hour from the snapshot's price
// paths (`next/price-check/{item}`) as the visitor steps the clock forward. Nothing is
// traded or sent anywhere: the stakes live in this browser only (localStorage, and in
// memory where storage is blocked), so the feature costs the server nothing.

const KEY = 'eb-portfolio'
export const MAX_POSITIONS = 8
export const DEFAULT_STAKE = 10 // Divines
export const MAX_STAKE = 100_000
/** The yardstick: values are in Divines, so a Divine Orb stake would never move. */
export const DIVINE = 'currency:divine-orb'

export type Position = { item_id: string; name: string; stake: number }
/** `at`: hours past the end of `day` the clock has been stepped to. */
export type PortfolioState = { positions: Position[]; day: number; at: number }

const EMPTY: PortfolioState = { positions: [], day: 0, at: 0 }

const validStake = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x) && x > 0 && x <= MAX_STAKE

/** The stored portfolio, or an empty one for anything unreadable. */
export function parse(raw: string | null): PortfolioState {
  try {
    const v = JSON.parse(raw ?? 'null') as Partial<PortfolioState> | null
    if (!v || !Array.isArray(v.positions)) return EMPTY
    const seen = new Set<string>()
    const positions = v.positions
      .filter((p): p is Position => !!p && typeof p.item_id === 'string' && typeof p.name === 'string' && validStake(p.stake) && p.item_id !== DIVINE)
      .filter((p) => !seen.has(p.item_id) && !!seen.add(p.item_id))
      .slice(0, MAX_POSITIONS)
      .map(({ item_id, name, stake }) => ({ item_id, name, stake }))
    const day = Number.isInteger(v.day) ? v.day! : 0
    const at = Number.isInteger(v.at) && v.at! >= 0 ? v.at! : 0
    return { positions, day, at }
  } catch {
    return EMPTY
  }
}

function read(): PortfolioState {
  try {
    return parse(localStorage.getItem(KEY))
  } catch {
    return EMPTY
  }
}

let state = read()
const listeners = new Set<() => void>()

function set(next: PortfolioState) {
  state = next
  try {
    localStorage.setItem(KEY, JSON.stringify(next))
  } catch {
    // blocked storage: it lasts this visit
  }
  for (const l of listeners) l()
}

function subscribe(listener: () => void) {
  listeners.add(listener)
  // Another tab changed it: follow.
  const onStorage = (e: StorageEvent) => {
    if (e.key !== KEY) return
    state = read()
    listener()
  }
  globalThis.addEventListener?.('storage', onStorage)
  return () => {
    listeners.delete(listener)
    globalThis.removeEventListener?.('storage', onStorage)
  }
}

export function usePortfolio(): PortfolioState {
  return useSyncExternalStore(subscribe, () => state)
}

export const portfolio = {
  /** Stake an item (a no-op if it's already in, the portfolio is full, or it's the Divine Orb). */
  add(item: { item_id: string; name: string }, stake = DEFAULT_STAKE): boolean {
    if (item.item_id === DIVINE || state.positions.length >= MAX_POSITIONS) return false
    if (state.positions.some((p) => p.item_id === item.item_id)) return false
    set({ ...state, positions: [...state.positions, { item_id: item.item_id, name: item.name, stake }] })
    return true
  },
  remove(itemId: string) {
    set({ ...state, positions: state.positions.filter((p) => p.item_id !== itemId) })
  },
  setStake(itemId: string, stake: number) {
    if (!validStake(stake)) return
    set({ ...state, positions: state.positions.map((p) => (p.item_id === itemId ? { ...p, stake } : p)) })
  },
  /** Step the clock: `at` hours past the end of `day`. */
  setAt(day: number, at: number) {
    set({ ...state, day, at: Math.max(0, Math.round(at)) })
  },
  clear() {
    set(EMPTY)
  },
  /** Read storage again (tests). */
  reload() {
    state = read()
    for (const l of listeners) l()
  },
}

/** The clock's position for `day`: a portfolio stepped on another day starts again. */
export const atFor = (s: PortfolioState, day: number, hours: number) => (s.day === day ? Math.min(s.at, Math.max(0, hours - 1)) : 0)

/** Every hour from the chosen day's last (`from`) to the snapshot's end, ISO, UTC. */
export function hoursFrom(from: string, until: string): string[] {
  const start = Date.parse(from)
  const end = Date.parse(until)
  if (!Number.isFinite(start) || !Number.isFinite(end)) return []
  const out: string[] = []
  for (let t = start; t <= end; t += HOUR) out.push(new Date(t).toISOString())
  return out
}

/** The typical price at each hour, carried forward through hours it didn't trade. */
export function pricePath(next: PreviewItemNext, hours: string[]): (number | null)[] {
  let last: number | null = null
  return hours.map((h) => {
    const p = typicalAt(next, Date.parse(h))
    if (p != null && p > 0) last = p
    return last
  })
}

export type Valued = {
  item_id: string
  /** The price (Divines each) the stake bought at, the end of the chosen day; null: it
   *  hadn't traded then, so nothing was bought. */
  entry: number | null
  /** What the stake is worth at each hour, in Divines. */
  worth: (number | null)[]
}

/** One stake's worth hour by hour: units bought at the day's typical price, at each
 *  later hour's. */
export function valueStake(next: PreviewItemNext, stake: number, hours: string[]): Valued {
  const path = pricePath(next, hours)
  const entry = path[0] ?? null
  return { item_id: next.item_id, entry, worth: path.map((p) => (entry && p != null ? (stake / entry) * p : null)) }
}

/** The same Divines kept as Chaos instead: bought at the day's Divine price, worth less
 *  in Divines as the Divine rises. From the Divine Orb's path (priced in Chaos). */
export function keptAsChaos(divine: PreviewItemNext, stake: number, hours: string[]): (number | null)[] {
  const path = pricePath(divine, hours)
  const entry = path[0] ?? null
  return path.map((p) => (entry && p ? (stake * entry) / p : null))
}
