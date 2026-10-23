import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import App from './App'
import './index.css'
import { persist, restore } from './lib/persist'

const queryClient = new QueryClient({
  defaultOptions: {
    // Data changes once an hour, when the worker loads a new hour; queries are keyed on
    // the API's data version (see api/queries.ts), so nothing refetches on a timer, and
    // switching pages reuses what's loaded for hours (gcTime) instead of asking again.
    queries: { staleTime: Infinity, gcTime: 6 * 3_600_000, refetchOnWindowFocus: false, retry: 1 },
  },
})
// Kept in this browser between visits too (lib/persist).
restore(queryClient, __BUILD_ID__)
persist(queryClient, __BUILD_ID__)

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
