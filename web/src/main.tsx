import { ApiError } from '@/lib/api'
import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { TooltipProvider } from '@/components/ui/tooltip'
import App from './App'
import './index.css'

const qc = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      retry: (failureCount, error: any) => {
        // Immediately reject non-retryable 4xx client errors
        if (error instanceof ApiError && [400, 401, 403, 404].includes(error.status)) {
          return false
        }
        if (error?.status && [400, 401, 403, 404].includes(error.status)) {
          return false
        }
        // Allow up to 7 retries for Render cold start (>50s total window)
        return failureCount < 7
      },
      retryDelay: (attempt) => Math.min(1500 * (1.6 ** attempt), 10000),
    },
  },
})

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <TooltipProvider>
          <App />
        </TooltipProvider>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
)
