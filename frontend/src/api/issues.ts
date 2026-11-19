import { apiGet, apiPost, apiPut, apiDelete, BASE_URL, getCsrfToken } from './client';
import type { Issue, IssueCreate, IssuePubliek, IssueUpdate, Onderzoeksverslag } from '@/types';

/**
 * Waar een vraag staat: in een casus, of zonder casus bij het initiatief.
 * Een vraag zelf (Issue, BacklogIssue) heeft deze velden ook, dus die kun je
 * meteen meegeven.
 */
export interface VraagPlek {
  casus_id?: string | null;
  initiatief_id?: string | null;
}

/** Het pad van de vragen op een plek. */
export function vraagBasis(plek: VraagPlek): string {
  if (plek.casus_id) return `/api/casussen/${plek.casus_id}/issues`;
  if (plek.initiatief_id) return `/api/initiatieven/${plek.initiatief_id}/vragen`;
  throw new Error('Een vraag hoort bij een casus of een initiatief');
}

export async function getIssues(plek: VraagPlek): Promise<Issue[]> {
  return apiGet<Issue[]>(vraagBasis(plek));
}

export async function createIssue(plek: VraagPlek, data: IssueCreate): Promise<Issue> {
  return apiPost<Issue>(vraagBasis(plek), data);
}

/** `data.casus_id`: naar die casus; `null`: uit de casus, naar het initiatief. */
export async function updateIssue(plek: VraagPlek, issueId: string, data: IssueUpdate): Promise<Issue> {
  return apiPut<Issue>(`${vraagBasis(plek)}/${issueId}`, data);
}

export async function deleteIssue(plek: VraagPlek, issueId: string): Promise<void> {
  return apiDelete(`${vraagBasis(plek)}/${issueId}`);
}

/** Geef een afgeronde onderzoeksvraag vrij voor buiten, of pas de publieke tekst aan. */
export async function publishIssue(plek: VraagPlek, issueId: string, data: IssuePubliek): Promise<Issue> {
  return apiPut<Issue>(`${vraagBasis(plek)}/${issueId}/publiek`, data);
}

/** Trek een vrijgegeven vraag in; de tekst blijft bewaard. */
export async function unpublishIssue(plek: VraagPlek, issueId: string): Promise<Issue> {
  return apiDelete<Issue>(`${vraagBasis(plek)}/${issueId}/publiek`);
}

// ---------------------------------------------------------------------------
// Onderzoeksverslag bij een onderzoeksvraag
// ---------------------------------------------------------------------------

const verslagPad = (plek: VraagPlek, issueId: string) => `${vraagBasis(plek)}/${issueId}/verslag`;

/** Het verslag van de vraag, of null als er nog geen is. */
export async function getVerslag(plek: VraagPlek, issueId: string): Promise<Onderzoeksverslag | null> {
  return apiGet<Onderzoeksverslag | null>(verslagPad(plek, issueId));
}

/** Upload het verslag, of vervang het bestaande; vervangen zet het akkoord terug. */
export async function uploadVerslag(plek: VraagPlek, issueId: string, file: File): Promise<Onderzoeksverslag> {
  const formData = new FormData();
  formData.append('file', file);
  const response = await fetch(`${BASE_URL}${verslagPad(plek, issueId)}`, {
    method: 'POST',
    headers: { 'X-CSRF-Token': getCsrfToken() },
    body: formData,
    credentials: 'include',
  });
  if (!response.ok) {
    const tekst = await response.text();
    let detail = tekst;
    try {
      detail = (JSON.parse(tekst) as { detail?: string }).detail ?? tekst;
    } catch {
      // geen JSON: de tekst zelf
    }
    throw new Error(detail);
  }
  return response.json();
}

export async function deleteVerslag(plek: VraagPlek, issueId: string): Promise<void> {
  return apiDelete(verslagPad(plek, issueId));
}

/** Akkoord: het verslag mag naar buiten (op de publieke pagina zodra de vraag vrijgegeven is). */
export async function maakVerslagOpenbaar(plek: VraagPlek, issueId: string): Promise<Onderzoeksverslag> {
  return apiPut<Onderzoeksverslag>(`${verslagPad(plek, issueId)}/openbaar`, { akkoord: true });
}

export async function trekVerslagOpenbaarIn(plek: VraagPlek, issueId: string): Promise<Onderzoeksverslag> {
  return apiDelete<Onderzoeksverslag>(`${verslagPad(plek, issueId)}/openbaar`);
}

export function getVerslagDownloadUrl(plek: VraagPlek, issueId: string): string {
  return `${BASE_URL}${verslagPad(plek, issueId)}/download`;
}
