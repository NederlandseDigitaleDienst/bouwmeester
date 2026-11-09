import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  createCasusChannelLink,
  createInitiatiefChannelLink,
  createLeadChannelLink,
  deleteChannelLink,
  listCasusChannels,
  listCasusKanaalberichten,
  listInitiatiefChannels,
  listLeadChannels,
  searchMattermostChannels,
  updateChannelLink,
  type MattermostChannelLinkCreate,
  type MattermostChannelLinkUpdate,
} from '@/api/mattermostChannels';
import { queryKeys } from '@/hooks/queryKeys';

/** Waar een kanaal aan hangt. */
export type ChannelScope = {
  type: 'initiatief' | 'lead' | 'casus';
  id: string;
};

function scopeQueryKey(scope: ChannelScope) {
  if (scope.type === 'initiatief') {
    return queryKeys.initiatieven.mattermostChannels(scope.id);
  }
  if (scope.type === 'lead') return queryKeys.mattermostChannels.forLead(scope.id);
  return queryKeys.mattermostChannels.forCasus(scope.id);
}

export function useInitiatiefChannels(initiatiefId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.initiatieven.mattermostChannels(initiatiefId),
    queryFn: () => listInitiatiefChannels(initiatiefId!),
    enabled: !!initiatiefId,
  });
}

export function useLeadChannels(leadId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.mattermostChannels.forLead(leadId),
    queryFn: () => listLeadChannels(leadId!),
    enabled: !!leadId,
  });
}

export function useCasusChannels(casusId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.mattermostChannels.forCasus(casusId),
    queryFn: () => listCasusChannels(casusId!),
    enabled: !!casusId,
  });
}

/**
 * Wat Bouwmeester over een casus in het kanaal zette, nieuwste eerst. Staat
 * er een bericht nog op versturen, dan kijkt hij zo weer: de status komt
 * pas na de commit, uit een achtergrondtaak. Niet langer dan een minuut,
 * want een taak die vastliep laat de status op wachten staan.
 */
export function useCasusKanaalberichten(casusId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.mattermostChannels.berichtenForCasus(casusId),
    queryFn: () => listCasusKanaalberichten(casusId!),
    enabled: !!casusId,
    refetchInterval: (query) =>
      query.state.data?.some(
        (b) => b.status === 'wacht' && Date.now() - Date.parse(b.created_at) < 60_000,
      )
        ? 2_000
        : false,
  });
}

export function useSearchMattermostChannels(q: string) {
  return useQuery({
    queryKey: queryKeys.mattermostChannels.search(q),
    queryFn: () => searchMattermostChannels(q),
    enabled: q.length >= 2,
    staleTime: 30_000,
  });
}

export function useCreateInitiatiefChannelLink(initiatiefId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: MattermostChannelLinkCreate) =>
      createInitiatiefChannelLink(initiatiefId!, data),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: queryKeys.initiatieven.mattermostChannels(initiatiefId),
      });
    },
  });
}

export function useCreateLeadChannelLink(leadId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: MattermostChannelLinkCreate) =>
      createLeadChannelLink(leadId!, data),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: queryKeys.mattermostChannels.forLead(leadId),
      });
    },
  });
}

export function useCreateCasusChannelLink(casusId: string | undefined) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: MattermostChannelLinkCreate) =>
      createCasusChannelLink(casusId!, data),
    onSuccess: () => {
      qc.invalidateQueries({
        queryKey: queryKeys.mattermostChannels.forCasus(casusId),
      });
    },
  });
}

export function useUpdateChannelLink(scope: ChannelScope | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      linkId,
      data,
    }: {
      linkId: string;
      data: MattermostChannelLinkUpdate;
    }) => updateChannelLink(linkId, data),
    onSuccess: () => {
      if (scope) qc.invalidateQueries({ queryKey: scopeQueryKey(scope) });
    },
  });
}

export function useDeleteChannelLink(scope: ChannelScope | null) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (linkId: string) => deleteChannelLink(linkId),
    onSuccess: () => {
      if (scope) qc.invalidateQueries({ queryKey: scopeQueryKey(scope) });
    },
  });
}
