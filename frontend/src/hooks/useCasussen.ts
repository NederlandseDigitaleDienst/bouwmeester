import { useQuery } from '@tanstack/react-query';
import {
  getCasussen,
  getCasus,
  startCasus,
  updateCasus,
  deleteCasus,
  addCasusTeamlid,
  removeCasusTeamlid,
  getBacklog,
  zetInKoelkast,
  haalUitKoelkast,
  publishCasus,
  unpublishCasus,
} from '@/api/casussen';
import { useMutationWithError } from '@/hooks/useMutationWithError';
import { queryKeys } from '@/hooks/queryKeys';
import type { CasusKoelkast, CasusPubliek, CasusStart, CasusUpdate } from '@/types';

export function useCasussen(initiatiefId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.casussen.list(initiatiefId),
    queryFn: () => getCasussen(initiatiefId),
  });
}

/** De sleutel staat onder tasks.list, zodat elke taakmutatie de backlog ververst. */
export function useBacklog(initiatiefId: string | null) {
  return useQuery({
    queryKey: queryKeys.tasks.backlog(initiatiefId),
    queryFn: () => getBacklog(initiatiefId!),
    enabled: !!initiatiefId,
  });
}

export function useCasus(id: string | null) {
  return useQuery({
    queryKey: queryKeys.casussen.detail(id),
    queryFn: () => getCasus(id!),
    enabled: !!id,
  });
}

/** Start een casus vanuit een lead. De lead wordt daarna alleen-lezen, dus die ververst mee. */
export function useStartCasus() {
  return useMutationWithError({
    mutationFn: (data: CasusStart) => startCasus(data),
    errorMessage: 'Fout bij starten casus',
    invalidateKeys: [queryKeys.casussen.all, queryKeys.leads.all],
  });
}

// Een casus die naar buiten gaat, terugkomt of van fase wisselt, verandert
// ook wat de tab Updates en de publieke pagina tonen.
const BUITEN_KEYS = [['klaar-om-te-delen'], ['initiatief-updates']];

export function useUpdateCasus() {
  return useMutationWithError({
    mutationFn: ({ id, data }: { id: string; data: CasusUpdate }) => updateCasus(id, data),
    errorMessage: 'Fout bij bijwerken casus',
    invalidateKeys: [queryKeys.casussen.all, ...BUITEN_KEYS],
  });
}

export function usePublishCasus() {
  return useMutationWithError({
    mutationFn: ({ id, data }: { id: string; data: CasusPubliek }) => publishCasus(id, data),
    errorMessage: 'Fout bij vrijgeven casus',
    invalidateKeys: [queryKeys.casussen.all, ...BUITEN_KEYS],
  });
}

export function useUnpublishCasus() {
  return useMutationWithError({
    mutationFn: ({ id }: { id: string }) => unpublishCasus(id),
    errorMessage: 'Fout bij intrekken casus',
    invalidateKeys: [queryKeys.casussen.all, ...BUITEN_KEYS],
  });
}

export function useZetInKoelkast() {
  return useMutationWithError({
    mutationFn: ({ id, data }: { id: string; data: CasusKoelkast }) => zetInKoelkast(id, data),
    errorMessage: 'Fout bij in de koelkast zetten',
    invalidateKeys: [queryKeys.casussen.all],
  });
}

export function useHaalUitKoelkast() {
  return useMutationWithError({
    mutationFn: (id: string) => haalUitKoelkast(id),
    errorMessage: 'Fout bij uit de koelkast halen',
    invalidateKeys: [queryKeys.casussen.all],
  });
}

export function useDeleteCasus() {
  return useMutationWithError({
    mutationFn: (id: string) => deleteCasus(id),
    errorMessage: 'Fout bij verwijderen casus',
    invalidateKeys: [queryKeys.casussen.all, queryKeys.leads.all],
  });
}

export function useAddCasusTeamlid() {
  return useMutationWithError({
    mutationFn: ({
      casusId,
      personId,
      rol,
    }: {
      casusId: string;
      personId: string;
      rol: 'trekker' | 'teamlid';
    }) => addCasusTeamlid(casusId, personId, rol),
    errorMessage: 'Fout bij toevoegen teamlid',
    invalidateKeys: [queryKeys.casussen.all],
  });
}

export function useRemoveCasusTeamlid() {
  return useMutationWithError({
    mutationFn: ({ casusId, rpId }: { casusId: string; rpId: string }) =>
      removeCasusTeamlid(casusId, rpId),
    errorMessage: 'Fout bij verwijderen teamlid',
    invalidateKeys: [queryKeys.casussen.all],
  });
}
