import { useQuery } from '@tanstack/react-query'
import {
  getAdminSemanticDatasets,
  getAdminSemanticModels,
} from '../lib/adminApi'

export function useAdminModels() {
  return useQuery({
    queryKey: ['admin', 'models'],
    queryFn: ({ signal }) => getAdminSemanticModels(signal),
  })
}

export function useAdminDatasets() {
  return useQuery({
    queryKey: ['admin', 'datasets'],
    queryFn: ({ signal }) => getAdminSemanticDatasets(signal),
  })
}
