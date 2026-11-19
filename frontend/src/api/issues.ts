import { apiGet, apiPost, apiPut, apiDelete } from './client';
import type { Issue, IssueCreate, IssueUpdate } from '@/types';

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
