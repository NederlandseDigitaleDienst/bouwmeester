import { describe, it, expect, vi, beforeEach } from 'vitest';
import { act, fireEvent, screen } from '@testing-library/react';

import { ToastProvider } from '@/contexts/ToastContext';
import { renderWithProviders } from '@/test/utils';
import { useTaakVerwijderen } from './useTaakVerwijderen';

const deleteTask = vi.fn();
vi.mock('@/api/tasks', async (orig) => ({
  ...(await orig<typeof import('@/api/tasks')>()),
  deleteTask: (id: string) => deleteTask(id),
}));

/** Een taakregel zoals in de backlog: rechtermuisknop opent het menu. */
function Regel({ onVerwijderd }: { onVerwijderd?: (id: string) => void }) {
  const verwijderen = useTaakVerwijderen({ onVerwijderd });
  const taak = { id: 't1', title: 'Wet lezen' };
  return (
    <>
      <div data-testid="taak" onContextMenu={(e) => verwijderen.openMenu(e, taak)}>
        Wet lezen
      </div>
      {verwijderen.element}
    </>
  );
}

const dialoog = () => document.querySelector('nldd-modal-dialog') as (HTMLElement & { show?: () => void }) | null;

describe('useTaakVerwijderen', () => {
  beforeEach(() => deleteTask.mockReset().mockResolvedValue(undefined));

  it('rechtermuisknop toont het menu, nog zonder iets te verwijderen', () => {
    renderWithProviders(<ToastProvider><Regel /></ToastProvider>);
    fireEvent.contextMenu(screen.getByTestId('taak'), { clientX: 40, clientY: 50 });
    expect(screen.getByRole('menuitem', { name: /Taak verwijderen/ })).toBeTruthy();
    expect(deleteTask).not.toHaveBeenCalled();
  });

  it('Escape sluit het menu', () => {
    renderWithProviders(<ToastProvider><Regel /></ToastProvider>);
    fireEvent.contextMenu(screen.getByTestId('taak'), { clientX: 40, clientY: 50 });
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(screen.queryByRole('menu')).toBeNull();
  });

  it('verwijderen gaat pas na bevestiging', async () => {
    renderWithProviders(<ToastProvider><Regel /></ToastProvider>);
    fireEvent.contextMenu(screen.getByTestId('taak'), { clientX: 40, clientY: 50 });
    fireEvent.click(screen.getByRole('menuitem', { name: /Taak verwijderen/ }));

    // Menu weg, bevestiging met de titel van de taak erin; nog niets verwijderd.
    expect(screen.queryByRole('menu')).toBeNull();
    const d = dialoog();
    expect(d?.getAttribute('supporting-text')).toContain('Wet lezen');
    expect(deleteTask).not.toHaveBeenCalled();

    // De knop "Verwijderen" is een nldd-button; de wrapper luistert op de host.
    const knop = [...d!.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === 'Verwijderen')!;
    await act(async () => {
      knop.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(deleteTask).toHaveBeenCalledWith('t1');
  });

  it('meldt een gelukte verwijdering, zodat een taakdetail kan sluiten', async () => {
    const onVerwijderd = vi.fn();
    renderWithProviders(<ToastProvider><Regel onVerwijderd={onVerwijderd} /></ToastProvider>);
    fireEvent.contextMenu(screen.getByTestId('taak'), { clientX: 40, clientY: 50 });
    fireEvent.click(screen.getByRole('menuitem', { name: /Taak verwijderen/ }));
    const knop = [...dialoog()!.querySelectorAll('nldd-button')].find((b) => b.getAttribute('text') === 'Verwijderen')!;
    await act(async () => {
      knop.dispatchEvent(new MouseEvent('click', { bubbles: true }));
    });
    expect(onVerwijderd).toHaveBeenCalledWith('t1');
  });
});
