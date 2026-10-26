import { lazy, Suspense } from 'react'
import { Navigate, Route, Routes, useLocation } from 'react-router'
import { Layout } from './components/Layout'
import { PageError } from './components/PageError'
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
const Journal = lazy(() => import('./pages/research/Journal'))
const Launch = lazy(() => import('./pages/Launch'))
const Method = lazy(() => import('./pages/research/Method'))
const Note = lazy(() => import('./pages/research/Note'))
const PriceCheck = lazy(() => import('./pages/PriceCheck'))

export default function App() {
  const { pathname } = useLocation()
  return (
    <Layout>
      <PageError resetKey={pathname}>
        <Suspense fallback={<Skeleton />}>
          <Routes>
            <Route index element={<Missed />} />
            {/* Research: the proof and the notes behind the tools, apart from the pages a
                player trades from (docs/decisions.md, 2026-10-26). Old addresses redirect. */}
            <Route path="research" element={<Research />}>
              <Route index element={<Journal />} />
              <Route path="notes/:n" element={<Note />} />
              <Route path="method" element={<Method />} />
              <Route path="backtest" element={<Backtest />} />
              <Route path="conversions" element={<Conversions />} />
              <Route path="about" element={<About />} />
            </Route>
            <Route path="backtest" element={<Navigate to="/research/backtest" replace />} />
            <Route path="conversions" element={<Navigate to="/research/conversions" replace />} />
            <Route path="about" element={<Navigate to="/research/about" replace />} />
            {/* Retired: their loops and cards are on the Market recap now. */}
            <Route path="arbitrage" element={<Navigate to="/#loops" replace />} />
            <Route path="cards" element={<Navigate to="/#cards" replace />} />
            <Route path="launch" element={<Launch />} />
            <Route path="price-check" element={<PriceCheck />} />
            {/* Retired: its stack seller is on Price check now. */}
            <Route path="farming" element={<Navigate to="/price-check" replace />} />
            <Route path="admin" element={<Admin />} />
            <Route path="*" element={<NotFound />} />
          </Routes>
        </Suspense>
      </PageError>
    </Layout>
  )
}
