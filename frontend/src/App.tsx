import { lazy, Suspense } from 'react'
import { Route, BrowserRouter as Router, Routes } from 'react-router-dom'

const HomePage = lazy(() => import('./pages/HomePage'))
const ResultsPage = lazy(() => import('./pages/ResultsPage'))

function App() {
  return (
    <Router>
      <div className="relative min-h-screen bg-[#F0EDE6] text-[#111111]">
        <Suspense
          fallback={
            <div className="flex min-h-screen items-center justify-center text-[#7A7670]">
              Loading…
            </div>
          }
        >
          <Routes>
            <Route path="/" element={<HomePage />} />
            <Route path="/card/:id" element={<ResultsPage />} />
            <Route path="/search" element={<ResultsPage />} />
          </Routes>
        </Suspense>
      </div>
    </Router>
  )
}

export default App
