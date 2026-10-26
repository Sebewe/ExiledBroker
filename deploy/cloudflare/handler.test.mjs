// Run with: node --test "deploy/cloudflare/*.test.mjs"   (Node 20+, no dependencies; fetch is stubbed.)
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import { handle } from "./handler.mjs";

const ORIGIN = "https://web-production.up.railway.app";
const PAGE = readFileSync(new URL("./fallback.html", import.meta.url), "utf8");
const APP = { "x-eb-origin": "app" };

const visit = (path, headers = {}, method = "GET") =>
  new Request(`https://example.com${path}`, { method, headers });
const nav = (path = "/") => visit(path, { accept: "text/html,application/xhtml+xml" });
const api = (path = "/api/status") => visit(path, { accept: "application/json" });

/** Runs the Worker with a stubbed origin; returns the response and what the origin saw. */
async function run(request, origin, options = {}) {
  const seen = [];
  const fetchImpl = async (req, init) => {
    seen.push({ req, init });
    return typeof origin === "function" ? origin(req, init) : origin;
  };
  const response = await handle(request, { origin: ORIGIN, page: PAGE, fetchImpl, ...options });
  return { response, seen };
}

test("the app's 200 passes through untouched, to the origin's address", async () => {
  const upstream = new Response('{"ok":true}', {
    status: 200,
    headers: { ...APP, etag: '"v1"', "cache-control": "public, max-age=60" },
  });
  const { response, seen } = await run(api("/api/status?x=1"), upstream);
  assert.equal(response, upstream); // the very same response: nothing copied or buffered
  assert.equal(response.status, 200);
  assert.equal(await response.text(), '{"ok":true}');
  assert.equal(response.headers.get("etag"), '"v1"');
  assert.equal(seen.length, 1);
  assert.equal(seen[0].req.url, `${ORIGIN}/api/status?x=1`);
  assert.equal(seen[0].req.method, "GET");
});

test("the app's own 503 (no data yet) is its answer, not an outage", async () => {
  const body = '{"detail":"No data loaded yet"}';
  const upstream = new Response(body, { status: 503, headers: { ...APP, "content-type": "application/json" } });
  const { response } = await run(api(), upstream);
  assert.equal(response.status, 503);
  assert.equal(await response.text(), body);
  assert.equal(response.headers.get("x-eb-fallback"), null);
});

test("the app's 404 and 422 pass through too", async () => {
  for (const status of [404, 422]) {
    const { response } = await run(api(), new Response('{"detail":"x"}', { status, headers: APP }));
    assert.equal(response.status, status);
    assert.equal(response.headers.get("x-eb-fallback"), null);
  }
});

test("a 304 passes through, and so do the conditional headers", async () => {
  const { response, seen } = await run(
    visit("/api/missed/Allflame", { "if-none-match": '"v1"' }),
    new Response(null, { status: 304, headers: { ...APP, etag: '"v1"' } }),
  );
  assert.equal(response.status, 304);
  assert.equal(response.headers.get("etag"), '"v1"');
  assert.equal(seen[0].req.headers.get("if-none-match"), '"v1"');
});

test("methods and the body are passed on unchanged", async () => {
  const request = new Request("https://example.com/api/x", { method: "POST", body: "hi" });
  const { response, seen } = await run(request, new Response("no", { status: 405, headers: APP }));
  assert.equal(response.status, 405);
  assert.equal(seen[0].req.method, "POST");
  assert.equal(await seen[0].req.text(), "hi");
});

