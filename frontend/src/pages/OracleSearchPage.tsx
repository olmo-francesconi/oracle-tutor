import { useInfiniteQuery } from '@tanstack/react-query'
import { ArrowLeft, MagnifyingGlass } from '@phosphor-icons/react'
import { useEffect, useMemo, useState } from 'react'
import { Link, useNavigate, useSearchParams } from 'react-router-dom'
import { searchOracleText } from '../api'
import { CardGrid } from '../components/CardGrid'
import { CardOverlay } from '../components/CardOverlay'
import { DeveloperLinks } from '../components/DeveloperLinks'
import type { SimilarCard } from '../types'

export function OracleSearchPage() {
  const [searchParams] = useSearchParams()
  const query = searchParams.get('q') || ''
  const navigate = useNavigate()
  const [selectedCard, setSelectedCard] = useState<SimilarCard | null>(null)
  const [searchTerm, setSearchTerm] = useState(query)

  const {
    data: similarData,
    fetchNextPage,
    hasNextPage,
    isFetchingNextPage,
    isLoading: similarLoading,
  } = useInfiniteQuery({
    queryKey: ['oracle-search', query],
    queryFn: ({ pageParam = 0 }) => {
      return searchOracleText(query, pageParam, 60)
    },
    initialPageParam: 0,
    getNextPageParam: (lastPage, allPages) => {
      // If we received fewer items than the limit (60), we're at the end
      return lastPage.length === 60 ? allPages.length * 60 : undefined
    },
    enabled: !!query,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
    staleTime: Infinity,
  })

  const similarCards = useMemo(() => {
    return similarData?.pages.flatMap((page) => page) || []
  }, [similarData])

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault()
    if (searchTerm.trim()) {
      navigate(`/search?q=${encodeURIComponent(searchTerm.trim())}`)
    }
  }

  // Update document title
  useEffect(() => {
    if (query) {
      document.title = `"${query}" - Oracle Tutor`
    }
  }, [query])

  // Handle keyboard ESC to close overlay
  useEffect(() => {
    const handleEsc = (e: KeyboardEvent) => {
      if (e.key === 'Escape') setSelectedCard(null)
    }
    window.addEventListener('keydown', handleEsc)
    return () => window.removeEventListener('keydown', handleEsc)
  }, [])

  const noResultsMessage = (
    <div className="text-center text-[#737373]">
      <p className="mb-2 text-lg font-medium">No results found</p>
      <p className="text-sm">Try adjusting your search terms</p>
    </div>
  )

  return (
    <div className="flex h-screen w-full flex-col overflow-hidden bg-transparent md:flex-row">
      {/* Overlay Component */}
      {selectedCard && (
        <CardOverlay
          card={selectedCard}
          onClose={() => setSelectedCard(null)}
        />
      )}

      {/* Sidebar - Search Details */}
      <div className="flex h-full w-full flex-shrink-0 flex-col overflow-y-auto border-r border-[#e5e5e5] bg-[#f5f2eb] p-5 md:w-[380px]">
        <Link
          to="/"
          className="mb-6 flex items-center gap-2 text-[#525252] transition-colors hover:text-[#1c1c1c]"
        >
          <ArrowLeft className="h-4 w-4" /> Back to Search
        </Link>

        {/* Query "Paper" Container */}
        <div className="rounded-xl border border-[#e5e5e5] bg-white p-5 text-[#1c1c1c] shadow-lg">
          <div className="mb-5 flex aspect-[5/3] w-full flex-col items-center justify-center rounded-lg border border-[#e5e5e5] bg-[#f0f0f0] p-4">
            <MagnifyingGlass className="mb-2 h-12 w-12 text-[#a3a3a3]" />
            <span className="text-sm font-medium text-[#737373]">
              Oracle Search
            </span>
          </div>

          <form onSubmit={handleSearch} className="group relative mb-2">
            <input
              type="text"
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              placeholder="Describe card meaning..."
              className="w-full rounded-lg border-2 border-[#e5e5e5] bg-white p-3 pl-10 text-lg font-medium text-[#1c1c1c] placeholder-[#a3a3a3] transition-all outline-none focus:border-[#d4d4d4] focus:bg-[#fafafa]"
            />
            <MagnifyingGlass className="absolute top-1/2 left-3 h-5 w-5 -translate-y-1/2 text-[#a3a3a3] transition-colors group-focus-within:text-[#1c1c1c]" />
          </form>

          <div className="mt-4 border-t border-[#e5e5e5] pt-4">
            <p className="text-sm leading-relaxed text-[#404040]">
              Searching for cards with similar meaning to your query.
            </p>
          </div>
        </div>

        <div className="mt-auto pt-6">
          <DeveloperLinks variant="dark" />
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
  )
}
