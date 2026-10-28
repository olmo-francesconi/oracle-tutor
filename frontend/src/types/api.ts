import type { z } from 'zod'
import type {
  CardAbilitySchema,
  CardFaceSchema,
  CardMatchSchema,
  CardSchema,
  OracleSamplesSchema,
  SimilarCardSchema,
  SimilarCardsPageSchema,
} from './schemas'

// `id` is added client-side from scryfall_id (see normalizeCard in lib/api.ts).
export type CardAbility = z.infer<typeof CardAbilitySchema>
export type CardFace = z.infer<typeof CardFaceSchema>
export type Card = z.infer<typeof CardSchema> & { id: string }
export type SimilarCard = z.infer<typeof SimilarCardSchema> & { id: string }
export type SimilarCardsPage = Omit<z.infer<typeof SimilarCardsPageSchema>, 'items'> & {
  items: SimilarCard[]
}
export type CardMatch = z.infer<typeof CardMatchSchema> & { id: string }
export type OracleSamples = z.infer<typeof OracleSamplesSchema>

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
