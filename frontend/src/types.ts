export interface CardFace {
  name: string
  mana_cost?: string
  type_line?: string
  oracle_text?: string
  power?: string
  toughness?: string
  colors?: string[]
}

export interface Card {
  id: string
  name: string
  layout?: string
  mana_cost?: string
  type_line?: string
  oracle_text?: string
  power?: string
  toughness?: string
  edhrec_rank?: number
  rarity?: string
  colors?: string[]
  legalities?: Record<string, string>
  faces?: CardFace[]
}

export interface SimilarCard extends Card {
  similarity: number
  card_name?: string
}

export interface CardMatch {
  name: string
  id: string
  similarity?: number
  rank?: number
}

export interface FilterState {
  cardType?: string
  colors?: string
  format?: string
  cmcMin?: number
  cmcMax?: number
  rarity?: string
  matchMode?: 'exact' | 'subset'
}
