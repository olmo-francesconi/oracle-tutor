import type { SemanticTrainJobCreate } from '../types/api'

export type DatasetFormState = { dataset_slug: string; augmentation_keys: string[] }

export const DEFAULT_DATASET_FORM: DatasetFormState = { dataset_slug: '', augmentation_keys: [] }

export type TrainFormState = Omit<SemanticTrainJobCreate, 'requested_by'>

export const DEFAULT_TRAIN_FORM: TrainFormState = {
  dataset_id: '',
  model_slug: '',
  base_model_key: 'mini-lm-l6-v2',
  skip_fine_tune: true,
  epochs: 2,
  batch_size: 64,
  promote_after_register: false,
  embed_batch_size: 256,
}
