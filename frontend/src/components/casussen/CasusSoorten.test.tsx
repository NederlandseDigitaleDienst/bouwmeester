import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';

import type { CasusSoort } from '@/types';
import { CasusSoortenKiezer, CasusSoortTags } from './CasusSoorten';

const soort = (id: string, naam: string, uitleg: string | null = null): CasusSoort => ({
  id,
  naam,
  kleur: 'neutral',
  uitleg,
  initiatief_id: 'i1',
  sort_order: 0,
  casus_count: 0,
  created_at: '2026-10-29T00:00:00Z',
});

describe('CasusSoortenKiezer', () => {
  it('toont de uitleg onder het vinkje, gekoppeld als beschrijving', () => {
    render(
      <CasusSoortenKiezer
        soorten={[soort('a', 'Experiment', 'We proberen iets nieuws uit om ervan te leren.'), soort('b', 'Productie')]}
        gekozen={[]}
        onChange={vi.fn()}
      />,
    );
    const uitleg = screen.getByText('We proberen iets nieuws uit om ervan te leren.');
    const vinkje = document.querySelector('nldd-checkbox-field[label="Experiment"]') as HTMLElement & {
      describedByElements?: readonly Element[];
    };
    expect(vinkje.describedByElements).toEqual([uitleg]);
    // Een soort zonder uitleg heeft geen tekst eronder.
    const zonder = document.querySelector('nldd-checkbox-field[label="Productie"]') as HTMLElement & {
      describedByElements?: readonly Element[];
    };
    expect(zonder.describedByElements ?? []).toEqual([]);
  });

  it('zonder soorten een verwijzing naar de instellingen', () => {
    render(<CasusSoortenKiezer soorten={[]} gekozen={[]} onChange={vi.fn()} />);
    expect(screen.getByText(/bij de instellingen van het initiatief/)).toBeTruthy();
  });
});

describe('CasusSoortTags', () => {
  it('zet de uitleg als tooltip op het label', () => {
    const { container } = render(<CasusSoortTags soorten={[soort('a', 'Simulatie', 'We rekenen beleidskeuzes door.')]} />);
    const tag = container.querySelector('nldd-tag')!;
    expect(tag.getAttribute('text')).toBe('Simulatie');
    expect(tag.getAttribute('title')).toBe('We rekenen beleidskeuzes door.');
  });
});
