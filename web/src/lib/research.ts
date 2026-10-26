// The Research section's pages (/research/*): the proof and the notes behind the tools, in
// the order of its menu. The Journal is lit on its notes too (/research/notes/<n>).
export const RESEARCH = [
  { to: '/research', label: 'Journal' },
  { to: '/research/method', label: 'How the tools work' },
  { to: '/research/backtest', label: 'Backtest' },
  { to: '/research/conversions', label: 'Multi-layered conversions' },
  { to: '/research/about', label: 'About' },
] as const

/** A journal note's address. */
export const noteHref = (n: number) => `/research/notes/${n}`
