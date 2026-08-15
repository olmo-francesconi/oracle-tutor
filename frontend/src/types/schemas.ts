import { z } from 'zod'

export const CardFaceSchema = z.object({
  oracle_id: z.string(),
  face_ix: z.number(),
  name: z.string(),
  mana_cost: z.string().nullish(),
  type_line: z.string().nullish(),
  oracle_text: z.string().nullish(),
  power: z.string().nullish(),
  toughness: z.string().nullish(),
  colors: z.array(z.string()).nullish(),
  image_uris: z.record(z.string(), z.string()).nullish(),
})

export const CardSchema = z.object({
  oracle_id: z.string(),
  scryfall_id: z.string(),
  name: z.string(),
  layout: z.string().nullish(),
  cmc: z.number().nullish(),
  mana_cost: z.string().nullish(),
  type_line: z.string().nullish(),
  oracle_text: z.string().nullish(),
  power: z.string().nullish(),
  toughness: z.string().nullish(),
  edhrec_rank: z.number().nullish(),
  rarity: z.string().nullish(),
  colors: z.array(z.string()).nullish(),
  legalities: z.record(z.string(), z.string()).nullish(),
  border_color: z.string().nullish(),
  set_code: z.string().nullish(),
  faces: z.array(CardFaceSchema).nullish(),
})

export const SimilarCardSchema = CardSchema.extend({
  face_ix: z.number(),
  image_side: z.enum(['front', 'back']),
  similarity: z.number(),
  // The single ability that drove the match, for highlighting why this card ranked.
  matched_ability: z.string().nullish(),
  card_name: z.string().nullish(),
})

export const SimilarCardsPageSchema = z.object({
  items: z.array(SimilarCardSchema),
  has_more: z.boolean(),
})

export const CardMatchSchema = z.object({
  name: z.string(),
  card_name: z.string().nullish(),
  oracle_id: z.string().nullable(),
  scryfall_id: z.string().nullable(),
  face_ix: z.number(),
  image_side: z.enum(['front', 'back']),
  similarity: z.number().nullish(),
  rank: z.number().nullish(),
})

export const CardMatchListSchema = z.array(CardMatchSchema)

export const OracleSamplesSchema = z.object({
  texts: z.array(z.string()),
  terms: z.array(z.string()),
})

export const AdminAuthTokenResponseSchema = z.object({
  access_token: z.string(),
  token_type: z.string(),
  expires_in: z.number(),
})

export const SemanticModelSummarySchema = z.object({
  id: z.string(),
  slug: z.string(),
  base_model_key: z.string().nullish(),
  base_model: z.string(),
  status: z.string(),
  is_active: z.boolean(),
  embedding_dim: z.number(),
  artifact_sha256: z.string(),
  artifact_size_bytes: z.number(),
  created_at: z.string(),
  activated_at: z.string().nullish(),
  error_message: z.string().nullish(),
})

export const SemanticModelListSchema = z.array(SemanticModelSummarySchema)

export const SemanticDatasetSummarySchema = z.object({
  id: z.string(),
  slug: z.string(),
  status: z.string(),
  augmentation_mode: z.string(),
  source_semantic_data_version: z.number().nullable(),
  created_at: z.string(),
  error_message: z.string().nullish(),
})

export const SemanticDatasetListSchema = z.array(SemanticDatasetSummarySchema)
