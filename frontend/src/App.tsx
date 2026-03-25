import { Route, BrowserRouter as Router, Routes } from 'react-router-dom'
import HomePage from './pages/HomePage'
import ResultsPage from './pages/ResultsPage'

function App() {
  return (
    <Router>
      <div className="relative min-h-screen bg-[#F0EDE6] text-[#111111]">
        <Routes>
          <Route path="/" element={<HomePage />} />
          <Route path="/card/:id" element={<ResultsPage />} />
          <Route path="/search" element={<ResultsPage />} />
        </Routes>
      </div>
    </Router>
  )
}

export default App
