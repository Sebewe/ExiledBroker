import { useQuery } from '@tanstack/react-query'
import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { api, ApiError, unwrap, type AdminOverview, type PipelineLeague, type UsageEvent, type UsageStats } from '../api/client'
import { Notice } from '../components/Notice'
import { Skeleton } from '../components/QueryState'
import { PageHeader, Section } from '../components/Section'
import { Stat } from '../components/Stat'
import { count, duration, utcHour } from '../lib/format'

// The owner's page (docs/admin.md): not linked anywhere, and empty without the token
// (EB_ADMIN_TOKEN on the server). The token is kept for this tab only (sessionStorage),
// and nothing here is saved with the site's query cache (lib/persist keeps only the
// status and the current data version's tables). Plain tables, no charts, so the
// page's chunk stays a few kB.

const KEY = 'eb-admin-token'
const REFRESH = 5 * 60_000
const LATE = 2 * 3_600_000 // no successful update for this long: the feed is behind

function readToken(): string {
  try {
    return sessionStorage.getItem(KEY) ?? ''
  } catch {
    return ''
  }
}

function writeToken(token: string) {
  try {
    if (token) sessionStorage.setItem(KEY, token)
    else sessionStorage.removeItem(KEY)
  } catch {
    // blocked storage: the token lasts until the page is left
  }
}

const bearer = (token: string) => ({ headers: { Authorization: `Bearer ${token}` } })
// Gone from memory as soon as the page is left.
const ADMIN_QUERY = { retry: false, refetchInterval: REFRESH, gcTime: 0 } as const

function useOverview(token: string) {
  return useQuery({
    queryKey: ['admin', 'overview', token],
    queryFn: () => unwrap(api.GET('/api/admin/overview', bearer(token))),
    enabled: !!token,
    ...ADMIN_QUERY,
  })
}

function useUsage(token: string, enabled: boolean) {
  return useQuery({
    queryKey: ['admin', 'usage', token],
    queryFn: () => unwrap(api.GET('/api/stats', bearer(token))),
    enabled: !!token && enabled,
    ...ADMIN_QUERY,
  })
}

/** Search engines skip this page. */
function useNoIndex() {
  useEffect(() => {
    const meta = document.createElement('meta')
    meta.name = 'robots'
    meta.content = 'noindex'
    document.head.appendChild(meta)
    return () => meta.remove()
  }, [])
}

const statusOf = (e: unknown) => (e instanceof ApiError ? e.status : undefined)

export default function Admin() {
  useNoIndex()
  const [token, setToken] = useState(readToken)
  const overview = useOverview(token)
  // The overview checks the token first; the counts are asked for once it's accepted.
  const usage = useUsage(token, overview.isSuccess)
  const refused = statusOf(overview.error) === 401
  const off = statusOf(overview.error) === 404

  const signOut = () => {
    writeToken('')
    setToken('')
  }

  if (!token || refused) {
    return (
      <div className="flex flex-col gap-6">
        <PageHeader title="Admin" />
        {refused && (
          <Notice kind="warning" title="That token wasn't accepted.">
            Check it and try again.
          </Notice>
        )}
        <TokenForm
          onSubmit={(t) => {
            writeToken(t)
            setToken(t)
          }}
        />
      </div>
    )
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-start justify-between gap-4">
        <PageHeader title="Admin">The site's usage and the pipeline's health. Refreshed every 5 minutes.</PageHeader>
        <button type="button" onClick={signOut} className="shrink-0 rounded-md border border-border px-3 py-1.5 text-sm text-muted hover:text-text">
          Sign out
        </button>
      </div>
      {off ? (
        <Notice kind="info" title="The admin page is switched off.">
          Set EB_ADMIN_TOKEN on the server to use it.
        </Notice>
      ) : overview.isPending ? (
        <Skeleton rows={4} />
      ) : overview.error ? (
        <Notice kind="warning" title="Couldn't load the overview.">
          {overview.error.message}
        </Notice>
      ) : (
        <>
          <Section title="Usage" description="Cookie-free counts: no id is kept, so returning visitors are counted within a month only.">
            {usage.isPending ? (
              <Skeleton rows={3} />
            ) : usage.error ? (
              <Notice kind={statusOf(usage.error) === 404 ? 'info' : 'warning'} title="Usage counts aren't available.">
                {statusOf(usage.error) === 404 ? 'Counting is switched off on the server (EB_USAGE).' : usage.error.message}
              </Notice>
            ) : (
              <Usage data={usage.data} />
            )}
          </Section>
          <Pipeline data={overview.data} />
        </>
      )}
    </div>
  )
}

function TokenForm({ onSubmit }: { onSubmit: (token: string) => void }) {
  const [value, setValue] = useState('')
  const submit = (e: FormEvent) => {
    e.preventDefault()
    if (value.trim()) onSubmit(value.trim())
  }
  return (
    <form onSubmit={submit} className="flex max-w-md flex-col gap-3">
      <label className="flex flex-col gap-1.5 text-sm">
        <span className="text-muted">Admin token</span>
        <input
          type="password"
          autoComplete="current-password"
          value={value}
          onChange={(e) => setValue(e.target.value)}
          className="rounded-md border border-border bg-surface px-3 py-2 text-text"
        />
      </label>
      <button type="submit" className="self-start rounded-md border border-accent/60 bg-accent/15 px-4 py-2 text-sm font-medium text-accent-strong">
        Open
      </button>
    </form>
  )
}

// --- Usage ---------------------------------------------------------------------------

const TD = 'num px-3 py-1.5 text-right'

