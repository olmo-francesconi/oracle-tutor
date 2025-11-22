export interface Card {
  id: string;
  name: string;
  mana_cost?: string;
  type_line?: string;
  oracle_text?: string;
  power?: string;
  toughness?: string;
  edhrec_rank?: number;
  rarity?: string;
  colors?: string[];
  legalities?: Record<string, string>;
}

export interface SimilarCard extends Card {
  similarity: number;
}

export interface CardMatch {
  name: string;
  id: string;
  similarity?: number;
  rank?: number;
}
