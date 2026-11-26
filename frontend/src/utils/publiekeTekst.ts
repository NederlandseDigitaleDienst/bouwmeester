/**
 * Tekst die naar buiten gaat (een vraag of casus voor buiten, een update)
 * mag geen @- of #-verwijzing uit de editor bevatten: `[@Naam](user:id)`
 * noemt een persoon met zijn id, `[#Taak](task:id)` intern werk. De backend
 * weigert hem (`schema/publieke_tekst.py`); het formulier zegt het al tijdens
 * het typen. Markdown laat een spatie en punthaken toe voor het doel van een
 * link, dus die tellen ook.
 */
const VERWIJZING = /\]\(\s*<?\s*(?:user|org|node|task):/i;

export function heeftVerwijzing(...teksten: (string | null | undefined)[]): boolean {
  return teksten.some((t) => !!t && VERWIJZING.test(t));
}

export const VERWIJZING_MELDING =
  'Haal de verwijzingen met @ of # weg. Die noemen een persoon, organisatie of intern werk, en dat gaat niet naar buiten.';
