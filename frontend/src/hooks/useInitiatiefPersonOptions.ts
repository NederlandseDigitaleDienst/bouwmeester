import { createContext, useContext, useMemo } from 'react';

import { useInitiatiefPersonen } from '@/hooks/useInitiatieven';
import { usePeople } from '@/hooks/usePeople';

/**
 * Het initiatief waar een casus- of backlogweergave onder valt. De
 * taaklijsten zitten diep in de boom; via deze context weten ze welk team
 * kiesbaar is zonder dat elke laag een prop doorgeeft.
 */
export const InitiatiefIdContext = createContext<string | null>(null);

export interface PersoonOptie {
  value: string;
  label: string;
}

/**
 * De keuzelijst "wie doet dit" op een casustaak: alleen wie het initiatief
 * kan zien. Dat is dezelfde regel als voor trekker en teamlid, en de backend
 * weigert anderen ook (400). Zonder initiatief (hoort niet voor te komen)
 * valt de lijst terug op alle actieve personen.
 *
 * Staat er nog iemand op de taak die geen lid meer is, dan blijft die
 * zichtbaar als "(geen lid meer)", zodat de keuze niet stil verspringt.
 */
export function useInitiatiefPersonOptions(
  huidige?: { id: string; naam: string } | null,
  /** Expliciet initiatief, voor een weergave buiten de casus- of backlogtab. */
  expliciet?: string | null,
): PersoonOptie[] {
  const uitContext = useContext(InitiatiefIdContext);
  const initiatiefId = expliciet ?? uitContext;
  const { data: leden } = useInitiatiefPersonen(initiatiefId ?? undefined);
  const { data: iedereen } = usePeople();

  return useMemo(() => {
    const basis = initiatiefId ? (leden ?? []) : (iedereen ?? []).filter((p) => p.is_active);
    const opties: PersoonOptie[] = [
      { value: '', label: 'Niemand' },
      ...basis.filter((p) => !p.is_agent).map((p) => ({ value: p.id, label: p.naam })),
    ];
    if (huidige && !opties.some((o) => o.value === huidige.id)) {
      // Pas "geen lid meer" zeggen als de lijst er is: tijdens het laden is
      // iedereen nog geen lid, en dan flitst dat achter elke naam.
      const geladen = initiatiefId ? leden !== undefined : iedereen !== undefined;
      opties.push({ value: huidige.id, label: geladen ? `${huidige.naam} (geen lid meer)` : huidige.naam });
    }
    return opties;
  }, [initiatiefId, leden, iedereen, huidige]);
}
