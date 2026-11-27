import { ApiError, errorDetail } from '@/api/client';

/** Eén fout uit een 422 van FastAPI: waar (loc), wat (type) en de melding. */
interface Validatiefout {
  loc?: (string | number)[];
  type?: string;
  msg?: string;
}

/**
 * De grenzen van de backend (schema/initiatief.py en schema/wensen.py), voor
 * de teksten hieronder en de controle vóór het opslaan.
 */
export const GRENZEN = {
  toelichting: 5000,
  titel: 300,
  wensen: 200,
  openPunten: 30,
} as const;

/** Waarom de toelichting niet opgeslagen kan worden; ook vóór het versturen. */
export const TOELICHTING_TE_LANG = `De toelichting is te lang. Met de opmaak erbij mag hij ${GRENZEN.toelichting} tekens zijn; maak hem korter.`;

/** De lijst met wensen is vol; ook vóór het versturen. */
export const WENSEN_VOL = `De lijst is vol: er passen ${GRENZEN.wensen} wensen op. Haal er eerst een weg.`;

/**
 * Een tekst bij mislukt opslaan van de instellingen van een initiatief, om in
 * het venster of onder het formulier te tonen. Bij 422 zegt hij welk veld te
 * lang is of welke lijst vol is, in plaats van niets (`errorDetail` kent
 * alleen een `detail` van tekst) of de Engelse melding van Pydantic.
 */
export function opslaanFout(e: unknown): string {
  if (e instanceof ApiError && e.status === 422) return validatieTekst(e.body);
  if (e instanceof ApiError && e.status === 403) return 'Alleen de eigenaar van het initiatief kan dit aanpassen.';
  return errorDetail(e) || 'Opslaan lukte niet. Probeer het opnieuw.';
}

function validatieTekst(body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === 'string' && detail) return detail;
  const fout: Validatiefout | undefined = Array.isArray(detail) ? detail[0] : undefined;
  const loc = fout?.loc ?? [];
  const veld = loc[loc.length - 1];
  const teLang = fout?.type === 'too_long';
  if (veld === 'toelichting') return TOELICHTING_TE_LANG;
  if (veld === 'titel') return `De titel is te lang: hooguit ${GRENZEN.titel} tekens.`;
  if (veld === 'wensen' && teLang) return WENSEN_VOL;
  if (veld === 'open_punten' && teLang) return `Er passen ${GRENZEN.openPunten} open punten op de lijst. Haal er eerst een weg.`;
  // Een eigen controle van de backend (een field_validator) heeft al een
  // Nederlandse melding, na het voorvoegsel van Pydantic.
  if (fout?.type === 'value_error' && fout.msg) {
    const tekst = fout.msg.replace(/^Value error, /, '');
    return /[.!?]$/.test(tekst) ? tekst : `${tekst}.`;
  }
  return 'Opslaan lukte niet: iets in de invoer past niet. Kijk de velden na en probeer het opnieuw.';
}
