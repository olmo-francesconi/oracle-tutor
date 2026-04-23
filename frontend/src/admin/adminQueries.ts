import { useQuery } from '@tanstack/react-query'
import {
  getAdminSemanticBaseModels,
  getAdminSemanticDatasets,
  getAdminSemanticJobs,
  getAdminSemanticModels,
  getAdminSemanticTrainOptions,
} from '../lib/adminApi'

// All admin queries share the leading key 'admin' so the Refresh button can
// invalidate the entire board at once via invalidateQueries({ queryKey: ['admin'] }).

export function useAdminModels() {
  return useQuery({
    queryKey: ['admin', 'models'],
    queryFn: ({ signal }) => getAdminSemanticModels(signal),
  })
}

export function useAdminJobs() {
  return useQuery({
    queryKey: ['admin', 'jobs'],
    queryFn: ({ signal }) => getAdminSemanticJobs(signal),
  })
}

export function useAdminDatasets() {
  return useQuery({
    queryKey: ['admin', 'datasets'],
    queryFn: ({ signal }) => getAdminSemanticDatasets(signal),
  })
}

export function useAdminBaseModels() {
  return useQuery({
    queryKey: ['admin', 'base-models'],
    queryFn: ({ signal }) => getAdminSemanticBaseModels(signal),
    staleTime: 60 * 60_000, // rarely changes
  })
}

export function useAdminTrainOptions() {
  return useQuery({
    queryKey: ['admin', 'train-options'],
    queryFn: ({ signal }) => getAdminSemanticTrainOptions(signal),
    staleTime: 60 * 60_000,
  })
}
