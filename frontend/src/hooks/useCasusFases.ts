import { useInitiatief } from '@/hooks/useInitiatieven';
import type { CasusFaseDef } from '@/types';

/**
 * De casusfunnel van een initiatief: de fases in volgorde, met naam, kleur,
 * omschrijving en "door als". Uit het initiatief zelf (de eigen funnel of
 * het voorstel); leeg zolang het initiatief laadt.
 */
export function useCasusFases(initiatiefId: string | null | undefined): CasusFaseDef[] {
  const { data } = useInitiatief(initiatiefId ?? undefined);
  return data?.casus_fases ?? [];
}

/** De naam van een fase; de id als de fase (nog) niet bekend is. */
export function faseNaam(fases: CasusFaseDef[], id: string): string {
  return fases.find((f) => f.id === id)?.naam ?? id;
}
