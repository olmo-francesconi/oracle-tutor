import { lazy, Suspense } from 'react'
import { Route, BrowserRouter as Router, Routes } from 'react-router-dom'
import { DeveloperLinks } from './components/DeveloperLinks'
import { PageSEO } from './components/PageSEO'
import { SearchCard } from './components/SearchCard'
import { MobileBottomBar } from './components/MobileBottomBar'
import { DEFAULT_DESCRIPTION, DEFAULT_TITLE } from './lib/seo'

const CardPage = lazy(() => import('./pages/CardPage'))
const OracleSearchPage = lazy(() => import('./pages/OracleSearchPage'))

function Home() {
  return (
    <>
      <PageSEO
        title={DEFAULT_TITLE}
        description={DEFAULT_DESCRIPTION}
        path="/"
      />
      <div className="relative z-10 flex min-h-[80vh] flex-col items-center justify-center gap-12 px-4 py-12">
        <div className="animate-[fadeIn_0.5s_ease-in] text-center">
          <h1 className="mb-4 font-['Goudy_Bookletter_1911'] text-6xl font-bold tracking-tight text-[#f5f2eb] drop-shadow-lg">
            Oracle Tutor
          </h1>
          <p className="font-['Crimson_Text'] text-xl font-light text-[#d4d4d4] drop-shadow-md">
            Find cards by semantic meaning, not just keywords.
          </p>
        </div>

        <div
          className="w-full max-w-[400px] animate-[slideUp_0.5s_ease-out_0.2s] opacity-0"
          style={{ animationFillMode: 'forwards' }}
        >
          <SearchCard />
        </div>

        <div className="fixed bottom-0 left-0 hidden md:block">
          <div className="flex items-end justify-between gap-6 px-5 pt-6 pb-5">
            <DeveloperLinks variant="light" />
          </div>
        </div>
        <MobileBottomBar />
      </div>
    </>
  )
}

function App() {
  return (
    <Router>
      <div className="relative min-h-screen bg-transparent text-[#f5f1e8]">
        <Suspense fallback={<div className="flex min-h-screen items-center justify-center text-[#d4d4d4]">Loading…</div>}>
          <Routes>
            <Route path="/" element={<Home />} />
            <Route path="/card/:id" element={<CardPage />} />
            <Route path="/search" element={<OracleSearchPage />} />
          </Routes>
        </Suspense>
      </div>
    </Router>
  )
}

export default App
