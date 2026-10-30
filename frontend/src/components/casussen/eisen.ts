import type { CasusSoortSummary, SoortEis } from '@/types';

export type Lijst = 'start_eisen' | 'eind_eisen';

/** Per eis: afgevinkt of niet, met een opmerking. De sleutel is soort en eis samen. */
export type EisWaarden = Record<string, { akkoord: boolean; opmerking: string }>;

export const sleutel = (soortId: string, eis: string) => `${soortId}\n${eis}`;

/** Of een van deze soorten eisen heeft in deze lijst. */
export function heeftEisen(soorten: CasusSoortSummary[], lijst: Lijst): boolean {
  return soorten.some((s) => (s[lijst] ?? []).length > 0);
}

/**
 * Alle eisen van de soorten met wat er is ingevuld, zoals de server ze wil.
 * Een eis zonder vinkje gaat mee als niet akkoord: de lijst is geen poort.
 */
export function naarSoortEisen(soorten: CasusSoortSummary[], lijst: Lijst, waarden: EisWaarden): SoortEis[] {
  return soorten.flatMap((s) =>
    (s[lijst] ?? []).map((eis) => {
      const w = waarden[sleutel(s.id, eis)];
      return { soort_id: s.id, eis, akkoord: !!w?.akkoord, opmerking: w?.opmerking.trim() || null };
    }),
  );
}

/** Beginwaarden uit een eerdere momentopname: wie opnieuw afrondt, ziet wat er stond. */
export function uitMomentopname(eisen: SoortEis[] | undefined): EisWaarden {
  return Object.fromEntries(
    (eisen ?? []).map((e) => [sleutel(e.soort_id, e.eis), { akkoord: e.akkoord, opmerking: e.opmerking ?? '' }]),
  );
}

/** Eén eis bijwerken in een EisWaarden-state. */
export function zetEis(waarden: EisWaarden, k: string, deel: Partial<{ akkoord: boolean; opmerking: string }>): EisWaarden {
  return { ...waarden, [k]: { ...(waarden[k] ?? { akkoord: false, opmerking: '' }), ...deel } };
}
