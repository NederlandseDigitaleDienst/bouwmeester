import { useCallback, useState, type MouseEvent as ReactMouseEvent } from 'react';

import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { TaakContextMenu } from '@/components/tasks/TaakContextMenu';
import { useDeleteTask } from '@/hooks/useTasks';

interface Taak {
  id: string;
  title: string;
}

interface MenuStand {
  x: number;
  y: number;
  taak: Taak;
}

/**
 * Een taak verwijderen via de rechtermuisknop, met een bevestiging ervoor.
 *
 * Geeft drie dingen terug:
 * - `openMenu(event, taak)`: hang aan `onContextMenu` van een taak. Opent een
 *   klein menu op de plek van de muis met "Taak verwijderen".
 * - `vraagBevestiging(taak)`: voor een prullenbakknop; slaat het menu over en
 *   vraagt meteen om bevestiging.
 * - `element`: het menu en het bevestigingsvenster; render dit één keer in
 *   de component die de hook gebruikt.
 *
 * Met het toetsenbord werkt het ook: de contextmenutoets of Shift+F10 op een
 * taak met focus geeft dezelfde `contextmenu`-gebeurtenis; het menu komt dan
 * onder de taak.
 *
 * `onVerwijderd` draait na een gelukte verwijdering, bijvoorbeeld om het
 * detail van die taak te sluiten.
 */
export function useTaakVerwijderen({ onVerwijderd }: { onVerwijderd?: (id: string) => void } = {}) {
  const deleteTask = useDeleteTask();
  const [menu, setMenu] = useState<MenuStand | null>(null);
  const [bevestig, setBevestig] = useState<Taak | null>(null);

  const openMenu = useCallback((e: ReactMouseEvent, taak: Taak) => {
    e.preventDefault();
    e.stopPropagation();
    let { clientX: x, clientY: y } = e;
    // Toetsenbord: geen muispositie, dan onder het element.
    if (x === 0 && y === 0) {
      const rect = (e.currentTarget as HTMLElement).getBoundingClientRect();
      x = rect.left + 8;
      y = rect.bottom;
    }
    setMenu({ x, y, taak });
  }, []);

  const vraagBevestiging = useCallback((taak: Taak) => setBevestig(taak), []);

  const verwijder = async () => {
    if (!bevestig) return;
    try {
      await deleteTask.mutateAsync(bevestig.id);
      setBevestig(null);
      onVerwijderd?.(bevestig.id);
    } catch {
      // toast is al getoond; het venster blijft open
    }
  };

  const element = (
    <>
      {menu && (
        <TaakContextMenu
          x={menu.x}
          y={menu.y}
          titel={menu.taak.title}
          onClose={() => setMenu(null)}
          onVerwijder={() => {
            setBevestig(menu.taak);
            setMenu(null);
          }}
        />
      )}
      <ConfirmDialog
        open={!!bevestig}
        onClose={() => setBevestig(null)}
        onConfirm={verwijder}
        title="Taak verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
        loading={deleteTask.isPending}
      >
        {`"${bevestig?.title ?? ''}" wordt definitief verwijderd, met subtaken, opmerkingen en bijlagen.`}
      </ConfirmDialog>
    </>
  );

  return { openMenu, vraagBevestiging, element };
}

