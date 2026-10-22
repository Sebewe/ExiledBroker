import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router'
import App from './App'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    // Data changes once an hour, when the worker loads a new hour; queries are keyed on
    // the API's data version (see api/queries.ts), so nothing refetches on a timer.
    queries: { staleTime: Infinity, refetchOnWindowFocus: false, retry: 1 },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
)
