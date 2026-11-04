import { useQuery } from '@tanstack/react-query';

import {
  createCasusSoort,
  deleteCasusSoort,
  getCasusSoorten,
  reorderCasusSoorten,
  updateCasusSoort,
  zetCasusSoorten,
} from '@/api/casusSoorten';
import { queryKeys } from '@/hooks/queryKeys';
import { useMutationWithError } from '@/hooks/useMutationWithError';

// Een soort hernoemen of verwijderen verandert wat op elke casus staat: de
// casuslijsten en -details dus ook verversen.
const KEYS = [queryKeys.casusSoorten.all, queryKeys.casussen.all];

/** De casussoorten van een initiatief, in de volgorde van de instellingen. */
export function useCasusSoorten(initiatiefId: string | null | undefined) {
  return useQuery({
    queryKey: queryKeys.casusSoorten.list(initiatiefId ?? null),
    queryFn: () => getCasusSoorten(initiatiefId!),
    enabled: !!initiatiefId,
  });
}

export function useCreateCasusSoort() {
  return useMutationWithError({
    mutationFn: ({
      initiatiefId,
      naam,
      kleur,
      uitleg,
    }: {
      initiatiefId: string;
      naam: string;
      kleur?: string;
      uitleg?: string | null;
    }) => createCasusSoort(initiatiefId, { naam, kleur, uitleg }),
    errorMessage: 'Fout bij toevoegen soort',
    invalidateKeys: KEYS,
  });
}

export function useUpdateCasusSoort() {
  return useMutationWithError({
    mutationFn: ({
      initiatiefId,
      soortId,
      data,
    }: {
      initiatiefId: string;
      soortId: string;
      data: { naam?: string; kleur?: string; uitleg?: string | null; hoe_ver?: string | null; start_eisen?: string[]; eind_eisen?: string[] };
    }) => updateCasusSoort(initiatiefId, soortId, data),
    errorMessage: 'Fout bij bijwerken soort',
    invalidateKeys: KEYS,
  });
}

export function useDeleteCasusSoort() {
  return useMutationWithError({
    mutationFn: ({ initiatiefId, soortId }: { initiatiefId: string; soortId: string }) =>
      deleteCasusSoort(initiatiefId, soortId),
    errorMessage: 'Fout bij verwijderen soort',
    invalidateKeys: KEYS,
  });
}

export function useReorderCasusSoorten() {
  return useMutationWithError({
    mutationFn: ({ initiatiefId, soortIds }: { initiatiefId: string; soortIds: string[] }) =>
      reorderCasusSoorten(initiatiefId, soortIds),
    errorMessage: 'Fout bij volgorde soorten',
    invalidateKeys: KEYS,
  });
}

/** De soorten van één casus als geheel zetten. */
export function useZetCasusSoorten() {
  return useMutationWithError({
    mutationFn: ({ casusId, soortIds }: { casusId: string; soortIds: string[] }) => zetCasusSoorten(casusId, soortIds),
    errorMessage: 'Fout bij soorten van de casus',
    invalidateKeys: KEYS,
  });
}
