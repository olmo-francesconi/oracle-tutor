import { useQuery } from '@tanstack/react-query'
import { getCard } from '../lib/api'

export function useCardQuery(oracleId: string | null | undefined) {
  return useQuery({
    queryKey: ['card', oracleId],
    queryFn: ({ signal }) => getCard(oracleId!, signal),
    enabled: Boolean(oracleId),
  })
}
