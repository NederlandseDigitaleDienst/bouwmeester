import { useQuery } from '@tanstack/react-query';
import {
  getIssues,
  createIssue,
  updateIssue,
  deleteIssue,
  publishIssue,
  unpublishIssue,
  getVerslag,
  uploadVerslag,
  deleteVerslag,
  maakVerslagOpenbaar,
  trekVerslagOpenbaarIn,
} from '@/api/issues';
import { useMutationWithError } from '@/hooks/useMutationWithError';
import { queryKeys } from '@/hooks/queryKeys';
import type { VraagPlek } from '@/api/issues';
import type { IssueCreate, IssuePubliek, IssueUpdate } from '@/types';

/** De vragen van een casus. */
export function useIssues(casusId: string | null) {
  return useQuery({
    queryKey: queryKeys.issues.forCasus(casusId),
    queryFn: () => getIssues({ casus_id: casusId }),
    enabled: !!casusId,
  });
}

// De backlog (onder tasks.list) toont issues ook, dus die ververst mee.
// Een issue dat verhuist neemt zijn taken mee, en verandert de tellers op de
// casuskaartjes: die lijsten ook verversen.
const ISSUE_KEYS = [queryKeys.issues.all, queryKeys.tasks.lists(), queryKeys.casussen.all];

// Een vraag die naar buiten gaat of terugkomt, verandert ook wat de tab
// Updates kan meenemen en wat de updates tonen. Een gewone wijziging kan dat
// ook (heropenen trekt in), dus die ververst deze lijsten mee.
const PUBLIEK_KEYS = [['vrijgegeven-vragen'], ['initiatief-updates'], ['klaar-om-te-delen']];

export function useCreateIssue() {
  return useMutationWithError({
    mutationFn: ({ plek, data }: { plek: VraagPlek; data: IssueCreate }) => createIssue(plek, data),
    errorMessage: 'Fout bij aanmaken onderzoeksvraag',
    invalidateKeys: ISSUE_KEYS,
  });
}

export function useUpdateIssue() {
  return useMutationWithError({
    mutationFn: ({ plek, issueId, data }: { plek: VraagPlek; issueId: string; data: IssueUpdate }) =>
      updateIssue(plek, issueId, data),
    errorMessage: 'Fout bij bijwerken onderzoeksvraag',
    invalidateKeys: [...ISSUE_KEYS, ...PUBLIEK_KEYS],
  });
}

export function useDeleteIssue() {
  return useMutationWithError({
    mutationFn: ({ plek, issueId }: { plek: VraagPlek; issueId: string }) => deleteIssue(plek, issueId),
    errorMessage: 'Fout bij verwijderen onderzoeksvraag',
    // De taken eronder worden los; ISSUE_KEYS ververst die lijst al.
    invalidateKeys: ISSUE_KEYS,
  });
}

export function usePublishIssue() {
  return useMutationWithError({
    mutationFn: ({ plek, issueId, data }: { plek: VraagPlek; issueId: string; data: IssuePubliek }) =>
      publishIssue(plek, issueId, data),
    errorMessage: 'Fout bij vrijgeven onderzoeksvraag',
    invalidateKeys: [...ISSUE_KEYS, ...PUBLIEK_KEYS],
  });
}

export function useUnpublishIssue() {
  return useMutationWithError({
    mutationFn: ({ plek, issueId }: { plek: VraagPlek; issueId: string }) => unpublishIssue(plek, issueId),
    errorMessage: 'Fout bij intrekken onderzoeksvraag',
    invalidateKeys: [...ISSUE_KEYS, ...PUBLIEK_KEYS],
  });
}

// ---------------------------------------------------------------------------
// Onderzoeksverslag
// ---------------------------------------------------------------------------

const verslagKey = (issueId: string) => ['onderzoeksverslag', issueId] as const;
// Een verslag dat naar buiten gaat of terugkomt, verandert ook wat de tab
// Updates en de publieke pagina tonen.
const VERSLAG_KEYS = [['onderzoeksverslag'], ...PUBLIEK_KEYS];

export function useVerslag(plek: VraagPlek, issueId: string) {
  return useQuery({
    queryKey: verslagKey(issueId),
    queryFn: () => getVerslag(plek, issueId),
  });
}

export function useUploadVerslag() {
  return useMutationWithError({
    mutationFn: ({ plek, issueId, file }: { plek: VraagPlek; issueId: string; file: File }) =>
      uploadVerslag(plek, issueId, file),
    errorMessage: 'Fout bij uploaden onderzoeksverslag',
    invalidateKeys: VERSLAG_KEYS,
  });
}

export function useDeleteVerslag() {
  return useMutationWithError({
    mutationFn: ({ plek, issueId }: { plek: VraagPlek; issueId: string }) => deleteVerslag(plek, issueId),
    errorMessage: 'Fout bij weghalen onderzoeksverslag',
    invalidateKeys: VERSLAG_KEYS,
  });
}

export function useVerslagOpenbaar() {
  return useMutationWithError({
    mutationFn: ({ plek, issueId }: { plek: VraagPlek; issueId: string }) => maakVerslagOpenbaar(plek, issueId),
    errorMessage: 'Fout bij openbaar maken onderzoeksverslag',
    invalidateKeys: VERSLAG_KEYS,
  });
}

export function useVerslagNietOpenbaar() {
  return useMutationWithError({
    mutationFn: ({ plek, issueId }: { plek: VraagPlek; issueId: string }) => trekVerslagOpenbaarIn(plek, issueId),
    errorMessage: 'Fout bij terughalen onderzoeksverslag',
    invalidateKeys: VERSLAG_KEYS,
  });
}
