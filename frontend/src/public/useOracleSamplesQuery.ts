import { useQuery } from '@tanstack/react-query'
import { getOracleSamples } from '../lib/api'

export function useOracleSamplesQuery() {
  return useQuery({
    queryKey: ['oracle-samples'],
    queryFn: ({ signal }) => getOracleSamples(signal),
    staleTime: 10 * 60_000,
  })
}