test("a Railway 502 for a page navigation gives the fallback page", async () => {
  const railway = new Response("Bad Gateway", { status: 502 }); // no X-EB-Origin
  const { response } = await run(nav("/launch"), railway);
  assert.equal(response.status, 503);
  assert.match(response.headers.get("content-type"), /^text\/html/);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.ok(Number(response.headers.get("retry-after")) > 0);
  const html = await response.text();
  assert.match(html, /Something went wrong, we're investigating/);
  assert.equal(html, PAGE);
});

test("a Railway 502 for the API gives JSON the frontend shows as an error", async () => {
  const { response } = await run(api(), new Response("Bad Gateway", { status: 502 }));
  // Not 503: the frontend reads the API's 503 as "no data yet".
  assert.equal(response.status, 502);
  assert.match(response.headers.get("content-type"), /^application\/json/);
  assert.equal(response.headers.get("cache-control"), "no-store");
  assert.ok(Number(response.headers.get("retry-after")) > 0);
  assert.match((await response.json()).detail, /investigating/);
});

test("Railway's own 404 and 503 pages (stopped service, usage limit) are replaced", async () => {
  for (const status of [404, 503, 504, 500]) {
    const { response } = await run(nav(), new Response("Application not found", { status }));
    assert.equal(response.status, 503, `origin ${status}`);
    assert.equal(response.headers.get("x-eb-fallback"), "1");
  }
});

test("an asset request gets a bare 503, not the page", async () => {
  const { response } = await run(visit("/assets/app-abc.js", { accept: "*/*" }), new Response("", { status: 502 }));
  assert.equal(response.status, 503);
  assert.match(response.headers.get("content-type"), /^text\/plain/);
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("a HEAD request for the fallback has no body", async () => {
  const { response } = await run(visit("/", { accept: "text/html" }, "HEAD"), new Response("", { status: 502 }));
  assert.equal(response.status, 503);
  assert.equal(await response.text(), "");
});

test("a fetch that throws gives the fallback", async () => {
  const boom = () => {
    throw new TypeError("Network connection lost");
  };
  const page = await run(nav(), boom);
  assert.equal(page.response.status, 503);
  assert.match(await page.response.text(), /investigating/);
  const json = await run(api(), boom);
  assert.equal(json.response.status, 502);
});

test("an origin that never answers times out into the fallback", async () => {
  const hang = (_req, init) =>
    new Promise((_resolve, reject) =>
      init.signal.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError"))),
    );
  const started = Date.now();
  const { response } = await run(nav(), hang, { timeoutMs: 30 });
  assert.equal(response.status, 503);
  assert.ok(Date.now() - started < 2000);
});

test("the timeout covers the headers only: a slow body is not cut", async () => {
  let abortedAfterHeaders = false;
  const slow = (_req, init) => {
    init.signal.addEventListener("abort", () => (abortedAfterHeaders = true));
    const body = new ReadableStream({
      async start(controller) {
        controller.enqueue(new TextEncoder().encode("first,"));
        await new Promise((r) => setTimeout(r, 120)); // well past timeoutMs
        controller.enqueue(new TextEncoder().encode("second"));
        controller.close();
      },
    });
    return new Response(body, { status: 200, headers: APP });
  };
  const { response } = await run(api(), slow, { timeoutMs: 30 });
  assert.equal(await response.text(), "first,second");
  assert.equal(abortedAfterHeaders, false);
});

test("a redirect to the origin's own address is pointed back at the visitor's host", async () => {
  const upstream = new Response(null, {
    status: 301,
    headers: { ...APP, location: `${ORIGIN}/launch` },
  });
  const { response, seen } = await run(nav("/launch/"), upstream);
  assert.equal(response.status, 301);
  assert.equal(response.headers.get("location"), "https://example.com/launch");
  assert.equal(seen[0].init.redirect, "manual");
});

test("without an ORIGIN the request goes to its own URL", async () => {
  const { seen } = await run(api("/api/health"), new Response("{}", { headers: APP }), { origin: "" });
  assert.equal(seen[0].req.url, "https://example.com/api/health");
});

test("reads go through Cloudflare's cache, kept as the origin's Cache-Control allows", async () => {
  for (const method of ["GET", "HEAD"]) {
    const { seen } = await run(visit("/api/missed/Allflame?v=1", {}, method), new Response(null, { headers: APP }));
    assert.deepEqual(seen[0].init.cf, { cacheEverything: true });
    assert.equal(seen[0].init.redirect, "manual");
  }
});

test("anything else is never cached", async () => {
  const { seen } = await run(
    new Request("https://example.com/api/x", { method: "POST", body: "{}" }),
    new Response(null, { headers: APP }),
  );
  assert.equal(seen[0].init.cf, undefined);
});

test("the fallback is never cached", async () => {
  const { response } = await run(api("/api/missed/Allflame"), new Response("", { status: 502 }));
  assert.equal(response.headers.get("cache-control"), "no-store");
});

test("the fallback page is self-contained", () => {
  assert.doesNotMatch(PAGE, /https?:\/\//i); // no external requests
  assert.doesNotMatch(PAGE, /<script|<link|<img|@import|url\(/i);
  assert.match(PAGE, /<title>[^<]+<\/title>/);
});
