import { Navigate, Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import About from './pages/About'
import Backtest from './pages/Backtest'
import Conversions from './pages/Conversions'
import Farming from './pages/Farming'
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
        <Route path="farming" element={<Farming />} />
        <Route path="conversions" element={<Conversions />} />
        <Route path="about" element={<About />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Layout>
  )
}
