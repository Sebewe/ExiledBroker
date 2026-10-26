// Budgets the built site's downloads (run after `npm run build`). A first visit loads
// index.html's script, its preloads and the stylesheet; the chart library must stay out of
// that set (it's lazy-loaded by the pages that draw charts, `components/LazyChart.tsx`).
// Sizes are gzipped, as served. Raise a budget only with a reason, in the same change.
import { readdirSync, readFileSync } from 'node:fs'
import { gzipSync } from 'node:zlib'

const BUDGET_KB = { firstVisit: 130, chart: 180 }

const dist = new URL('../dist/', import.meta.url)
const gz = (file) => gzipSync(readFileSync(new URL(file, dist)), { level: 9 }).length / 1024
const html = readFileSync(new URL('index.html', dist), 'utf8')
const first = [...html.matchAll(/(?:src|href)="\/(assets\/[^"]+\.(?:js|css))"/g)].map((m) => m[1])
const chart = readdirSync(new URL('assets/', dist)).filter((f) => /^Chart-.*\.js$/.test(f))

const failures = []
const firstKb = first.reduce((sum, f) => sum + gz(f), 0)
console.log(`first visit: ${firstKb.toFixed(1)} kB gzipped in ${first.length} files (budget ${BUDGET_KB.firstVisit})`)
for (const f of first) console.log(`  ${gz(f).toFixed(1).padStart(6)} kB  ${f}`)
if (firstKb > BUDGET_KB.firstVisit) failures.push(`first visit is ${firstKb.toFixed(1)} kB, over ${BUDGET_KB.firstVisit}`)

if (chart.length !== 1) failures.push(`expected one lazy Chart chunk, found ${chart.length}`)
for (const f of chart) {
  const kb = gz(`assets/${f}`)
  console.log(`chart (lazy): ${kb.toFixed(1)} kB gzipped (budget ${BUDGET_KB.chart})`)
  if (kb > BUDGET_KB.chart) failures.push(`the chart chunk is ${kb.toFixed(1)} kB, over ${BUDGET_KB.chart}`)
  if (first.includes(`assets/${f}`)) failures.push('the chart chunk is loaded on a first visit')
}

if (failures.length) {
  for (const f of failures) console.error(`bundle budget: ${f}`)
  process.exit(1)
}
