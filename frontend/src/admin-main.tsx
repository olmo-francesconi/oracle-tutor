import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import './mana-font.css'
import { ErrorBoundary } from './components/ErrorBoundary'
import { setupGlobalErrorHandlers } from './lib/observability'
import { AdminApp } from './admin/AdminApp'

setupGlobalErrorHandlers()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <AdminApp />
    </ErrorBoundary>
  </StrictMode>
)
