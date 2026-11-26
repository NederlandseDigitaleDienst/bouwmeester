import { describe, it, expect } from 'vitest';

import { ApiError } from '@/api/client';
import { TOELICHTING_TE_LANG, WENSEN_VOL, opslaanFout } from './opslaanFout';

const fout422 = (loc: (string | number)[], type: string, msg = 'iets') =>
  new ApiError(422, 'Unprocessable Entity', { detail: [{ loc, type, msg }] });

describe('opslaanFout', () => {
  it('een te lange toelichting van een wens', () => {
    expect(opslaanFout(fout422(['body', 'wensen', 3, 'toelichting'], 'string_too_long'))).toBe(TOELICHTING_TE_LANG);
  });

  it('een volle lijst wensen of open punten', () => {
    expect(opslaanFout(fout422(['body', 'wensen'], 'too_long'))).toBe(WENSEN_VOL);
    expect(opslaanFout(fout422(['body', 'open_punten'], 'too_long'))).toMatch(/30 open punten/);
  });

  it('een te lange titel', () => {
    expect(opslaanFout(fout422(['body', 'wensen', 0, 'titel'], 'string_too_long'))).toMatch(/titel is te lang/);
  });

  it('de eigen melding van de backend, zonder het voorvoegsel van Pydantic', () => {
    const e = fout422(['body', 'open_punten'], 'value_error', 'Value error, Een open punt is maximaal 300 tekens');
    expect(opslaanFout(e)).toBe('Een open punt is maximaal 300 tekens.');
  });

  it('een 422 die we niet kennen krijgt een algemene tekst, geen Engels', () => {
    const e = fout422(['body', 'overleggen', 0, 'naam'], 'string_too_long', 'String should have at most 80 characters');
    expect(opslaanFout(e)).toMatch(/^Opslaan lukte niet/);
    expect(opslaanFout(e)).not.toMatch(/String should/);
  });

  it('403, een detail van tekst, en een fout zonder antwoord', () => {
    expect(opslaanFout(new ApiError(403, 'Forbidden', { detail: 'Onvoldoende rechten' }))).toMatch(/eigenaar/);
    expect(opslaanFout(new ApiError(409, 'Conflict', { detail: 'Er staat een casus in die fase' }))).toBe(
      'Er staat een casus in die fase',
    );
    expect(opslaanFout(new TypeError('Failed to fetch'))).toBe('Opslaan lukte niet. Probeer het opnieuw.');
  });
});
