import { describe, expect, it } from 'vitest';
import { cirkelLayout, initialen, labelRegels } from './cirkelLayout';

const R = 300;

function overlapt(a: { x: number; y: number; r: number }, b: { x: number; y: number; r: number }) {
  return Math.hypot(a.x - b.x, a.y - b.y) < a.r + b.r;
}

describe('cirkelLayout', () => {
  it('geeft niets bij geen rollen en één in het midden bij één rol', () => {
    expect(cirkelLayout(0, 0, 0, R)).toEqual([]);
    const [p] = cirkelLayout(1, 10, 20, R);
    expect([p.x, p.y]).toEqual([10, 20]);
  });

  it.each([2, 3, 6, 7, 8, 19, 20, 37])('%i rollen overlappen niet en blijven binnen de cirkel', (n) => {
    const plekken = cirkelLayout(n, 0, 0, R);
    expect(plekken).toHaveLength(n);
    for (const p of plekken) {
      expect(Math.hypot(p.x, p.y) + p.r).toBeLessThanOrEqual(R);
    }
    for (let i = 0; i < plekken.length; i++) {
      for (let j = i + 1; j < plekken.length; j++) {
        expect(overlapt(plekken[i], plekken[j])).toBe(false);
      }
    }
  });

  it('zet de eerste rol bovenaan', () => {
    const [eerste] = cirkelLayout(4, 0, 0, R);
    expect(eerste.x).toBeCloseTo(0);
    expect(eerste.y).toBeLessThan(0);
  });
});

describe('labelRegels', () => {
  it('breekt op woorden', () => {
    expect(labelRegels('Drijvende kracht beleidsvisie', 16)).toEqual(['Drijvende kracht', 'beleidsvisie']);
  });

  it('kort een te lang woord in en houdt het bij drie regels', () => {
    expect(labelRegels('Onwaarschijnlijklangewoordnaam', 10)).toEqual(['Onwaarsch…']);
    const regels = labelRegels('een twee drie vier vijf zes zeven', 4);
    expect(regels).toHaveLength(3);
    expect(regels[2].endsWith('…')).toBe(true);
  });
});

describe('initialen', () => {
  it('neemt de eerste letters van twee woorden', () => {
    expect(initialen('Persoon Dgdoo')).toBe('PD');
    expect(initialen('ünal')).toBe('Ü');
  });
});
