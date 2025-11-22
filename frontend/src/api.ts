import axios from 'axios';
import type { Card, CardMatch, SimilarCard } from './types';

const API_URL = '/api';

const api = axios.create({
  baseURL: API_URL,
});

export const searchCards = async (query: string): Promise<CardMatch[]> => {
  if (!query || query.length < 2) return [];
  const response = await api.get<CardMatch[]>('/suggest-names', {
    params: { q: query, limit: 10 },
  });
  return response.data;
};

export const getCard = async (id: string): Promise<Card> => {
  const response = await api.get<Card>(`/card/${id}`);
  return response.data;
};

export const getSimilarCards = async (id: string, offset: number = 0, limit: number = 24): Promise<SimilarCard[]> => {
  const response = await api.get<SimilarCard[]>(`/similar-cards/${id}`, {
    params: { limit, offset }
  });
  return response.data;
};