function Usage({ data }: { data: UsageStats }) {
  const current = data.periods.at(-1)
  const pages = data.events.filter((e) => e.event.startsWith('page:'))
  const features = data.events.filter((e) => e.event.startsWith('feature:'))
  return (
    <div className="flex flex-col gap-6">
      {!data.stored && (
        <Notice kind="info" title="Counts aren't being stored.">
          There's no database for them: these are this server process's counts since it started.
        </Notice>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Visitors this month" value={count(current?.visitors)} hint={current?.period} />
        <Stat label="Returning this month" value={count(current?.returning)} hint="Seen on two or more days of the month" />
        <Stat label="Page views, all time" value={count(data.total.views)} hint={data.total.since ? `Since ${data.total.since}` : undefined} />
        <Stat label="Visitor-days, all time" value={count(data.total.visitor_days)} hint="Each visitor counted once a day" />
      </div>
      <div className="grid gap-6 lg:grid-cols-2">
        <Table title="Months" head={['Month', 'Visitors', 'Returning']} empty="Nothing counted yet." rows={data.periods.length}>
          {[...data.periods].reverse().map((p) => (
            <tr key={p.period} className="border-t border-border">
              <td className="px-3 py-1.5">
                {p.period}
                {!p.finished && <span className="text-muted"> (so far)</span>}
              </td>
              <td className={TD}>{count(p.visitors)}</td>
              <td className={TD}>{count(p.returning)}</td>
            </tr>
          ))}
        </Table>
        <Table title="Last 30 days" head={['Day', 'Visitors', 'Views']} empty="No days stored yet." rows={data.days.length}>
          {[...data.days].reverse().map((d) => (
            <tr key={d.day} className="border-t border-border">
              <td className="px-3 py-1.5">{d.day}</td>
              <td className={TD}>{count(d.visitors)}</td>
              <td className={TD}>{count(d.views)}</td>
            </tr>
          ))}
        </Table>
        <EventTable title="Pages" events={pages} prefix="page:" />
        <EventTable title="Features" events={features} prefix="feature:" />
      </div>
    </div>
  )
}

function Table({ title, head, empty, rows, children }: { title: string; head: string[]; empty: string; rows: number; children: ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-2">
      <h3 className="font-semibold">{title}</h3>
      {rows === 0 ? (
        <p className="text-sm text-muted">{empty}</p>
      ) : (
        <div className="max-h-96 overflow-auto rounded-lg border border-border">
          <table className="w-full text-sm">
            <thead className="sticky top-0 bg-surface">
              <tr>
                {head.map((h, i) => (
                  <th key={h} className={`px-3 py-2 font-medium text-muted ${i ? 'text-right' : 'text-left'}`}>
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>{children}</tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function EventTable({ title, events, prefix }: { title: string; events: UsageEvent[]; prefix: string }) {
  return (
    <Table title={title} head={['Name', 'Views (30 d)', 'Visitors (30 d)', 'Views (all)']} empty="None used yet." rows={events.length}>
      {events.map((e) => (
        <tr key={e.event} className="border-t border-border">
          <td className="max-w-48 truncate px-3 py-1.5" title={e.event}>
            {e.event.slice(prefix.length)}
          </td>
          <td className={TD}>{count(e.views_recent)}</td>
          <td className={TD}>{count(e.visitors_recent)}</td>
          <td className={TD}>{count(e.views)}</td>
        </tr>
      ))}
    </Table>
  )
}

// --- Pipeline ------------------------------------------------------------------------

function Pipeline({ data }: { data: AdminOverview }) {
  const now = new Date(data.now).getTime()
  const loaded = data.data_version ? `${data.data_version.replace('T', ' ').slice(0, 16)} UTC` : 'nothing loaded yet'
  return (
    <Section title="Pipeline" description={`Each league's hourly update over the past day. Last load: ${loaded}.`}>
      {data.pipeline.length === 0 ? (
        <Notice kind="waiting" title="No updates recorded yet.">
          The pipeline writes a row here each time it runs.
        </Notice>
      ) : (
        data.pipeline.map((league) => <PipelineCard key={league.league} league={league} now={now} />)
      )}
    </Section>
  )
}

function PipelineCard({ league, now }: { league: PipelineLeague; now: number }) {
  const sinceSuccess = league.last_success ? now - new Date(league.last_success).getTime() : null
  const late = sinceSuccess === null || sinceSuccess > LATE
  return (
    <div className="flex flex-col gap-3">
      <h3 className="font-semibold">{league.league}</h3>
      {league.last_state === 'failed' && (
        <Notice kind="warning" title={`The latest update failed (${utcHour(league.last_run)}).`}>
          <span className="break-words font-mono text-xs">{league.last_error ?? 'No error recorded.'}</span>
        </Notice>
      )}
      {late && league.last_state !== 'failed' && (
        <Notice kind="warning" title="No successful update in over 2 hours.">
          The last one was {league.last_success ? utcHour(league.last_success) : 'never'}.
        </Notice>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat label="Last success" value={sinceSuccess === null ? '–' : `${duration(sinceSuccess)} ago`} hint={utcHour(league.last_success)} />
        <Stat label="Latest hour loaded" value={utcHour(league.latest_hour).replace(' UTC', '')} hint="UTC" />
        <Stat label="Runs / failed (day)" value={`${count(league.runs_day)} / ${count(league.failures_day)}`} />
        <Stat label="Median run (day)" value={league.median_seconds_day === null ? '–' : `${count(league.median_seconds_day, 1)} s`} />
        <Stat label="Requests (day)" value={count(league.requests_day)} />
        <Stat label="Downloaded (day)" value={`${count(league.bytes_day / 1e6, 1)} MB`} />
        <Stat label="Hours added (day)" value={count(league.hours_added_day)} />
        <Stat label="Last state" value={league.last_state} hint={utcHour(league.last_run)} />
      </div>
    </div>
  )
}
