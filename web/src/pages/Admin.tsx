import { useQuery } from "@tanstack/react-query";
import { useEffect, useState, type FormEvent } from "react";
import {
  api,
  ApiError,
  unwrap,
  type AdminOverview,
  type PipelineLeague,
} from "../api/client";
import { Notice } from "../components/Notice";
import { Skeleton } from "../components/QueryState";
import { PageHeader, Section } from "../components/Section";
import { Stat } from "../components/Stat";
import { count, duration, utcHour } from "../lib/format";

// The owner's page (docs/admin.md): not linked anywhere, and empty without the token
// (EB_ADMIN_TOKEN on the server). The token is kept for this tab only (sessionStorage),
// and the overview is never saved with the site's query cache (lib/persist keeps only
// the status and the current data version's tables).

const KEY = "eb-admin-token";
const REFRESH = 5 * 60_000;
const LATE = 2 * 3_600_000; // no successful update for this long: the feed is behind

function readToken(): string {
  try {
    return sessionStorage.getItem(KEY) ?? "";
  } catch {
    return "";
  }
}

function writeToken(token: string) {
  try {
    if (token) sessionStorage.setItem(KEY, token);
    else sessionStorage.removeItem(KEY);
  } catch {
    // blocked storage: the token lasts until the page is left
  }
}

function useOverview(token: string) {
  return useQuery({
    queryKey: ["admin", "overview", token],
    queryFn: () =>
      unwrap(
        api.GET("/api/admin/overview", {
          headers: { Authorization: `Bearer ${token}` },
        }),
      ),
    enabled: !!token,
    retry: false,
    refetchInterval: REFRESH,
    gcTime: 0, // gone from memory as soon as the page is left
  });
}

/** Search engines skip this page. */
function useNoIndex() {
  useEffect(() => {
    const meta = document.createElement("meta");
    meta.name = "robots";
    meta.content = "noindex";
    document.head.appendChild(meta);
    return () => meta.remove();
  }, []);
}

export default function Admin() {
  useNoIndex();
  const [token, setToken] = useState(readToken);
  const overview = useOverview(token);
  const refused =
    overview.error instanceof ApiError && overview.error.status === 401;
  const off =
    overview.error instanceof ApiError && overview.error.status === 404;

  const signOut = () => {
    writeToken("");
    setToken("");
  };

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
            writeToken(t);
            setToken(t);
          }}
        />
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-8">
      <div className="flex items-start justify-between gap-4">
        <PageHeader title="Admin">
          The site's usage and the pipeline's health. Refreshed every 5 minutes.
        </PageHeader>
        <button
          type="button"
          onClick={signOut}
          className="shrink-0 rounded-md border border-border px-3 py-1.5 text-sm text-muted hover:text-text"
        >
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
        <Pipeline data={overview.data} />
      )}
    </div>
  );
}

function TokenForm({ onSubmit }: { onSubmit: (token: string) => void }) {
  const [value, setValue] = useState("");
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (value.trim()) onSubmit(value.trim());
  };
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
      <button
        type="submit"
        className="self-start rounded-md bg-accent px-4 py-2 text-sm font-medium text-bg"
      >
        Open
      </button>
    </form>
  );
}

function Pipeline({ data }: { data: AdminOverview }) {
  const now = new Date(data.now).getTime();
  return (
    <Section
      title="Pipeline"
      description={`Each league's hourly update over the past day. Last load: ${data.data_version ? `${data.data_version.replace("T", " ").slice(0, 16)} UTC` : "nothing loaded yet"}.`}
    >
      {data.pipeline.length === 0 ? (
        <Notice kind="waiting" title="No updates recorded yet.">
          The pipeline writes a row here each time it runs.
        </Notice>
      ) : (
        data.pipeline.map((league) => (
          <PipelineCard key={league.league} league={league} now={now} />
        ))
      )}
    </Section>
  );
}

function PipelineCard({
  league,
  now,
}: {
  league: PipelineLeague;
  now: number;
}) {
  const sinceSuccess = league.last_success
    ? now - new Date(league.last_success).getTime()
    : null;
  const late = sinceSuccess === null || sinceSuccess > LATE;
  return (
    <div className="flex flex-col gap-3">
      <h3 className="font-semibold">{league.league}</h3>
      {league.last_state === "failed" && (
        <Notice
          kind="warning"
          title={`The latest update failed (${utcHour(league.last_run)}).`}
        >
          <span className="break-words font-mono text-xs">
            {league.last_error ?? "No error recorded."}
          </span>
        </Notice>
      )}
      {late && league.last_state !== "failed" && (
        <Notice kind="warning" title="No successful update in over 2 hours.">
          The last one was{" "}
          {league.last_success ? utcHour(league.last_success) : "never"}.
        </Notice>
      )}
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        <Stat
          label="Last success"
          value={sinceSuccess === null ? "–" : `${duration(sinceSuccess)} ago`}
          hint={utcHour(league.last_success)}
        />
        <Stat
          label="Latest hour loaded"
          value={utcHour(league.latest_hour).replace(" UTC", "")}
          hint="UTC"
        />
        <Stat
          label="Runs / failed (day)"
          value={`${count(league.runs_day)} / ${count(league.failures_day)}`}
        />
        <Stat
          label="Median run (day)"
          value={
            league.median_seconds_day === null
              ? "–"
              : `${count(league.median_seconds_day, 1)} s`
          }
        />
        <Stat label="Requests (day)" value={count(league.requests_day)} />
        <Stat
          label="Downloaded (day)"
          value={`${count(league.bytes_day / 1e6, 1)} MB`}
        />
        <Stat label="Hours added (day)" value={count(league.hours_added_day)} />
        <Stat
          label="Last state"
          value={league.last_state}
          hint={utcHour(league.last_run)}
        />
      </div>
    </div>
  );
}
