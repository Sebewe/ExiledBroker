import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AdminOverview, PipelineLeague } from "../api/client";
import Admin from "./Admin";

const TOKEN = "x".repeat(40);

/** Answers the overview only with the right token, like the server. */
function serve(overview: AdminOverview | { status: number }) {
  const fetch = vi.fn(async (input: Request) => {
    if ("status" in overview)
      return new Response('{"detail":"not found"}', {
        status: overview.status,
      });
    if (input.headers.get("Authorization") !== `Bearer ${TOKEN}`) {
      return new Response('{"detail":"admin token required"}', { status: 401 });
    }
    return new Response(JSON.stringify(overview), {
      headers: { "Content-Type": "application/json" },
    });
  });
  vi.stubGlobal("fetch", fetch);
  return fetch;
}

function renderAdmin() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>
        <Admin />
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const NOW = "2026-10-26T12:00:00Z";
const league = (over: Partial<PipelineLeague> = {}): PipelineLeague => ({
  league: "Mirage",
  last_run: "2026-10-26T11:08:00Z",
  last_success: "2026-10-26T11:08:00Z",
  last_failure: null,
  last_state: "updated",
  last_error: null,
  latest_hour: "2026-10-26T10:00:00Z",
  runs_day: 24,
  failures_day: 0,
  median_seconds_day: 3.2,
  requests_day: 30,
  bytes_day: 12_500_000,
  hours_added_day: 24,
  ...over,
});

function signIn(token = TOKEN) {
  fireEvent.change(screen.getByLabelText("Admin token"), {
    target: { value: token },
  });
  fireEvent.click(screen.getByRole("button", { name: "Open" }));
}

beforeEach(() => sessionStorage.clear());
afterEach(() => vi.unstubAllGlobals());

describe("Admin", () => {
  it("asks for the token and requests nothing without it", () => {
    const fetch = serve({ now: NOW, data_version: null, pipeline: [] });
    renderAdmin();
    expect(screen.getByLabelText("Admin token")).toBeInTheDocument();
    expect(fetch).not.toHaveBeenCalled();
  });

  it("says when the token is refused, and forgets it", async () => {
    serve({ now: NOW, data_version: null, pipeline: [] });
    renderAdmin();
    signIn("wrong");
    expect(
      await screen.findByText("That token wasn't accepted."),
    ).toBeInTheDocument();
  });

  it("shows each league's updates", async () => {
    serve({
      now: NOW,
      data_version: "2026-10-26T11:09:00",
      pipeline: [league()],
    });
    renderAdmin();
    signIn();
    expect(await screen.findByText("Mirage")).toBeInTheDocument();
    expect(screen.getByText("52m ago")).toBeInTheDocument();
    expect(screen.getByText("24 / 0")).toBeInTheDocument();
    expect(screen.getByText("12.5 MB")).toBeInTheDocument();
    expect(sessionStorage.getItem("eb-admin-token")).toBe(TOKEN); // this tab only
  });

  it("warns about a failed or late update", async () => {
    const failed = league({
      last_state: "failed",
      last_error: "ReadTimeout",
      last_failure: "2026-10-26T11:08:00Z",
      last_success: "2026-10-26T10:08:00Z",
    });
    const late = league({
      league: "Keepers",
      last_success: "2026-10-26T06:00:00Z",
    });
    serve({
      now: NOW,
      data_version: "2026-10-26T11:09:00",
      pipeline: [failed, late],
    });
    renderAdmin();
    signIn();
    expect(
      await screen.findByText(/The latest update failed/),
    ).toBeInTheDocument();
    expect(screen.getByText("ReadTimeout")).toBeInTheDocument();
    expect(
      screen.getByText("No successful update in over 2 hours."),
    ).toBeInTheDocument();
  });

  it("handles nothing recorded yet and the page being switched off", async () => {
    serve({ now: NOW, data_version: null, pipeline: [] });
    const { unmount } = renderAdmin();
    signIn();
    expect(
      await screen.findByText("No updates recorded yet."),
    ).toBeInTheDocument();
    unmount();
    serve({ status: 404 });
    renderAdmin(); // the token is still in this tab
    expect(
      await screen.findByText("The admin page is switched off."),
    ).toBeInTheDocument();
  });
});
