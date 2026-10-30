import { describe, it, expect, vi } from 'vitest';
import { render } from '@testing-library/react';

import { RichTextEditor } from './RichTextEditor';

/**
 * Enter verstuurt (onEnter), Shift+Enter niet, en een open @-lijst laat Enter
 * aan de editor. jsdom tekent de editor zelf niet; we sturen de toets naar
 * het element en kijken of de functie wordt aangeroepen en of de toets de
 * editor nog bereikt.
 */
function toets(el: Element, init: KeyboardEventInit) {
  const e = new KeyboardEvent('keydown', { bubbles: true, cancelable: true, composed: true, ...init });
  el.dispatchEvent(e);
  return e;
}

describe('RichTextEditor onEnter', () => {
  it('Enter roept onEnter aan en is geen nieuwe regel', () => {
    const onEnter = vi.fn();
    const { container } = render(<RichTextEditor value="" onChange={vi.fn()} onEnter={onEnter} />);
    const el = container.querySelector('nldd-text-editor')!;
    const e = toets(el, { key: 'Enter' });
    expect(onEnter).toHaveBeenCalledTimes(1);
    expect(e.defaultPrevented).toBe(true);
  });

  it('Shift+Enter laat de editor een nieuwe regel maken', () => {
    const onEnter = vi.fn();
    const { container } = render(<RichTextEditor value="" onChange={vi.fn()} onEnter={onEnter} />);
    const e = toets(container.querySelector('nldd-text-editor')!, { key: 'Enter', shiftKey: true });
    expect(onEnter).not.toHaveBeenCalled();
    expect(e.defaultPrevented).toBe(false);
  });

  it('met de @-lijst open kiest Enter in de lijst', () => {
    const onEnter = vi.fn();
    const { container } = render(<RichTextEditor value="" onChange={vi.fn()} onEnter={onEnter} />);
    const el = container.querySelector('nldd-text-editor')!;
    const root = el.shadowRoot ?? el.attachShadow({ mode: 'open' });
    const lijst = document.createElement('div');
    lijst.className = 'cm-tooltip-autocomplete';
    root.appendChild(lijst);
    toets(el, { key: 'Enter' });
    expect(onEnter).not.toHaveBeenCalled();
  });

  it('zonder onEnter verandert er niets', () => {
    const { container } = render(<RichTextEditor value="" onChange={vi.fn()} />);
    const e = toets(container.querySelector('nldd-text-editor')!, { key: 'Enter' });
    expect(e.defaultPrevented).toBe(false);
  });
});
