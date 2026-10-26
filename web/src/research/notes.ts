import type { Note } from './buildNotes'
import data from './notes.json'

// The journal's notes, newest first (generated from docs/findings.md by `npm run gen:notes`).
// Only the Research pages import this, so it loads with them and never with the Market recap.
export const NOTES = data as Note[]

/** "Backtest: the Launch picks pay; …" → its topic and its takeaway; a title without a
 *  short topic before a colon is all takeaway. */
export function splitTitle(title: string): { topic: string | null; takeaway: string } {
  const i = title.indexOf(': ')
  if (i < 0 || i > 40) return { topic: null, takeaway: title }
  const rest = title.slice(i + 2)
  return { topic: title.slice(0, i), takeaway: rest.charAt(0).toUpperCase() + rest.slice(1) }
}

const DATE = new Intl.DateTimeFormat('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })

/** "26 Oct 2026", from the note's ISO date. */
export const noteDate = (iso: string) => DATE.format(new Date(`${iso}T00:00:00Z`))
