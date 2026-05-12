import { useQuery } from '@tanstack/react-query'
import { getOracleSamples } from '../lib/api'
import { useApiReadyValue } from '../lib/apiReadyContext'

export function useOracleSamplesQuery() {
  const apiReady = useApiReadyValue()
  return useQuery({
    queryKey: ['oracle-samples'],
    queryFn: ({ signal }) => getOracleSamples(signal),
    enabled: apiReady,
    staleTime: 10 * 60_000,
  })
}
