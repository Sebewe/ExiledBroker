// Filtering for the type-to-search item picker (components/ItemSearch).

export type SearchOption = { id: string; name: string; group?: string }

/** Options matching every word typed (in the name or the group), names that start with
 *  the text first. Nothing typed keeps the given order. */
export function matchOptions<T extends SearchOption>(options: T[], query: string): T[] {
  const q = query.trim().toLowerCase()
  if (!q) return options
  const words = q.split(/\s+/)
  const hits = options.filter((o) => {
    const text = `${o.name} ${o.group ?? ''}`.toLowerCase()
    return words.every((w) => text.includes(w))
  })
  const starts = (o: T) => (o.name.toLowerCase().startsWith(q) ? 0 : 1)
  return hits.sort((a, b) => starts(a) - starts(b) || a.name.localeCompare(b.name))
}
