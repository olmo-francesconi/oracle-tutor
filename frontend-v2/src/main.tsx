import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './styles.css'
import './mana-font.css'
import App from './App.tsx'
import { ErrorBoundary } from './components/ErrorBoundary'
import { setupGlobalErrorHandlers } from './lib/observability'

setupGlobalErrorHandlers()

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ErrorBoundary>
      <App />
    </ErrorBoundary>
  </StrictMode>
)
