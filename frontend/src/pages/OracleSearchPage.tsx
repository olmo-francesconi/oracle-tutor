import { useSearchParams, Link, useNavigate } from 'react-router-dom';
import { useInfiniteQuery } from '@tanstack/react-query';
import { searchOracleText } from '../api';
import { ArrowLeft, SlidersHorizontal, Search } from 'lucide-react';
import { useEffect, useRef, useState } from 'react';
import { CardOverlay } from '../components/CardOverlay';
import type { SimilarCard } from '../types';
import { getCardImageUrl } from '../utils';

export function OracleSearchPage() {
  const [searchParams] = useSearchParams();
  const query = searchParams.get('q') || '';
  const navigate = useNavigate();
  const loadMoreRef = useRef<HTMLDivElement>(null);
  const [selectedCard, setSelectedCard] = useState<SimilarCard | null>(null);
  const [searchTerm, setSearchTerm] = useState(query);

  // Sync local state with URL query
  useEffect(() => {
    setSearchTerm(query);
    setSelectedCard(null);
  }, [query]);

  const {
    data: similarData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading: similarLoading
  } = useInfiniteQuery({
    queryKey: ['oracle-search', query],
    queryFn: ({ pageParam = 0 }) => searchOracleText(query, pageParam, 24),
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      // If we received fewer items than the limit (24), we're at the end
      return lastPage.length === 24 ? allPages.length * 24 : undefined;
    },
    enabled: !!query,
  });

  const similarCards = similarData?.pages.flatMap((page) => page) || [];

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchTerm.trim()) {
      navigate(`/search?q=${encodeURIComponent(searchTerm.trim())}`);
    }
  };

  // Intersection Observer for infinite scrolling
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0].isIntersecting && hasNextPage && !isFetchingNextPage) {
          fetchNextPage();
        }
      },
      { threshold: 0.1 }
    );

    if (loadMoreRef.current) {
      observer.observe(loadMoreRef.current);
    }

    return () => {
      if (loadMoreRef.current) {
        observer.unobserve(loadMoreRef.current);
      }
    };
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  // Update document title
  useEffect(() => {
    if (query) {
      document.title = `"${query}" - Oracle Tutor`;
    }
  }, [query]);

  // Handle keyboard ESC to close overlay
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedCard(null);
    };
    window.addEventListener('keydown', handleEsc);
    return () => window.removeEventListener('keydown', handleEsc);
  }, []);

  return (
    <div className="h-screen w-full flex flex-col md:flex-row overflow-hidden bg-transparent">
      
      {/* Overlay Component */}
      {selectedCard && (
        <CardOverlay 
          card={selectedCard} 
          onClose={() => setSelectedCard(null)} 
        />
      )}

      {/* Sidebar - Search Details */}
      <div className="w-full md:w-[380px] flex-shrink-0 h-full overflow-y-auto bg-[#f5f2eb] border-r border-[#e5e5e5] p-5 flex flex-col">
        <Link to="/" className="flex items-center gap-2 text-[#525252] mb-6 hover:text-[#1c1c1c] transition-colors">
          <ArrowLeft size={16} /> Back to Search
        </Link>

        {/* Query "Paper" Container */}
        <div className="bg-white rounded-xl p-5 shadow-lg border border-[#e5e5e5] text-[#1c1c1c]">
           <div className="flex flex-col items-center justify-center aspect-[5/3] w-full mb-5 bg-[#f0f0f0] rounded-lg border border-[#e5e5e5] p-4">
             <Search size={48} className="text-[#a3a3a3] mb-2" />
             <span className="text-[#737373] text-sm font-medium">Oracle Search</span>
           </div>

          <form onSubmit={handleSearch} className="mb-2 relative group">
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Describe card meaning..."
              className="w-full p-3 pl-10 text-lg font-medium border-2 border-[#e5e5e5] rounded-lg outline-none focus:border-[#d4d4d4] focus:bg-[#fafafa] transition-all text-[#1c1c1c] bg-white placeholder-[#a3a3a3]"
            />
            <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-[#a3a3a3] group-focus-within:text-[#1c1c1c] transition-colors" size={20} />
          </form>
          
          <div className="pt-4 border-t border-[#e5e5e5] mt-4">
             <p className="text-sm leading-relaxed text-[#404040]">
               Searching for cards with similar meaning to your query.
             </p>
          </div>
        </div>
      </div>

      {/* Main Content - Results Grid */}
      <div className="flex-1 h-full overflow-y-auto bg-transparent relative scroll-smooth">
        {/* Sticky Header */}
        <div className="sticky top-0 z-30 flex items-center justify-end px-6 py-4 bg-[#1c1c1c]/70 backdrop-blur-xl border-b border-white/5 transition-all duration-300 supports-[backdrop-filter]:bg-[#1c1c1c]/60">
          <div className="flex items-center gap-3">
            <button className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#262626] border border-white/5 text-[#f5f2eb] hover:bg-[#333] hover:border-[#e3dccb]/30 transition-all text-sm font-medium cursor-pointer shadow-sm active:scale-95">
              <SlidersHorizontal size={16} />
              <span>Filters</span>
            </button>
          </div>
        </div>
        
        {/* Results Grid */}
        <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-6 p-6 pt-6 pb-10">
          {similarCards.map((s) => (
            <div 
              key={s.id} 
              onClick={() => setSelectedCard(s)}
              className="group relative aspect-[5/7] overflow-hidden bg-[#262626] shadow-lg hover:-translate-y-1 hover:shadow-2xl hover:ring-1 hover:ring-[#e3dccb]/30 hover:scale-[1.02] border border-white/5 transition-all duration-300 block cursor-pointer" 
              style={{ borderRadius: '4.5% / 3.21%' }}
            >
               <img 
                src={getCardImageUrl(s)} 
                alt={s.name}
                loading="lazy"
                className="w-full h-full object-cover"
              />
              
              {/* Similarity Badge */}
              <div className="absolute top-3 left-1/2 -translate-x-1/2 bg-[#171717]/90 backdrop-blur-md border border-white/5 rounded-full px-3 py-1 flex items-center gap-2 shadow-lg z-10">
                <div className={`w-2 h-2 rounded-full ${s.similarity > 0.8 ? 'bg-emerald-500/80 shadow-[0_0_8px_rgba(16,185,129,0.4)]' : 'bg-amber-500/80 shadow-[0_0_8px_rgba(245,158,11,0.4)]'}`}></div>
                <span className="text-xs font-bold text-[#f5f2eb]">{(s.similarity * 100).toFixed(1)}%</span>
              </div>

               {/* Hover Name Overlay */}
              <div className="absolute inset-x-0 bottom-0 bg-gradient-to-t from-[#171717] via-[#171717]/90 to-transparent p-4 pt-12 translate-y-full group-hover:translate-y-0 transition-transform duration-300">
                 <p className="text-[#f5f2eb] text-center font-medium text-sm truncate">{s.name}</p>
              </div>
            </div>
          ))}
        </div>

        {/* Loading / Empty States */}
        <div ref={loadMoreRef} className="flex justify-center py-8">
          {(isFetchingNextPage || similarLoading) && (
             <div className="flex items-center gap-2 text-[#737373]">
                <div className="w-2 h-2 bg-[#e3dccb] rounded-full animate-bounce" style={{ animationDelay: '0s' }}></div>
                <div className="w-2 h-2 bg-[#e3dccb] rounded-full animate-bounce" style={{ animationDelay: '0.2s' }}></div>
                <div className="w-2 h-2 bg-[#e3dccb] rounded-full animate-bounce" style={{ animationDelay: '0.4s' }}></div>
             </div>
          )}
          {!similarLoading && similarCards.length === 0 && (
            <div className="text-[#737373] text-center">
                <p className="text-lg font-medium mb-2">No results found</p>
                <p className="text-sm">Try adjusting your search terms</p>
            </div>
          )}
          {!hasNextPage && similarCards.length > 0 && (
            <span className="text-[#525252] text-sm">End of results</span>
          )}
        </div>
      </div>
    </div>
  );
}
