import { useQuery } from '@tanstack/react-query';
import { getIssues, createIssue, updateIssue, deleteIssue } from '@/api/issues';
import { useMutationWithError } from '@/hooks/useMutationWithError';
import { queryKeys } from '@/hooks/queryKeys';
import type { IssueCreate, IssueUpdate } from '@/types';

export function useIssues(casusId: string | null) {
  return useQuery({
    queryKey: queryKeys.issues.forCasus(casusId),
    queryFn: () => getIssues(casusId!),
    enabled: !!casusId,
  });
}

// De backlog (onder tasks.list) toont issues ook, dus die ververst mee.
// Een issue dat verhuist neemt zijn taken mee, en verandert de tellers op de
// casuskaartjes: die lijsten ook verversen.
const ISSUE_KEYS = [queryKeys.issues.all, queryKeys.tasks.lists(), queryKeys.casussen.all];

export function useCreateIssue() {
  return useMutationWithError({
    mutationFn: ({ casusId, data }: { casusId: string; data: IssueCreate }) => createIssue(casusId, data),
    errorMessage: 'Fout bij aanmaken onderzoeksvraag',
    invalidateKeys: ISSUE_KEYS,
  });
}

export function useUpdateIssue() {
  return useMutationWithError({
    mutationFn: ({ casusId, issueId, data }: { casusId: string; issueId: string; data: IssueUpdate }) =>
      updateIssue(casusId, issueId, data),
    errorMessage: 'Fout bij bijwerken onderzoeksvraag',
    invalidateKeys: ISSUE_KEYS,
  });
}

export function useDeleteIssue() {
  return useMutationWithError({
    mutationFn: ({ casusId, issueId }: { casusId: string; issueId: string }) => deleteIssue(casusId, issueId),
    errorMessage: 'Fout bij verwijderen onderzoeksvraag',
    // De taken eronder worden los; ISSUE_KEYS ververst die lijst al.
    invalidateKeys: ISSUE_KEYS,
  });
}
