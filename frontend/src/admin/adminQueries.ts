import { useQuery } from '@tanstack/react-query'
import {
  getAdminSemanticDatasets,
  getAdminSemanticModels,
} from '../lib/adminApi'

// All admin queries share the leading key 'admin' so the Refresh button can
// invalidate the entire board at once via invalidateQueries({ queryKey: ['admin'] }).

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
