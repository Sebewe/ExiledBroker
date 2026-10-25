import { Navigate, Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import About from './pages/About'
import Backtest from './pages/Backtest'
import Conversions from './pages/Conversions'
import PriceCheck from './pages/PriceCheck'
import Launch from './pages/Launch'
import Missed from './pages/Missed'
import NotFound from './pages/NotFound'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route index element={<Missed />} />
        <Route path="backtest" element={<Backtest />} />
        {/* Retired: their loops and cards are on the Market recap now. */}
        <Route path="arbitrage" element={<Navigate to="/#loops" replace />} />
        <Route path="cards" element={<Navigate to="/#cards" replace />} />
        <Route path="launch" element={<Launch />} />
        <Route path="price-check" element={<PriceCheck />} />
        {/* Retired: its stack seller is on Price check now (Farming.tsx goes in workstream E). */}
        <Route path="farming" element={<Navigate to="/price-check" replace />} />
        <Route path="conversions" element={<Conversions />} />
        <Route path="about" element={<About />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Layout>
  )
}
