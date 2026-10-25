// The fallback Worker's logic, with everything it touches passed in (fetch, the page,
// the origin), so node:test can run it without Cloudflare. worker.mjs wires it up.
//
// The site's app stamps `X-EB-Origin: app` on every response it sends (api/app.py,
// `MarkOrigin`): its own 503 "no data yet", 404 and 422 included. A response of 400 or
// above WITHOUT the stamp therefore did not come from the app: it is Railway's edge
// (a stopped service, a deploy, the usage limit) and gets replaced. So does a fetch
// that fails or takes longer than `timeoutMs`. Everything else passes through as is.

export const APP_HEADER = "x-eb-origin";
export const FALLBACK_HEADER = "x-eb-fallback";
export const DEFAULT_TIMEOUT_MS = 15_000;
export const RETRY_AFTER_SECONDS = 120;

const API_MESSAGE =
  "The site is having a problem right now. We're investigating. Try again in a few minutes.";

/** True for an error response the app didn't send (Railway's edge, a proxy). */
export function originIsDown(response) {
  return response.status >= 400 && response.headers.get(APP_HEADER) !== "app";
}

/** The request pointed at the Railway origin (same path, query, method, headers, body). */
export function toOrigin(request, origin) {
  if (!origin) return request;
  const url = new URL(request.url);
  const target = new URL(origin);
  target.pathname = url.pathname;
  target.search = url.search;
  return new Request(target, request);
}

function isNavigation(request) {
  const accept = request.headers.get("accept") ?? "";
  return (request.method === "GET" || request.method === "HEAD") && accept.includes("text/html");
}

/** What visitors get when the origin is down: JSON for the API, the page for a
 *  navigation, a bare 503 for anything else. Never cached, and says when to retry. */
export function fallback(request, page) {
  const { pathname } = new URL(request.url);
  const headers = {
    "cache-control": "no-store",
    "retry-after": String(RETRY_AFTER_SECONDS),
    [FALLBACK_HEADER]: "1",
  };
  const body = (text) => (request.method === "HEAD" ? null : text);
  if (pathname === "/api" || pathname.startsWith("/api/")) {
    // 502, not 503: the frontend reads the API's 503 as "no data yet" (isNoData); any
    // other status shows its `detail` under "Couldn't load this".
    return new Response(body(JSON.stringify({ detail: API_MESSAGE })), {
      status: 502,
      headers: { ...headers, "content-type": "application/json" },
    });
  }
  if (isNavigation(request)) {
    return new Response(body(page), {
      status: 503,
      headers: { ...headers, "content-type": "text/html; charset=utf-8" },
    });
  }
  return new Response(body("Service unavailable"), {
    status: 503,
    headers: { ...headers, "content-type": "text/plain; charset=utf-8" },
  });
}

/** A redirect the origin sent to its own address points back at the visitor's. */
function keepVisitorOnTheirHost(response, request, origin) {
  const location = response.headers.get("location");
  if (!origin || !location || !location.startsWith(origin)) return response;
  const copy = new Response(response.body, response);
  copy.headers.set("location", new URL(request.url).origin + location.slice(origin.length));
  return copy;
}

export async function handle(
  request,
  { origin, page, fetchImpl = fetch, timeoutMs = DEFAULT_TIMEOUT_MS },
) {
  const upstream = toOrigin(request, origin);
  const controller = new AbortController();
  // The timer covers the wait for the response's headers only. It is cleared before the
  // body streams, so a big or slow body is never cut and nothing is buffered.
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    // redirect: "manual" hands the origin's redirects to the browser unchanged.
    response = await fetchImpl(upstream, { signal: controller.signal, redirect: "manual" });
  } catch {
    return fallback(request, page);
  } finally {
    clearTimeout(timer);
  }
  if (originIsDown(response)) {
    // Release the error body (Railway's page) instead of leaving it unread.
    try {
      await response.body?.cancel();
    } catch {
      // nothing to release
    }
    return fallback(request, page);
  }
  return keepVisitorOnTheirHost(response, request, origin);
}
