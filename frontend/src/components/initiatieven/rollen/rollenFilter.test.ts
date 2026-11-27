import { describe, expect, it } from 'vitest';
import type { InitiatiefRol } from '@/types';
import { filterRollen, isBelegd, isOpen } from './rollenFilter';

function rol(extra: Partial<InitiatiefRol>): InitiatiefRol {
  return {
    id: extra.naam ?? 'id',
    initiatief_id: 'init',
    cirkel_id: 'cirkel',
    naam: 'Rol',
    status: 'concept',
    doel: null,
    aanspreekbaar_op: [],
    domein: [],
    toelichting: null,
    feedback: null,
    vervuller: null,
    vervuller_is_lid: true,
    ronde: 1,
    interesse: [],
    eerdere_interesse: [],
    raakvlakken: [],
    sort_order: 0,
    created_at: '2026-11-27T00:00:00Z',
    updated_at: null,
    ...extra,
  };
}

const ritme = rol({
  naam: 'Aanjager ritme',
  status: 'belegd',
  domein: ['De teamagenda: rituelen en open demo’s'],
  vervuller: { id: 'p1', naam: 'Ünal' },
});
const spel = rol({ naam: 'Spelverdeler', status: 'open', aanspreekbaar_op: ['Teamsamenstelling klopt'] });
const weg = rol({ naam: 'Hoeder', status: 'belegd', vervuller: { id: 'p2', naam: 'Vertrokken' }, vervuller_is_lid: false });
const concept = rol({ naam: 'Inregelaar' });
const alle = [ritme, spel, weg, concept];

describe('isBelegd en isOpen', () => {
  it('telt een vervuller zonder toegang als open, en een concept als geen van beide', () => {
    expect(isBelegd(ritme)).toBe(true);
    expect(isOpen(spel)).toBe(true);
    expect(isOpen(weg)).toBe(true);
    expect(isBelegd(concept) || isOpen(concept)).toBe(false);
  });
});

describe('filterRollen', () => {
  it('zoekt ook in domein en aanspreekbaar op, zonder hoofdletters', () => {
    expect(filterRollen(alle, 'TEAMAGENDA', 'alle', null)).toEqual([ritme]);
    expect(filterRollen(alle, 'teamsamenstelling', 'alle', null)).toEqual([spel]);
  });

  it('zoekt op de naam van de vervuller, ook met accenten', () => {
    expect(filterRollen(alle, 'ünal', 'alle', null)).toEqual([ritme]);
  });

  it('toont bij open de open rollen en die waarvan de vervuller weg is, geen concepten', () => {
    expect(filterRollen(alle, '', 'open', null)).toEqual([spel, weg]);
  });

  it('toont bij van mij alleen wat ik vervul', () => {
    expect(filterRollen(alle, '', 'mijn', 'p1')).toEqual([ritme]);
    expect(filterRollen(alle, '', 'mijn', null)).toEqual([]);
  });

  it('negeert spaties rond de zoekterm', () => {
    expect(filterRollen(alle, '   ', 'alle', null)).toEqual(alle);
  });
});
