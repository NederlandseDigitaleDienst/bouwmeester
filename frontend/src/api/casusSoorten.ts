import { apiDelete, apiGet, apiPost, apiPut } from './client';
import type { CasusSoort, CasusSoortSummary } from '@/types';

const basis = (initiatiefId: string) => `/api/initiatieven/${initiatiefId}/casussoorten`;

export async function getCasusSoorten(initiatiefId: string): Promise<CasusSoort[]> {
  return apiGet<CasusSoort[]>(basis(initiatiefId));
}

export async function createCasusSoort(
  initiatiefId: string,
  data: { naam: string; kleur?: string; uitleg?: string | null },
): Promise<CasusSoort> {
  return apiPost<CasusSoort>(basis(initiatiefId), data);
}

export async function updateCasusSoort(
  initiatiefId: string,
  soortId: string,
  data: { naam?: string; kleur?: string; uitleg?: string | null; hoe_ver?: string | null; start_eisen?: string[]; eind_eisen?: string[] },
): Promise<CasusSoort> {
  return apiPut<CasusSoort>(`${basis(initiatiefId)}/${soortId}`, data);
}

export async function deleteCasusSoort(initiatiefId: string, soortId: string): Promise<void> {
  return apiDelete(`${basis(initiatiefId)}/${soortId}`);
}

export async function reorderCasusSoorten(initiatiefId: string, soortIds: string[]): Promise<CasusSoort[]> {
  return apiPost<CasusSoort[]>(`${basis(initiatiefId)}/reorder`, { soort_ids: soortIds });
}

export async function zetCasusSoorten(casusId: string, soortIds: string[]): Promise<CasusSoortSummary[]> {
  return apiPut<CasusSoortSummary[]>(`/api/casussen/${casusId}/soorten`, { soort_ids: soortIds });
}
