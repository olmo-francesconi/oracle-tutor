import { BrowserRouter as Router, Routes, Route } from 'react-router-dom';
import { SearchBar } from './components/SearchBar';
import { CardPage } from './pages/CardPage';
import { useEffect } from 'react';

function Home() {
  useEffect(() => {
    document.title = "OracleTutor";
  }, []);

  return (
    <div className="flex flex-col items-center justify-center min-h-[80vh] px-4 relative z-10">
      <div className="w-full max-w-[600px] bg-[#f5f2eb]/95 backdrop-blur-xl border border-white/20 text-[#1c1c1c] rounded-[24px] shadow-2xl p-10 animate-[fadeIn_0.5s_ease-in]">
        <h1 className="text-5xl font-bold text-[#1c1c1c] mb-4 text-center tracking-tight">Oracle Tutor</h1>
        <p className="text-[#525252] mb-8 text-center text-lg font-light">Find cards by semantic meaning, not just keywords.</p>
        <SearchBar />
      </div>
    </div>
  );
}

function App() {
  return (
    <Router>
      <div className="min-h-screen bg-transparent text-[#f5f1e8]">
        {/* Header/Nav can be added here if needed, but legacy Home was centered without a top nav */}
        <Routes>
          <Route path="/" element={<Home />} />
          <Route path="/card/:id" element={<CardPage />} />
        </Routes>
      </div>
    </Router>
  );
}

export default App;
