import { useQuery } from '@tanstack/react-query'
import { getCard } from '../lib/api'
import { useApiReadyValue } from '../lib/apiReadyContext'

export function useCardQuery(oracleId: string | null | undefined) {
  const apiReady = useApiReadyValue()
  return useQuery({
    queryKey: ['card', oracleId],
    queryFn: ({ signal }) => getCard(oracleId!, signal),
    enabled: apiReady && Boolean(oracleId),
  })
}
