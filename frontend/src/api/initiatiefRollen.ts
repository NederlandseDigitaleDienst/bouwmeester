import { apiDelete, apiGet, apiPost, apiPut } from './client';
import type {
  InitiatiefCirkel,
  InitiatiefRol,
  InitiatiefRolInput,
  PersoonWerk,
  RollenImportResultaat,
} from '@/types';

const basis = (initiatiefId: string) => `/api/initiatieven/${initiatiefId}/rollen`;

export function getRollen(initiatiefId: string): Promise<InitiatiefRol[]> {
  return apiGet<InitiatiefRol[]>(basis(initiatiefId));
}

export function createRol(initiatiefId: string, data: InitiatiefRolInput & { naam: string }): Promise<InitiatiefRol> {
  return apiPost<InitiatiefRol>(basis(initiatiefId), data);
}

export function updateRol(initiatiefId: string, rolId: string, data: InitiatiefRolInput): Promise<InitiatiefRol> {
  return apiPut<InitiatiefRol>(`${basis(initiatiefId)}/${rolId}`, data);
}

export function deleteRol(initiatiefId: string, rolId: string): Promise<void> {
  return apiDelete(`${basis(initiatiefId)}/${rolId}`);
}

export function zetInteresse(
  initiatiefId: string,
  rolId: string,
  personId: string,
  invulling: string | null,
): Promise<InitiatiefRol> {
  return apiPut<InitiatiefRol>(`${basis(initiatiefId)}/${rolId}/interesse/${personId}`, { invulling });
}

export function verwijderInteresse(initiatiefId: string, rolId: string, personId: string): Promise<InitiatiefRol> {
  return apiDelete<InitiatiefRol>(`${basis(initiatiefId)}/${rolId}/interesse/${personId}`);
}

export function maakRaakvlak(
  initiatiefId: string,
  rolId: string,
  anderRolId: string,
  omschrijving: string | null,
): Promise<InitiatiefRol> {
  return apiPost<InitiatiefRol>(`${basis(initiatiefId)}/${rolId}/raakvlakken`, { rol_id: anderRolId, omschrijving });
}

export function verwijderRaakvlak(initiatiefId: string, raakvlakId: string): Promise<void> {
  return apiDelete(`/api/initiatieven/${initiatiefId}/raakvlakken/${raakvlakId}`);
}

export function getCirkel(initiatiefId: string): Promise<InitiatiefCirkel> {
  return apiGet<InitiatiefCirkel>(`/api/initiatieven/${initiatiefId}/cirkel`);
}

export function updateCirkel(
  initiatiefId: string,
  data: { doel?: string | null; focus?: string[] },
): Promise<InitiatiefCirkel> {
  return apiPut<InitiatiefCirkel>(`/api/initiatieven/${initiatiefId}/cirkel`, data);
}

export function getPersoonWerk(initiatiefId: string, personId: string): Promise<PersoonWerk> {
  return apiGet<PersoonWerk>(`/api/initiatieven/${initiatiefId}/personen/${personId}/werk`);
}

export function zetPersoonFocus(initiatiefId: string, personId: string, focus: string[]): Promise<{ focus: string[] }> {
  return apiPut<{ focus: string[] }>(`/api/initiatieven/${initiatiefId}/personen/${personId}/focus`, { focus });
}

export function exportRollen(initiatiefId: string): Promise<unknown> {
  return apiGet<unknown>(`${basis(initiatiefId)}/export`);
}

export function importRollen(initiatiefId: string, data: unknown): Promise<RollenImportResultaat> {
  return apiPost<RollenImportResultaat>(`${basis(initiatiefId)}/import`, data);
}
