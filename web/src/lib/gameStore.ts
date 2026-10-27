import { useSyncExternalStore } from 'react'

// The preview's trading game (docs/preview.md, lib/game.ts): its state, kept in this
// browser only (localStorage, and in memory where storage is blocked). No accounts,
// nothing sent. This part is small and loaded with the recap, which reads the game's
// hour from it; the rules that change it are in lib/game.ts, loaded with the game.

const KEY = 'eb-game'
export const START_CASH = 10 // Divines

/** A loop or a card turn-in: the recap's own order that hour, its outcome read from the
 *  snapshot when placed (and shown only once the clock passes it). */
export type OrderTrade = {
  id: string
  kind: 'loop' | 'card'
  item_id: string
  name: string
  direction?: string | null
  /** The game hour it was placed in (hours since launch). */
  at: number
  /** Divines tied up: the purchases bought while the order waits, what filled once it has. */
  stake: number
  /** The game's Divine price in Chaos: the trade's Chaos are converted at it. */
  rate: number
  /** Chaos one purchase costs (the smallest whole trade at the order's bid), and how many. */
  lot: number
  lots: number
  filled: boolean | null
  spent: number | null
  pnl: number | null
  /** The game hour it sells in; null: not known by the snapshot's end. */
  settle: number | null
  state: 'placed' | 'filled'
}

/** A flip: a bid, then items held and listed until they sell or are quick-sold. */
export type FlipTrade = {
  id: string
  kind: 'flip'
  item_id: string
  name: string
  at: number
  /** Divines put in: the stake while bidding, the items' cost once bought. */
  stake: number
  rate: number
  /** Items one purchase buys, its Chaos (the recap's whole bid), and how many were bid for. */
  lot: number
  lotCost: number
  lots: number
  /** Chaos an item: the recap's bid and first ask, and its hourly cut. */
  bid: number
  ask: number
  cut: number
  /** Items bought, and still held. */
  units: number
  left: number
  /** Divines the sales brought in so far. */
  got: number
  /** The listing, Chaos an item: null follows the recap's (its ask, cut each hour). */
  listing: number | null
  /** The last known average price (Chaos an item), to value what's held. */
  mark: number
  state: 'bidding' | 'holding'
}

export type Trade = OrderTrade | FlipTrade

/** A finished trade, for the history. */
export type Done = {
  id: string
  kind: Trade['kind']
  item_id: string
  name: string
  direction?: string | null
  at: number
  closed: number
  /** Divines in, and out. Equal when nothing filled. */
  cost: number
  back: number
  outcome: 'sold' | 'quick-sold' | 'unfilled'
}

export type GameState = {
  /** The stored format: an older game starts over. */
  v: 2
  /** The snapshot's league: a game of another league starts over. */
  league: string
  /** The game hour the clock is at (hours since launch); 0: no game yet. */
  n: number
  /** Where it started, for the history. */
  start: number
  /** The Divine's price in Chaos, fixed for the game at its first trade (0: none yet):
   *  every Chaos amount converts at it, so the total moves only with the trades. */
  rate: number
  cash: number
  open: Trade[]
  done: Done[]
}

export const EMPTY: GameState = { v: 2, league: '', n: 0, start: 0, rate: 0, cash: START_CASH, open: [], done: [] }

const finite = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x)

/** The stored game, or a fresh one for anything unreadable. */
export function parse(raw: string | null): GameState {
  try {
    const v = JSON.parse(raw ?? 'null') as Partial<GameState> | null
    if (!v || v.v !== 2 || typeof v.league !== 'string' || !finite(v.n) || !finite(v.cash) || !Array.isArray(v.open) || !Array.isArray(v.done)) return EMPTY
    const ok = (t: unknown) => !!t && typeof t === 'object' && typeof (t as Trade).id === 'string' && finite((t as Trade).stake) && finite((t as Trade).at) && finite((t as Trade).lots)
    // A closed trade has no stake: what went in and came back.
    const closed = (t: unknown) => !!t && typeof t === 'object' && typeof (t as Done).id === 'string' && finite((t as Done).at) && finite((t as Done).cost) && finite((t as Done).back)
    return {
      v: 2,
      league: v.league,
      n: Math.max(0, Math.round(v.n)),
      start: finite(v.start) ? v.start : 0,
      rate: finite(v.rate) && v.rate > 0 ? v.rate : 0,
      cash: v.cash,
      open: v.open.filter(ok) as Trade[],
      done: v.done.filter(closed).slice(-500) as Done[],
    }
  } catch {
    return EMPTY
  }
}

function read(): GameState {
  try {
    return parse(localStorage.getItem(KEY))
  } catch {
    return EMPTY
  }
}

let state = read()
const listeners = new Set<() => void>()

export function setGame(next: GameState) {
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
  // Another tab played: follow.
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

export function useGame(): GameState {
  return useSyncExternalStore(subscribe, () => state)
}

export const getGame = () => state

/** Read storage again (tests). */
export function reloadGame() {
  state = read()
  for (const l of listeners) l()
}

/** The game's hour for `league`, if one is running there (0: none). */
export const gameHour = (s: GameState, league: string | undefined) => (league && s.league === league ? s.n : 0)
