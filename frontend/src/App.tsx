import { useEffect } from 'react'
import { Route, BrowserRouter as Router, Routes } from 'react-router-dom'
import { DeveloperLinks } from './components/DeveloperLinks'
import { SearchBar } from './components/SearchBar'
import { SystemStatus } from './components/SystemStatus'
import { CardPage } from './pages/CardPage'
import { OracleSearchPage } from './pages/OracleSearchPage'

function Home() {
  useEffect(() => {
    document.title = 'OracleTutor'
  }, [])

  return (
    <div className="relative z-10 flex min-h-[80vh] flex-col items-center justify-center px-4">
      <div className="w-full max-w-[600px] animate-[fadeIn_0.5s_ease-in] rounded-[24px] border border-white/20 bg-[#f5f2eb]/95 p-10 text-[#1c1c1c] shadow-2xl backdrop-blur-xl">
        <h1 className="mb-4 text-center text-5xl font-bold tracking-tight text-[#1c1c1c]">
          Oracle Tutor
        </h1>
        <p className="mb-8 text-center text-lg font-light text-[#525252]">
          Find cards by semantic meaning, not just keywords.
        </p>
        <SearchBar />
      </div>
      <DeveloperLinks
        variant="light"
        className="fixed bottom-0 left-0 px-6 py-4"
      />
    </div>
  )
}

function App() {
  return (
    <Router>
      <div className="min-h-screen bg-transparent text-[#f5f1e8]">
        {/* Header/Nav can be added here if needed, but legacy Home was centered without a top nav */}
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/card/:id" element={<CardPage />} />
          <Route path="/search" element={<OracleSearchPage />} />
        </Routes>
        <SystemStatus />
      </div>
    </Router>
  )
}

export default App
