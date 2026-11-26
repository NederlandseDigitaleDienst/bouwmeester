import { apiGet, apiPost, apiPut, apiDelete } from './client';
import type {
  BacklogResponse,
  Casus,
  CasusDetail,
  CasusKoelkast,
  CasusPubliek,
  CasusStart,
  CasusTeamlid,
  CasusUpdate,
} from '@/types';

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

/** In de koelkast zetten, of de reden en datum bijwerken. De fase blijft staan. */
export async function zetInKoelkast(id: string, data: CasusKoelkast): Promise<CasusDetail> {
  return apiPut<CasusDetail>(`/api/casussen/${id}/koelkast`, data);
}

/** Uit de koelkast: de casus gaat verder in zijn fase. */
export async function haalUitKoelkast(id: string): Promise<CasusDetail> {
  return apiDelete<CasusDetail>(`/api/casussen/${id}/koelkast`);
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

/** Geef een afgeronde casus vrij voor buiten, of pas de tekst aan. */
export async function publishCasus(id: string, data: CasusPubliek): Promise<CasusDetail> {
  return apiPut<CasusDetail>(`/api/casussen/${id}/publiek`, data);
}

/** Trek een vrijgegeven casus in; de tekst blijft bewaard. */
export async function unpublishCasus(id: string): Promise<CasusDetail> {
  return apiDelete<CasusDetail>(`/api/casussen/${id}/publiek`);
}
