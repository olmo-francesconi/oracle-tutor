import { useInfiniteQuery } from '@tanstack/react-query'
import { searchOracleText } from '../lib/api'
import type { FilterState } from '../types/api'

const RESULTS_PAGE_SIZE = 24

export function useSearchQuery(query: string | null, filters: FilterState) {
  return useInfiniteQuery({
    queryKey: ['search', query, filters],
    enabled: query !== null && query.length > 0,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      searchOracleText(query!, pageParam, RESULTS_PAGE_SIZE, filters, signal),
    getNextPageParam: (lastPage, allPages) =>
      lastPage.has_more ? allPages.reduce((sum, page) => sum + page.items.length, 0) : undefined,
  })
}
