import { CASUS_TYPE_LABELS, type Startvoorwaarden, type Startvraag } from '@/types';

/**
 * Hulp bij de startvragen. De vragen zelf staan per initiatief in de
 * instellingen (backend schema/startvragen.py); de API geeft altijd de lijst
 * die geldt, de eigen of de standaardlijst. De vraag naar intern of satelliet
 * is vast: zijn antwoord staat in startvoorwaarden.casustype en bepaalt of de
 * acceptatiecriteria volgen. De andere antwoorden staan in
 * startvoorwaarden.antwoorden.
 */

export const CASUSTYPE_ID = 'casustype';

/** De vaste vraag; ook de enige bij een lead zonder initiatief. */
export const VASTE_VRAAG: Startvraag = {
  id: CASUSTYPE_ID,
  vraag: 'Is het een interne casus of een satellietcasus?',
  antwoordtype: 'een_keuze',
  opties: [CASUS_TYPE_LABELS.intern, CASUS_TYPE_LABELS.satelliet],
  verplicht: true,
  op_kaartje: true,
};

export type Waarde = boolean | string | string[] | null | undefined;

export function isBeantwoord(waarde: Waarde): boolean {
  if (waarde === undefined || waarde === null) return false;
  if (typeof waarde === 'string') return waarde.trim() !== '';
  if (Array.isArray(waarde)) return waarde.length > 0;
  return true;
}

/** Een antwoord als tekst: Ja of Nee, de keuze, of de keuzes achter elkaar. */
export function antwoordTekst(waarde: Waarde): string {
  if (typeof waarde === 'boolean') return waarde ? 'Ja' : 'Nee';
  if (Array.isArray(waarde)) return waarde.join(', ');
  return waarde ?? '';
}

/**
 * Wat er op het casuskaartje komt: de antwoorden op de vragen met "op het
 * kaartje". Bij meer keuzes de eerste twee en een teller, zodat het kaartje
 * niet volloopt; bij ja/nee de vraag erbij, anders zegt "ja" niets.
 */
export function kaartjeLabels(sv: Partial<Startvoorwaarden> | undefined, vragen: Startvraag[]): string[] {
  const uit: string[] = [];
  for (const v of vragen) {
    if (!v.op_kaartje) continue;
    if (v.id === CASUSTYPE_ID) {
      if (sv?.casustype) uit.push(CASUS_TYPE_LABELS[sv.casustype] ?? sv.casustype);
      continue;
    }
    const waarde = sv?.antwoorden?.find((a) => a.vraag_id === v.id)?.waarde;
    if (!isBeantwoord(waarde)) continue;
    if (typeof waarde === 'boolean') {
      uit.push(`${v.vraag.replace(/\?\s*$/, '')}: ${waarde ? 'ja' : 'nee'}`);
    } else if (Array.isArray(waarde)) {
      uit.push(...waarde.slice(0, 2));
      if (waarde.length > 2) uit.push(`+${waarde.length - 2}`);
    } else if (waarde) {
      uit.push(waarde);
    }
  }
  return uit;
}
