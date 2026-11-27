import { useQuery } from '@tanstack/react-query';

import {
  createRol,
  deleteRol,
  getCirkel,
  getPersoonWerk,
  getRollen,
  importRollen,
  maakRaakvlak,
  updateCirkel,
  updateRol,
  verwijderInteresse,
  verwijderRaakvlak,
  zetInteresse,
  zetPersoonFocus,
} from '@/api/initiatiefRollen';
import { queryKeys } from '@/hooks/queryKeys';
import { useMutationWithError } from '@/hooks/useMutationWithError';
import type { InitiatiefRolInput } from '@/types';

// Het id komt uit de URL en gaat in een API-pad.
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Een rol wijzigen verandert ook het werk per persoon en de cirkel.
const KEYS = [queryKeys.initiatiefRollen.all];

export function useInitiatiefRollen(initiatiefId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.initiatiefRollen.list(initiatiefId),
    queryFn: () => getRollen(initiatiefId),
    enabled,
  });
}

export function useInitiatiefCirkel(initiatiefId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.initiatiefRollen.cirkel(initiatiefId),
    queryFn: () => getCirkel(initiatiefId),
    enabled,
  });
}

export function usePersoonWerk(initiatiefId: string, personId: string | null) {
  return useQuery({
    queryKey: queryKeys.initiatiefRollen.werk(initiatiefId, personId ?? ''),
    queryFn: () => getPersoonWerk(initiatiefId, personId!),
    enabled: !!personId && UUID_RE.test(personId),
  });
}

export function useCreateRol() {
  return useMutationWithError({
    mutationFn: ({ initiatiefId, data }: { initiatiefId: string; data: InitiatiefRolInput & { naam: string } }) =>
      createRol(initiatiefId, data),
    errorMessage: 'Fout bij toevoegen rol',
    invalidateKeys: KEYS,
  });
}

export function useUpdateRol() {
  return useMutationWithError({
    mutationFn: ({ initiatiefId, rolId, data }: { initiatiefId: string; rolId: string; data: InitiatiefRolInput }) =>
      updateRol(initiatiefId, rolId, data),
    errorMessage: 'Fout bij bijwerken rol',
    invalidateKeys: KEYS,
  });
}

export function useDeleteRol() {
  return useMutationWithError({
    mutationFn: ({ initiatiefId, rolId }: { initiatiefId: string; rolId: string }) => deleteRol(initiatiefId, rolId),
    errorMessage: 'Fout bij verwijderen rol',
    invalidateKeys: KEYS,
  });
}

export function useZetInteresse() {
  return useMutationWithError({
    mutationFn: ({
      initiatiefId,
      rolId,
      personId,
      invulling,
    }: {
      initiatiefId: string;
      rolId: string;
      personId: string;
      invulling: string | null;
    }) => zetInteresse(initiatiefId, rolId, personId, invulling),
    errorMessage: 'Fout bij vastleggen interesse',
    invalidateKeys: KEYS,
  });
}

export function useVerwijderInteresse() {
  return useMutationWithError({
    mutationFn: ({ initiatiefId, rolId, personId }: { initiatiefId: string; rolId: string; personId: string }) =>
      verwijderInteresse(initiatiefId, rolId, personId),
    errorMessage: 'Fout bij weghalen interesse',
    invalidateKeys: KEYS,
  });
}

export function useMaakRaakvlak() {
  return useMutationWithError({
    mutationFn: ({
      initiatiefId,
      rolId,
      anderRolId,
      omschrijving,
    }: {
      initiatiefId: string;
      rolId: string;
      anderRolId: string;
      omschrijving: string | null;
    }) => maakRaakvlak(initiatiefId, rolId, anderRolId, omschrijving),
    errorMessage: 'Fout bij toevoegen raakvlak',
    invalidateKeys: KEYS,
  });
}

export function useVerwijderRaakvlak() {
  return useMutationWithError({
    mutationFn: ({ initiatiefId, raakvlakId }: { initiatiefId: string; raakvlakId: string }) =>
      verwijderRaakvlak(initiatiefId, raakvlakId),
    errorMessage: 'Fout bij weghalen raakvlak',
    invalidateKeys: KEYS,
  });
}

export function useUpdateCirkel() {
  return useMutationWithError({
    mutationFn: ({ initiatiefId, data }: { initiatiefId: string; data: { doel?: string | null; focus?: string[] } }) =>
      updateCirkel(initiatiefId, data),
    errorMessage: 'Fout bij bijwerken cirkel',
    invalidateKeys: KEYS,
  });
}

export function useZetPersoonFocus() {
  return useMutationWithError({
    mutationFn: ({ initiatiefId, personId, focus }: { initiatiefId: string; personId: string; focus: string[] }) =>
      zetPersoonFocus(initiatiefId, personId, focus),
    errorMessage: 'Fout bij opslaan focus',
    invalidateKeys: KEYS,
  });
}

export function useImportRollen() {
  return useMutationWithError({
    mutationFn: ({ initiatiefId, data }: { initiatiefId: string; data: unknown }) => importRollen(initiatiefId, data),
    errorMessage: 'Importeren mislukt',
    invalidateKeys: KEYS,
  });
}
