import { afterEach, describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';
import { NlddButton } from './NlddButton';

/**
 * jsdom does not upgrade custom elements, so there is no real <button> in the
 * shadow root to query by role and no click behaviour to drive with
 * userEvent. These therefore assert what this wrapper is responsible for: the
 * right element, the right attributes, and a click listener bound on the host.
 * Whether the element renders an accessible button is the design system's test.
 */
describe('NlddButton', () => {
  const button = (container: HTMLElement) => container.querySelector('nldd-button');

  it('passes the label as the text attribute', () => {
    const { container } = render(<NlddButton text="Opslaan" />);
    expect(button(container)).toHaveAttribute('text', 'Opslaan');
  });

  it('calls onClick when the element emits a click', () => {
    const onClick = vi.fn();
    const { container } = render(<NlddButton text="Klik" onClick={onClick} />);

    // The real click originates inside the element's shadow root; dispatching on
    // the host is the closest jsdom equivalent.
    button(container)?.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    expect(onClick).toHaveBeenCalledOnce();
  });

  it('passes the states through', () => {
    // The element keeps its width while loading and blocks activation itself,
    // so loading does not also need `disabled`: that drops it from the tab order.
    const { container } = render(<NlddButton text="Laden" loading disabled singleLine />);
    expect(button(container)).toHaveAttribute('loading');
    expect(button(container)).toHaveAttribute('disabled');
    expect(button(container)).toHaveAttribute('single-line');
  });

  it('passes icons, variant and size through', () => {
    const { container } = render(
      <NlddButton text="Verwijderen" startIcon="trash" variant="destructive" size="sm" />,
    );
    expect(button(container)).toHaveAttribute('start-icon', 'trash');
    expect(button(container)).toHaveAttribute('appearance', 'destructive');
    expect(button(container)).toHaveAttribute('size', 'sm');
  });

  it('points a button outside its form at that form', () => {
    const { container } = render(<NlddButton text="Opslaan" type="submit" form="f" />);
    expect(button(container)).toHaveAttribute('type', 'submit');
    expect(button(container)).toHaveAttribute('form', 'f');
  });

  describe('compactBelowSm', () => {
    const setWidth = (wide: boolean) =>
      vi.stubGlobal(
        'matchMedia',
        vi.fn().mockImplementation((query: string) => ({
          matches: wide,
          media: query,
          addEventListener: vi.fn(),
          removeEventListener: vi.fn(),
        })),
      );

    afterEach(() => vi.unstubAllGlobals());

    it('shows the label from sm up', () => {
      setWidth(true);
      const { container } = render(<NlddButton startIcon="plus" text="Nieuwe taak" compactBelowSm />);
      expect(button(container)).toHaveAttribute('text', 'Nieuwe taak');
      expect(button(container)).not.toHaveAttribute('accessible-label');
    });

    it('turns the label into the accessible name below sm', () => {
      setWidth(false);
      const { container } = render(<NlddButton startIcon="plus" text="Nieuwe taak" compactBelowSm />);
      expect(button(container)).not.toHaveAttribute('text');
      expect(button(container)).toHaveAttribute('accessible-label', 'Nieuwe taak');
    });
  });
});
