import { useMutation, useQueryClient } from '@tanstack/react-query'
import {
  queueSemanticDatasetJob,
  queueSemanticPromotion,
  queueSemanticTrainJob,
} from '../lib/adminApi'
import type { SemanticDatasetJobCreate, SemanticTrainJobCreate } from '../types/api'

export function useQueueDatasetJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: SemanticDatasetJobCreate) => queueSemanticDatasetJob(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'jobs'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'datasets'] })
    },
  })
}

export function useQueueTrainJob() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (payload: SemanticTrainJobCreate) => queueSemanticTrainJob(payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'jobs'] })
    },
  })
}

export function useQueuePromotion() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (vars: {
      modelId: string
      payload: { requested_by: string; embed_batch_size: number }
    }) => queueSemanticPromotion(vars.modelId, vars.payload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['admin', 'jobs'] })
      void queryClient.invalidateQueries({ queryKey: ['admin', 'models'] })
    },
  })
}
