import { useQuery } from '@tanstack/react-query';
import { getIssues, createIssue, updateIssue, deleteIssue } from '@/api/issues';
import { useMutationWithError } from '@/hooks/useMutationWithError';
import { queryKeys } from '@/hooks/queryKeys';
import type { VraagPlek } from '@/api/issues';
import type { IssueCreate, IssueUpdate } from '@/types';

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
    invalidateKeys: ISSUE_KEYS,
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
