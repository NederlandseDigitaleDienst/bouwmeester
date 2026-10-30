import { describe, it, expect, vi, beforeAll } from 'vitest';
import { act, render } from '@testing-library/react';
import { Select } from './Select';

/**
 * Tegen de échte `nldd-dropdown`, want het gedrag zit in die component en een
 * stub zou het wegpoetsen.
 *
 * Tot design system 0.8.92 tekende de dropdown zijn label zelf, in een span
 * die een programmatisch gezette waarde niet volgde. Sinds 0.13 toont hij de
 * echte `<select>`, dus wat je leest is de geselecteerde optie zelf. Deze
 * tests houden vast dat een waarde van buitenaf daar landt, en dat alleen een
 * keuze van de gebruiker `onChange` aanroept.
 */
beforeAll(async () => {
  // jsdom kent `CSS.supports` niet; de dropdown vraagt het op zodra hij een
  // `width` krijgt. Zonder dit gooit hij een onafgevangen fout.
  const g = globalThis as unknown as { CSS?: { supports?: unknown } };
  if (typeof g.CSS?.supports !== 'function') g.CSS = { ...(g.CSS ?? {}), supports: () => false };
  await import('@nldd/design-system/dropdown');
});

const DREMPELS = [
  { value: '0', label: 'Alles tonen' },
  { value: '20', label: 'Normaal' },
  { value: '40', label: 'Alleen relevante' },
];

const label = (container: HTMLElement) =>
  container.querySelector('select')?.selectedOptions[0]?.textContent ?? '';

describe('Select', () => {
  it('werkt het zichtbare label bij als de waarde van buitenaf verandert', async () => {
    const { container, rerender } = render(
      <Select value="0" onChange={vi.fn()} options={DREMPELS} aria-label="Drempel" />,
    );

    await act(async () => {
      rerender(<Select value="20" onChange={vi.fn()} options={DREMPELS} aria-label="Drempel" />);
    });

    expect(container.querySelector('select')!.value).toBe('20');
    expect(label(container)).toBe('Normaal');
  });

  it('schrijft niets weg bij een waarde van buitenaf', async () => {
    // Een waarde die de app zelf zet is geen keuze van de gebruiker, dus
    // `onChange` blijft stil en er wordt niets weggeschreven.
    const onChange = vi.fn();
    const { rerender } = render(
      <Select value="0" onChange={onChange} options={DREMPELS} aria-label="Drempel" />,
    );

    await act(async () => {
      rerender(<Select value="20" onChange={onChange} options={DREMPELS} aria-label="Drempel" />);
    });

    expect(onChange).not.toHaveBeenCalled();
  });

  it('meldt een keuze van de gebruiker wel', async () => {
    const onChange = vi.fn();
    const { container } = render(
      <Select value="20" onChange={onChange} options={DREMPELS} aria-label="Drempel" />,
    );

    const select = container.querySelector('select')!;
    await act(async () => {
      select.value = '40';
      select.dispatchEvent(new Event('change', { bubbles: true }));
    });

    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange.mock.calls[0][0].target.value).toBe('40');
  });

  it('compact: veld zo breed als de keuzelijst en zonder "Optioneel"', () => {
    const { container } = render(
      <Select compact label="Status" width="150px" value="0" onChange={vi.fn()} options={DREMPELS} />,
    );
    const veld = container.querySelector('nldd-form-field') as HTMLElement;
    expect(veld.hasAttribute('optional')).toBe(false);
    expect(veld.style.width).toBe('150px');
  });

  it('zonder compact blijft een veld met label optioneel en volle breedte', () => {
    const { container } = render(
      <Select label="Status" width="150px" value="0" onChange={vi.fn()} options={DREMPELS} />,
    );
    const veld = container.querySelector('nldd-form-field') as HTMLElement;
    expect(veld.hasAttribute('optional')).toBe(true);
    expect(veld.style.width).toBe('');
  });
});
