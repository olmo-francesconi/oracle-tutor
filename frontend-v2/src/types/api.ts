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
  uniqueness?: number
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
  cardType?: string
  colors?: string
  format?: string
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
