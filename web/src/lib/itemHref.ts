import { useCallback } from 'react'
import { usePriceCheck } from '../api/queries'

// Item names elsewhere on the site link to the item on Price check, when Price check
// prices it (components/ItemLink). The search list is the same cached response Price
// check reads, so a visitor fetches it at most once an hour whichever page they start on.

/** Where an item's Price check is, or undefined when Price check doesn't price it (yet). */
export function useItemHref(league: string | undefined) {
  const index = usePriceCheck(league)
  const items = index.data?.items
  return useCallback(
    (itemId: string) => {
      if (!league || !items?.some((x) => x.item_id === itemId)) return undefined
      return `/price-check?${new URLSearchParams({ league, item: itemId })}`
    },
    [league, items],
  )
}

export type ItemHref = ReturnType<typeof useItemHref>
