import { useSearchParams, Link, useNavigate } from 'react-router-dom';
import { useInfiniteQuery } from '@tanstack/react-query';
import { searchOracleText } from '../api';
import { ArrowLeft, Search } from 'lucide-react';
import { useEffect, useState, useMemo } from 'react';
import { CardOverlay } from '../components/CardOverlay';
import { CardGrid } from '../components/CardGrid';
import type { SimilarCard } from '../types';

export function OracleSearchPage() {
  const [searchParams] = useSearchParams();
  const query = searchParams.get('q') || '';
  const navigate = useNavigate();
  const [selectedCard, setSelectedCard] = useState<SimilarCard | null>(null);
  const [searchTerm, setSearchTerm] = useState(query);

  const {
    data: similarData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading: similarLoading
  } = useInfiniteQuery({
    queryKey: ['oracle-search', query],
    queryFn: ({ pageParam = 0 }) => {
      return searchOracleText(query, pageParam, 60);
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      // If we received fewer items than the limit (60), we're at the end
      return lastPage.length === 60 ? allPages.length * 60 : undefined;
    },
    enabled: !!query,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: Infinity,
  });

  const similarCards = useMemo(() => {
    return similarData?.pages.flatMap((page) => page) || [];
  }, [similarData]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (searchTerm.trim()) {
      navigate(`/search?q=${encodeURIComponent(searchTerm.trim())}`);
    }
  };

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

  const noResultsMessage = (
    <div className="text-[#737373] text-center">
      <p className="text-lg font-medium mb-2">No results found</p>
      <p className="text-sm">Try adjusting your search terms</p>
    </div>
  );

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
      <CardGrid
        cards={similarCards}
        isLoading={similarLoading}
        isFetchingNextPage={isFetchingNextPage}
        hasNextPage={!!hasNextPage}
        fetchNextPage={fetchNextPage}
        onCardClick={setSelectedCard}
        noResultsMessage={noResultsMessage}
        searchQuery={query}
      />
    </div>
  );
}
