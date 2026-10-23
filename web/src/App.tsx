import { Route, Routes } from 'react-router'
import { Layout } from './components/Layout'
import About from './pages/About'
import Arbitrage from './pages/Arbitrage'
import Cards from './pages/Cards'
import Conversions from './pages/Conversions'
import Launch from './pages/Launch'
import Missed from './pages/Missed'
import NotFound from './pages/NotFound'

export default function App() {
  return (
    <Layout>
      <Routes>
        <Route index element={<Missed />} />
        <Route path="arbitrage" element={<Arbitrage />} />
        <Route path="cards" element={<Cards />} />
        <Route path="launch" element={<Launch />} />
        <Route path="conversions" element={<Conversions />} />
        <Route path="about" element={<About />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Layout>
  )
}
