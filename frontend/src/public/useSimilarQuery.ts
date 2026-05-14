import { useInfiniteQuery } from '@tanstack/react-query'
import { getSimilarCards } from '../lib/api'
import type { FilterState } from '../types/api'
import type { PinnedCard } from '../types/ui'
import { useApiReadyValue } from '../lib/apiReadyContext'

const RESULTS_PAGE_SIZE = 24

export function useSimilarQuery(pinnedCard: PinnedCard | null, filters: FilterState) {
  const apiReady = useApiReadyValue()
  return useInfiniteQuery({
    queryKey: ['similar', pinnedCard?.oracle_id, pinnedCard?.face_ix, filters],
    enabled: apiReady && pinnedCard !== null,
    initialPageParam: 0,
    queryFn: ({ pageParam, signal }) =>
      getSimilarCards(
        pinnedCard!.oracle_id,
        pinnedCard!.face_ix,
        pageParam,
        RESULTS_PAGE_SIZE,
        filters,
        signal
      ),
    getNextPageParam: (lastPage, allPages) =>
      lastPage.has_more ? allPages.reduce((sum, page) => sum + page.items.length, 0) : undefined,
  })
}
