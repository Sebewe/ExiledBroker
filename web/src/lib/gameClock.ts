import { dayOf, hourAt, isoAt } from './game'
import { gameHour, useGame } from './gameStore'
import { usePreview } from './preview'

// The trading game's clock (lib/game.ts), for its components (Game.tsx, pages/Portfolio).

/** The game as the preview has it: the hour it's at (a new game starts at the chosen
 *  day's end), its first and last hours, and whether one is running. */
export function useGameClock() {
  const preview = usePreview()
  const s = useGame()
  const league = preview.manifest?.league
  const launched = preview.manifest?.launched_at
  const range = preview.manifest?.game
  const running = gameHour(s, league)
  const start = launched && preview.hour ? hourAt(launched, preview.hour) : 0
  const n = running || start
  const playable = !!range && !!league && !!launched && n >= range.first && n <= range.last
  return { s, league, launched, range, running, n, playable, version: preview.version }
}

/** "Day 5, 14:00 UTC" for game hour `n`. */
export const hourLabel = (launched: string | null | undefined, n: number) => (launched ? `Day ${dayOf(n)}, ${isoAt(launched, n).slice(11, 16)} UTC` : `Hour ${n}`)
