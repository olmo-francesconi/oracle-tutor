export interface CardFace {
  oracle_id: string
  face_ix: number
  name: string
  mana_cost?: string
  type_line?: string
  oracle_text?: string
  power?: string
  toughness?: string
  colors?: string[]
  image_uris?: Record<string, string>
}

export interface Card {
  id: string
  oracle_id: string
  scryfall_id: string
  name: string
  layout?: string
  cmc?: number
  mana_cost?: string
  type_line?: string
  oracle_text?: string
  power?: string
  toughness?: string
  edhrec_rank?: number
  rarity?: string
  colors?: string[]
  legalities?: Record<string, string>
  border_color?: string
  set_code?: string
  faces?: CardFace[]
}

export interface SimilarCard extends Card {
  face_ix: number
  image_side: 'front' | 'back'
  similarity: number
  card_name?: string
}

export interface SimilarCardsPage {
  items: SimilarCard[]
  has_more: boolean
}

export interface CardMatch {
  id: string
  name: string
  oracle_id: string | null
  scryfall_id: string | null
  face_ix: number
  image_side: 'front' | 'back'
  similarity?: number
  rank?: number
}

export interface FilterState {
  cardType?: string[]
  colors?: string
  format?: string[]
  cmcMin?: number
  cmcMax?: number
  rarities?: string[]
  matchMode?: 'exact' | 'at_most' | 'at_least'
  colorFeature?: 'identity' | 'colors'
}

export interface OracleSamples {
  texts: string[]
  terms: string[]
}

export interface AdminAuthTokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export interface SemanticModelSummary {
  id: number
  slug: string
  base_model_key?: string | null
  base_model: string
  status: string
  is_active: boolean
  embedding_dim: number
  artifact_sha256: string
  artifact_size_bytes: number
  created_at: string
  activated_at?: string | null
  error_message?: string | null
}

export interface SemanticJobSummary {
  id: number
  job_type: 'train' | 'promote' | 'dataset' | string
  status: 'pending' | 'running' | 'succeeded' | 'failed' | 'cancelled' | string
  requested_by: string
  model_id?: number | null
  dataset_id?: string | null
  created_at: string
  started_at?: string | null
  heartbeat_at?: string | null
  finished_at?: string | null
  error_message?: string | null
}

export interface SemanticJobDetail extends SemanticJobSummary {
  payload_json: Record<string, unknown>
  result_json?: Record<string, unknown> | null
}

export interface SemanticTrainJobCreate {
  requested_by: string
  dataset_id: string
  model_slug: string
  base_model_key: string
  skip_fine_tune: boolean
  epochs: number
  batch_size: number
  promote_after_register: boolean
  embed_batch_size: number
}

export interface SemanticPromoteAccepted {
  accepted: boolean
  job_id: number
  model_id: number
  status: string
}

export interface SemanticBaseModelOption {
  key: string
  label: string
  base_model: string
  embedding_dim: number
}

export interface SemanticTrainAugmentationOption {
  key: string
  label: string
  description: string
  default_enabled: boolean
}

export interface SemanticTrainOptions {
  epoch_min: number
  epoch_max: number
  batch_size_options: number[]
  embed_batch_size_options: number[]
  augmentation_options: SemanticTrainAugmentationOption[]
}

export interface SemanticDatasetSummary {
  id: string
  slug: string
  status: 'ready' | 'failed' | string
  augmentation_mode: string
  source_semantic_data_version: number | null
  created_at: string
  error_message?: string | null
}

export interface SemanticDatasetJobCreate {
  requested_by: string
  dataset_slug: string
  augmentation_mode: string
}
