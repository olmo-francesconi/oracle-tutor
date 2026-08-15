/** One segmented ability of a face — the unit similarity is scored over. */
export interface CardAbility {
  ability_ix: number
  text: string
  is_keyword: boolean
}

export interface CardFace {
  oracle_id: string
  face_ix: number
  name: string
  mana_cost?: string | null
  type_line?: string | null
  oracle_text?: string | null
  power?: string | null
  toughness?: string | null
  colors?: string[] | null
  image_uris?: Record<string, string> | null
  abilities?: CardAbility[] | null
}

export interface Card {
  id: string
  oracle_id: string
  scryfall_id: string
  name: string
  layout?: string | null
  cmc?: number | null
  mana_cost?: string | null
  type_line?: string | null
  oracle_text?: string | null
  power?: string | null
  toughness?: string | null
  edhrec_rank?: number | null
  rarity?: string | null
  colors?: string[] | null
  legalities?: Record<string, string> | null
  border_color?: string | null
  set_code?: string | null
  faces?: CardFace[] | null
}

export interface SimilarCard extends Card {
  face_ix: number
  image_side: 'front' | 'back'
  similarity: number
  /** The single ability that drove the match, for highlighting why this card ranked. */
  matched_ability?: string | null
  card_name?: string | null
}

export interface SimilarCardsPage {
  items: SimilarCard[]
  has_more: boolean
}

export interface CardMatch {
  id: string
  name: string
  card_name?: string | null
  oracle_id: string | null
  scryfall_id: string | null
  face_ix: number
  image_side: 'front' | 'back'
  similarity?: number | null
  rank?: number | null
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
  /** Exclude bare keyword abilities (Flying, Trample, ...) from similarity scoring. */
  ignoreKeywords?: boolean
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
  id: string
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

export interface SemanticDatasetSummary {
  id: string
  slug: string
  status: 'ready' | 'failed' | string
  augmentation_mode: string
  source_semantic_data_version: number | null
  created_at: string
  error_message?: string | null
}

