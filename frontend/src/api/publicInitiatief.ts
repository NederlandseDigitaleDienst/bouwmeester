import { apiGet, BASE_URL } from './client';
import type { PublicInitiatief } from '@/types';

export async function getPublicInitiatief(slug: string): Promise<PublicInitiatief> {
  return apiGet<PublicInitiatief>(
    `/api/public/initiatieven/by-slug/${encodeURIComponent(slug)}`,
  );
}

/** De download van een openbaar onderzoeksverslag op de publieke pagina. */
export function getPubliekVerslagUrl(slug: string, verslagId: string): string {
  return `${BASE_URL}/api/public/initiatieven/by-slug/${encodeURIComponent(slug)}/verslagen/${verslagId}`;
}
