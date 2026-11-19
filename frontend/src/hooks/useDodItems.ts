import { useCasus } from '@/hooks/useCasussen';
import { useInitiatief } from '@/hooks/useInitiatieven';

/**
 * De Definition of Done die voor een vraag geldt. In een casus geeft de casus
 * hem mee; een vraag zonder casus neemt die van het initiatief, en zolang het
 * initiatief geen eigen punten heeft de standaard. Undefined zolang het
 * nog laadt.
 */
export function useDodItems(casusId: string | null | undefined, initiatiefId: string | null | undefined): string[] | undefined {
  const { data: casus } = useCasus(casusId ?? null);
  const { data: initiatief } = useInitiatief(casusId ? undefined : (initiatiefId ?? undefined));
  if (casusId) return casus?.dod_items;
  if (!initiatief) return undefined;
  return initiatief.dod_items.length ? initiatief.dod_items : (initiatief.dod_standaard ?? []);
}
