import { isNoData } from '../api/client'
import { Notice } from '../components/Notice'
import { Skeleton } from '../components/QueryState'

/** What to show instead of a query's content: a placeholder while loading, an explanation
 *  for no data yet (the API's 503), or the error. Null when the data is ready. */
export function queryFallback(q: { isPending: boolean; error: unknown }, rows = 6) {
  if (q.error) {
    return isNoData(q.error) ? (
      <Notice kind="waiting" title="No data yet">
        Nothing has been loaded yet. Data appears once the live feed has loaded the league's first published hour.
      </Notice>
    ) : (
      <Notice kind="warning" title="Couldn't load this">
        {q.error instanceof Error ? q.error.message : 'The server returned an error.'} Try again in a moment.
      </Notice>
    )
  }
  if (q.isPending) return <Skeleton rows={rows} />
  return null
}
