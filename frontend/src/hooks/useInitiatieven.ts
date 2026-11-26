import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import {
  getInitiatiefPersonen,
  getInitiatieven,
  getInitiatief,
  createInitiatief,
  updateInitiatief,
  updateInitiatiefSettings,
  addInitiatiefMember,
  removeInitiatiefMember,
  updateInitiatiefMemberRole,
  addInitiatiefEenheid,
  removeInitiatiefEenheid,
  updateInitiatiefEenheidRol,
  getInitiatievenForEenheid,
  getInitiatiefUpdates,
  createInitiatiefUpdate,
  editInitiatiefUpdate,
  publishInitiatiefUpdate,
  unpublishInitiatiefUpdate,
  deleteInitiatiefUpdate,
  getVrijgegevenVragen,
  getKlaarOmTeDelen,
} from '@/api/initiatieven';
import { queryKeys } from '@/hooks/queryKeys';
import type {
  InitiatiefCreate,
  InitiatiefSettingsUpdate,
  InitiatiefUpdate,
  InitiatiefUpdatePostCreate,
  InitiatiefUpdatePostEdit,
} from '@/types';

export function useInitiatieven(params?: { search?: string }) {
  return useQuery({
    queryKey: queryKeys.initiatieven.list(params),
    queryFn: () => getInitiatieven(params),
  });
}

export function useInitiatief(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.initiatieven.detail(id),
    queryFn: () => getInitiatief(id!),
    enabled: !!id,
  });
}

/**
 * Mag de ingelogde persoon iets van dit initiatief naar buiten brengen? Een
 * bijdrager of eigenaar, dezelfde regel als `require_can_publish_issue` in de
 * backend. Zolang het initiatief laadt: nee.
 */
export function useKanVrijgeven(initiatiefId: string | null | undefined): boolean {
  const { data } = useInitiatief(initiatiefId ?? undefined);
  return data?.access_level === 'eigenaar' || data?.access_level === 'contributor';
}

/** Wie het initiatief kan zien: de kandidaten voor een casusteam. */
export function useInitiatiefPersonen(id: string | undefined) {
  return useQuery({
    queryKey: queryKeys.initiatieven.personen(id),
    queryFn: () => getInitiatiefPersonen(id!),
    enabled: !!id,
  });
}

export function useCreateInitiatief() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (data: InitiatiefCreate) => createInitiatief(data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.initiatieven.all });
    },
  });
}

export function useUpdateInitiatief() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: InitiatiefUpdate }) =>
      updateInitiatief(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.initiatieven.all });
    },
  });
}

export function useAddInitiatiefMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      initiatiefId,
      personId,
      rol,
    }: {
      initiatiefId: string;
      personId: string;
      rol?: string;
    }) => addInitiatiefMember(initiatiefId, personId, rol),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.initiatieven.all });
    },
  });
}

export function useRemoveInitiatiefMember() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      initiatiefId,
      personId,
    }: {
      initiatiefId: string;
      personId: string;
    }) => removeInitiatiefMember(initiatiefId, personId),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.initiatieven.all });
    },
  });
}

export function useUpdateInitiatiefMemberRole() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      initiatiefId,
      personId,
      rol,
    }: {
      initiatiefId: string;
      personId: string;
      rol: string;
    }) => updateInitiatiefMemberRole(initiatiefId, personId, rol),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.initiatieven.all });
    },
  });
}

export function useAddInitiatiefEenheid() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      initiatiefId,
      eenheidId,
    }: {
      initiatiefId: string;
      eenheidId: string;
    }) => addInitiatiefEenheid(initiatiefId, eenheidId),
    onSuccess: (_data, { eenheidId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.initiatieven.all });
      qc.invalidateQueries({ queryKey: ['initiatieven-for-eenheid', eenheidId] });
    },
  });
}

export function useRemoveInitiatiefEenheid() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      initiatiefId,
      eenheidId,
    }: {
      initiatiefId: string;
      eenheidId: string;
    }) => removeInitiatiefEenheid(initiatiefId, eenheidId),
    onSuccess: (_data, { eenheidId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.initiatieven.all });
      qc.invalidateQueries({ queryKey: ['initiatieven-for-eenheid', eenheidId] });
    },
  });
}

export function useUpdateInitiatiefEenheidRol() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      initiatiefId,
      eenheidId,
      rol,
    }: {
      initiatiefId: string;
      eenheidId: string;
      rol: string;
    }) => updateInitiatiefEenheidRol(initiatiefId, eenheidId, rol),
    onSuccess: (_data, { eenheidId }) => {
      qc.invalidateQueries({ queryKey: queryKeys.initiatieven.all });
      qc.invalidateQueries({ queryKey: ['initiatieven-for-eenheid', eenheidId] });
    },
  });
}

export function useInitiatievenForEenheid(eenheidId: string | null) {
  return useQuery({
    queryKey: ['initiatieven-for-eenheid', eenheidId],
    queryFn: () => getInitiatievenForEenheid(eenheidId!),
    enabled: !!eenheidId,
  });
}

