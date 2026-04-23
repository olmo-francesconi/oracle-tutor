import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { QueryClientProvider } from '@tanstack/react-query'
import './styles.css'
import './mana-font.css'
import { ErrorBoundary } from './components/ErrorBoundary'
import { queryClient } from './lib/queryClient'
import { PublicApp } from './public/PublicApp'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <PublicApp />
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>
)
