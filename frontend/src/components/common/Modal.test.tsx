import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/react';
import { Modal } from './Modal';

/**
 * The modal renders `nldd-window` + `nldd-page`, so these assert the contract
 * rather than the markup.
 *
 * Three things belong in the Playwright suite instead, because jsdom cannot
 * reach them:
 *
 *  - Escape and the backdrop click are the native <dialog>'s own behaviour.
 *    jsdom does not implement `showModal`, so there is no dialog to press
 *    Escape against.
 *  - The close button lives in nldd-top-title-bar's shadow root, which Lit
 *    never renders under jsdom, so there is no button to click.
 *  - The window is always mounted (it opens and closes through show()/hide()
 *    so the animation plays), so the closed state is "not open", not "not
 *    rendered".
 */
describe('Modal', () => {
  const win = (container: HTMLElement) => container.querySelector('nldd-window');
  const bar = (container: HTMLElement) => container.querySelector('nldd-top-title-bar');

  it('stays mounted but closed when not open', () => {
    const { container } = render(
      <Modal open={false} onClose={vi.fn()} title="Test">
        Content
      </Modal>,
    );
    // Mounted, so the enter animation has something to animate.
    expect(win(container)).toBeInTheDocument();
    expect(win(container)).not.toHaveAttribute('open');
  });

  it('puts the title on the title bar', () => {
    const { container } = render(
      <Modal open onClose={vi.fn()} title="Bewerken">
        <p>Modal inhoud</p>
      </Modal>,
    );
    expect(bar(container)).toHaveAttribute('text', 'Bewerken');
    expect(screen.getByText('Modal inhoud')).toBeInTheDocument();
  });

  it('names the window for assistive technology', () => {
    const { container } = render(
      <Modal open onClose={vi.fn()} title="Taak bewerken">
        Content
      </Modal>,
    );
    expect(win(container)).toHaveAttribute('accessible-label', 'Taak bewerken');
  });

  it('renders the footer in the page footer slot', () => {
    render(
      <Modal open onClose={vi.fn()} title="Test" footer={<button>Opslaan</button>}>
        Body
      </Modal>,
    );
    const action = screen.getByText('Opslaan');
    expect(action).toBeInTheDocument();
    expect(action.closest('[slot="footer"]')).not.toBeNull();
  });

  it('offers a dismiss button when closeable', () => {
    const { container } = render(
      <Modal open onClose={vi.fn()} title="Sluiten">
        Content
      </Modal>,
    );
    expect(bar(container)).toHaveAttribute('dismiss-text', 'Sluiten');
  });

  it('offers no dismiss and no light dismiss when not closeable', () => {
    const { container } = render(
      <Modal open closeable={false} onClose={vi.fn()} title="Vast">
        Content
      </Modal>,
    );
    expect(bar(container)).not.toHaveAttribute('dismiss-text');
    // A click on the backdrop must not throw away work either.
    expect(win(container)).toHaveAttribute('no-light-dismiss');
  });

  it('shows a back affordance only with both a label and a handler', () => {
    const withBoth = render(
      <Modal open onClose={vi.fn()} title="Sub" backLabel="Taak" onBack={vi.fn()}>
        Content
      </Modal>,
    );
    expect(bar(withBoth.container)).toHaveAttribute('back-text', 'Terug naar Taak');

    const labelOnly = render(
      <Modal open onClose={vi.fn()} title="Sub" backLabel="Taak">
        Content
      </Modal>,
    );
    expect(bar(labelOnly.container)).not.toHaveAttribute('back-text');
  });

  it('becomes a full-height side sheet at the document root when placed left or right', () => {
    const { container } = render(
      <Modal open onClose={vi.fn()} title="Taak" placement="left">
        Paneelinhoud
      </Modal>,
    );
    // Geen zwevend venster: dat is begrensd op schermhoogte min de marge.
    expect(win(container)).toBeNull();
    const sheet = document.body.querySelector('nldd-sheet');
    expect(sheet).toHaveAttribute('placement', 'left');
    expect(sheet).toHaveAttribute('accessible-label', 'Taak');
    // Aan de wortel, niet in de flow van de pagina.
    expect(sheet?.parentElement).toBe(document.body);
    expect(screen.getByText('Paneelinhoud')).toBeInTheDocument();
  });

  it('puts toolbar actions inside the title bar', () => {
    const { container } = render(
      <Modal open onClose={vi.fn()} title="Taak" toolbar={<button slot="toolbar">Bewerken</button>}>
        Content
      </Modal>,
    );
    expect(screen.getByText('Bewerken').closest('nldd-top-title-bar')).toBe(bar(container));
  });

  it('names the entity type as supporting text', () => {
    const { container } = render(
      <Modal open onClose={vi.fn()} title="Iets" entityLabel="Taak">
        Content
      </Modal>,
    );
    expect(bar(container)).toHaveAttribute('supporting-text', 'Taak');
  });
});
