import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import { Research } from './components/Research'
import { Skeleton } from './components/QueryState'
import Missed from './pages/Missed'
import NotFound from './pages/NotFound'

// The landing page (Market recap) ships in the main bundle; the others load when first
// opened, so a first visit downloads only what it shows (a link straight to Price check
// fetches its chunk in parallel with the main one).
const About = lazy(() => import('./pages/About'))
const Admin = lazy(() => import('./pages/Admin')) // the owner's, not linked anywhere
const Backtest = lazy(() => import('./pages/Backtest'))
const Conversions = lazy(() => import('./pages/Conversions'))
const Launch = lazy(() => import('./pages/Launch'))
const PriceCheck = lazy(() => import('./pages/PriceCheck'))

export default function App() {
  return (
    <Layout>
      <Suspense fallback={<Skeleton />}>
        <Routes>
          <Route index element={<Missed />} />
          {/* Research: the proof and the notes behind the tools, apart from the pages a
              player trades from. The Backtest moved here on 2026-10-26. */}
          <Route path="research" element={<Navigate to="/research/backtest" replace />} />
          <Route
            path="research/backtest"
            element={
              <Research>
                <Backtest />
              </Research>
            }
          />
          <Route path="backtest" element={<Navigate to="/research/backtest" replace />} />
          {/* Retired: their loops and cards are on the Market recap now. */}
          <Route path="arbitrage" element={<Navigate to="/#loops" replace />} />
          <Route path="cards" element={<Navigate to="/#cards" replace />} />
          <Route path="launch" element={<Launch />} />
          <Route path="price-check" element={<PriceCheck />} />
          {/* Retired: its stack seller is on Price check now. */}
          <Route path="farming" element={<Navigate to="/price-check" replace />} />
          <Route path="conversions" element={<Conversions />} />
          <Route path="about" element={<About />} />
          <Route path="admin" element={<Admin />} />
          <Route path="*" element={<NotFound />} />
        </Routes>
      </Suspense>
    </Layout>
  )
}
