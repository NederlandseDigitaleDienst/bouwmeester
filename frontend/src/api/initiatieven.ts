import { apiGet, apiPost, apiPut, apiDelete } from './client';
import type {
  InitiatiefPersoon,
  Initiatief,
  InitiatiefCreate,
  InitiatiefDetail,
  InitiatiefEenheid,
  InitiatiefListItem,
  InitiatiefMember,
  InitiatiefSettingsUpdate,
  InitiatiefUpdate,
  InitiatiefUpdatePost,
  InitiatiefUpdatePostCreate,
  InitiatiefUpdatePostEdit,
} from '@/types';

export async function getInitiatieven(params?: {
  search?: string;
}): Promise<InitiatiefListItem[]> {
  const query: Record<string, string> = {};
  if (params?.search) query.search = params.search;
  return apiGet<InitiatiefListItem[]>('/api/initiatieven', query);
}

export async function getInitiatiefPersonen(id: string): Promise<InitiatiefPersoon[]> {
  return apiGet<InitiatiefPersoon[]>(`/api/initiatieven/${id}/personen`);
}

export async function getInitiatief(id: string): Promise<InitiatiefDetail> {
  return apiGet<InitiatiefDetail>(`/api/initiatieven/${id}`);
}

export async function createInitiatief(data: InitiatiefCreate): Promise<Initiatief> {
  return apiPost<Initiatief>('/api/initiatieven', data);
}

export async function updateInitiatief(
  id: string,
  data: InitiatiefUpdate,
): Promise<Initiatief> {
  return apiPut<Initiatief>(`/api/initiatieven/${id}`, data);
}

export async function updateInitiatiefSettings(
  id: string,
  data: InitiatiefSettingsUpdate,
): Promise<Initiatief> {
  return apiPut<Initiatief>(`/api/initiatieven/${id}/settings`, data);
}

// ---------------------------------------------------------------------------
// InitiatiefUpdatePost — internal CRUD for publication posts
// ---------------------------------------------------------------------------

export async function getInitiatiefUpdates(
  initiatiefId: string,
): Promise<InitiatiefUpdatePost[]> {
  return apiGet<InitiatiefUpdatePost[]>(
    `/api/initiatieven/${initiatiefId}/updates`,
  );
}

export async function createInitiatiefUpdate(
  initiatiefId: string,
  data: InitiatiefUpdatePostCreate,
): Promise<InitiatiefUpdatePost> {
  return apiPost<InitiatiefUpdatePost>(
    `/api/initiatieven/${initiatiefId}/updates`,
    data,
  );
}

export async function editInitiatiefUpdate(
  initiatiefId: string,
  postId: string,
  data: InitiatiefUpdatePostEdit,
): Promise<InitiatiefUpdatePost> {
  return apiPut<InitiatiefUpdatePost>(
    `/api/initiatieven/${initiatiefId}/updates/${postId}`,
    data,
  );
}

export async function publishInitiatiefUpdate(
  initiatiefId: string,
  postId: string,
): Promise<InitiatiefUpdatePost> {
  return apiPost<InitiatiefUpdatePost>(
    `/api/initiatieven/${initiatiefId}/updates/${postId}/publish`,
    {},
  );
}

export async function unpublishInitiatiefUpdate(
  initiatiefId: string,
  postId: string,
): Promise<InitiatiefUpdatePost> {
  return apiPost<InitiatiefUpdatePost>(
    `/api/initiatieven/${initiatiefId}/updates/${postId}/unpublish`,
    {},
  );
}

export async function deleteInitiatiefUpdate(
  initiatiefId: string,
  postId: string,
): Promise<void> {
  return apiDelete(`/api/initiatieven/${initiatiefId}/updates/${postId}`);
}

export async function addInitiatiefMember(
  initiatiefId: string,
  personId: string,
  rol: string = 'contributor',
): Promise<InitiatiefMember> {
  return apiPost<InitiatiefMember>(`/api/initiatieven/${initiatiefId}/members`, {
    person_id: personId,
    rol,
  });
}

export async function removeInitiatiefMember(
  initiatiefId: string,
  personId: string,
): Promise<void> {
  return apiDelete(`/api/initiatieven/${initiatiefId}/members/${personId}`);
}

export async function updateInitiatiefMemberRole(
  initiatiefId: string,
  personId: string,
  rol: string,
): Promise<InitiatiefMember> {
  return apiPut<InitiatiefMember>(
    `/api/initiatieven/${initiatiefId}/members/${personId}`,
    { person_id: personId, rol },
  );
}

export async function addInitiatiefEenheid(
  initiatiefId: string,
  eenheidId: string,
  rol: string = 'contributor',
): Promise<InitiatiefEenheid> {
  return apiPost<InitiatiefEenheid>(`/api/initiatieven/${initiatiefId}/eenheden`, {
    eenheid_id: eenheidId,
    rol,
  });
}

export async function removeInitiatiefEenheid(
  initiatiefId: string,
  eenheidId: string,
): Promise<void> {
  return apiDelete(`/api/initiatieven/${initiatiefId}/eenheden/${eenheidId}`);
}

export async function updateInitiatiefEenheidRol(
  initiatiefId: string,
  eenheidId: string,
  rol: string,
): Promise<InitiatiefEenheid> {
  return apiPut<InitiatiefEenheid>(
    `/api/initiatieven/${initiatiefId}/eenheden/${eenheidId}`,
    { rol },
  );
}

export interface InitiatiefEenheidWithName {
  initiatief_id: string;
  initiatief_naam: string;
  eenheid_id: string;
  rol: string;
  created_at: string;
}

export async function getInitiatievenForEenheid(
  eenheidId: string,
): Promise<InitiatiefEenheidWithName[]> {
  return apiGet<InitiatiefEenheidWithName[]>(
    `/api/initiatieven/by-eenheid/${eenheidId}`,
  );
}
