import { useQuery } from '@tanstack/react-query'
import { getApiReady } from './api'

const POLL_INTERVAL_MS = 2000
const MAX_ATTEMPTS = 60

export function useApiReady() {
  const query = useQuery({
    queryKey: ['api-ready'],
    queryFn: ({ signal }) => getApiReady(signal),
    retry: false,
    staleTime: Infinity,
    refetchInterval: (q) =>
      q.state.data || q.state.dataUpdateCount + q.state.errorUpdateCount >= MAX_ATTEMPTS
        ? false
        : POLL_INTERVAL_MS,
  })
  const ready = query.data === true
  const attempts = query.failureCount + (query.data === undefined ? 0 : 1)
  const error =
    !ready && attempts >= MAX_ATTEMPTS
      ? new Error('API did not become ready after maximum polling attempts')
      : null
  return { ready, attempts, error }
}
