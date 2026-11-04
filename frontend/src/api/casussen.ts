import { apiGet, apiPost, apiPut, apiDelete } from './client';
import type { BacklogResponse, Casus, CasusDetail, CasusStart, CasusTeamlid, CasusUpdate } from '@/types';

export async function getCasussen(initiatiefId?: string): Promise<Casus[]> {
  return apiGet<Casus[]>('/api/casussen', initiatiefId ? { initiatief_id: initiatiefId } : undefined);
}

export async function getCasus(id: string): Promise<CasusDetail> {
  return apiGet<CasusDetail>(`/api/casussen/${id}`);
}

export async function startCasus(data: CasusStart): Promise<CasusDetail> {
  return apiPost<CasusDetail>('/api/casussen', data);
}

export async function updateCasus(id: string, data: CasusUpdate): Promise<CasusDetail> {
  return apiPut<CasusDetail>(`/api/casussen/${id}`, data);
}

export async function deleteCasus(id: string): Promise<void> {
  return apiDelete(`/api/casussen/${id}`);
}

export async function addCasusTeamlid(
  casusId: string,
  personId: string,
  rol: 'trekker' | 'teamlid',
): Promise<CasusTeamlid> {
  return apiPost<CasusTeamlid>(`/api/casussen/${casusId}/team`, { person_id: personId, rol });
}

export async function removeCasusTeamlid(casusId: string, rpId: string): Promise<void> {
  return apiDelete(`/api/casussen/${casusId}/team/${rpId}`);
}

/** Alle issues van alle casussen van een initiatief, met hun taken, plus de losse taken. */
export async function getBacklog(initiatiefId: string): Promise<BacklogResponse> {
  return apiGet<BacklogResponse>('/api/casussen/backlog', { initiatief_id: initiatiefId });
}