export function useUpdateInitiatiefSettings() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: InitiatiefSettingsUpdate }) =>
      updateInitiatiefSettings(id, data),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: queryKeys.initiatieven.all });
      // Een andere laatste fase trekt vrijgegeven casussen in.
      qc.invalidateQueries({ queryKey: ['klaar-om-te-delen'] });
      qc.invalidateQueries({ queryKey: ['initiatief-updates'] });
    },
  });
}

// ---------------------------------------------------------------------------
// InitiatiefUpdatePost hooks
// ---------------------------------------------------------------------------

const initiatiefUpdatesKey = (initiatiefId: string | undefined) =>
  ['initiatief-updates', initiatiefId] as const;

const vrijgegevenVragenKey = (initiatiefId: string | undefined) =>
  ['vrijgegeven-vragen', initiatiefId] as const;

const klaarKey = (initiatiefId: string | undefined) => ['klaar-om-te-delen', initiatiefId] as const;

/** Afgeronde onderzoeksvragen en casussen: waar een update op voortbouwt. */
export function useKlaarOmTeDelen(initiatiefId: string | undefined) {
  return useQuery({
    queryKey: klaarKey(initiatiefId),
    queryFn: () => getKlaarOmTeDelen(initiatiefId!),
    enabled: !!initiatiefId,
  });
}

/** De beantwoorde onderzoeksvragen die een update kan meenemen, nieuwste eerst. */
export function useVrijgegevenVragen(initiatiefId: string | undefined) {
  return useQuery({
    queryKey: vrijgegevenVragenKey(initiatiefId),
    queryFn: () => getVrijgegevenVragen(initiatiefId!),
    enabled: !!initiatiefId,
  });
}

export function useInitiatiefUpdates(initiatiefId: string | undefined) {
  return useQuery({
    queryKey: initiatiefUpdatesKey(initiatiefId),
    queryFn: () => getInitiatiefUpdates(initiatiefId!),
    enabled: !!initiatiefId,
  });
}

export function useCreateInitiatiefUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      initiatiefId,
      data,
    }: {
      initiatiefId: string;
      data: InitiatiefUpdatePostCreate;
    }) => createInitiatiefUpdate(initiatiefId, data),
    onSuccess: (_data, { initiatiefId }) => {
      qc.invalidateQueries({ queryKey: initiatiefUpdatesKey(initiatiefId) });
      qc.invalidateQueries({ queryKey: vrijgegevenVragenKey(initiatiefId) });
      qc.invalidateQueries({ queryKey: klaarKey(initiatiefId) });
    },
  });
}

export function useEditInitiatiefUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      initiatiefId,
      postId,
      data,
    }: {
      initiatiefId: string;
      postId: string;
      data: InitiatiefUpdatePostEdit;
    }) => editInitiatiefUpdate(initiatiefId, postId, data),
    onSuccess: (_data, { initiatiefId }) => {
      qc.invalidateQueries({ queryKey: initiatiefUpdatesKey(initiatiefId) });
      qc.invalidateQueries({ queryKey: vrijgegevenVragenKey(initiatiefId) });
      qc.invalidateQueries({ queryKey: klaarKey(initiatiefId) });
    },
  });
}

export function usePublishInitiatiefUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      initiatiefId,
      postId,
    }: {
      initiatiefId: string;
      postId: string;
    }) => publishInitiatiefUpdate(initiatiefId, postId),
    onSuccess: (_data, { initiatiefId }) => {
      qc.invalidateQueries({ queryKey: initiatiefUpdatesKey(initiatiefId) });
      qc.invalidateQueries({ queryKey: vrijgegevenVragenKey(initiatiefId) });
      qc.invalidateQueries({ queryKey: klaarKey(initiatiefId) });
    },
  });
}

export function useUnpublishInitiatiefUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      initiatiefId,
      postId,
    }: {
      initiatiefId: string;
      postId: string;
    }) => unpublishInitiatiefUpdate(initiatiefId, postId),
    onSuccess: (_data, { initiatiefId }) => {
      qc.invalidateQueries({ queryKey: initiatiefUpdatesKey(initiatiefId) });
      qc.invalidateQueries({ queryKey: vrijgegevenVragenKey(initiatiefId) });
      qc.invalidateQueries({ queryKey: klaarKey(initiatiefId) });
    },
  });
}

export function useDeleteInitiatiefUpdate() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({
      initiatiefId,
      postId,
    }: {
      initiatiefId: string;
      postId: string;
    }) => deleteInitiatiefUpdate(initiatiefId, postId),
    onSuccess: (_data, { initiatiefId }) => {
      qc.invalidateQueries({ queryKey: initiatiefUpdatesKey(initiatiefId) });
      qc.invalidateQueries({ queryKey: vrijgegevenVragenKey(initiatiefId) });
      qc.invalidateQueries({ queryKey: klaarKey(initiatiefId) });
    },
  });
}
