import { useLocation } from 'react-router-dom';
import { isLeadDropPath } from '@/utils/initiatiefRoutes';

interface GlobalDropOverlayProps {
  visible: boolean;
}

/**
 * The full-screen hint while a file is being dragged over the window.
 *
 * The one overlay that cannot be a component. nldd-window documents itself as
 * "always modal", and a modal takes focus and blocks what is underneath; this
 * has to let the drop reach the page (`pointer-events: none`), so it would be
 * the wrong element however it looked.
 *
 * What remains is layout and hit-testing, not styling: fill the viewport, sit
 * above the page, pass events through. The backdrop uses the system's own
 * `--semantics-overlays-backdrop-color`, the same one its dialogs draw, so it
 * follows the theme instead of being a black this file picked.
 */
export function GlobalDropOverlay({ visible }: GlobalDropOverlayProps) {
  const location = useLocation();

  if (!visible) return null;

  let message = 'Laat los om een bestand of e-mail te verwerken';
  if (isLeadDropPath(location.pathname)) {
    message = 'Laat los om een nieuwe lead aan te maken';
  } else if (location.pathname.startsWith('/corpus')) {
    message = 'Laat los om een nieuwe bron toe te voegen';
  }

  return (
    <div
      style={{
        position: 'fixed',
        inset: 0,
        // Only has to clear the page. Every dialog in the app is a native
        // <dialog> on the top layer now, which no z-index can reach anyway, so
        // this cannot cover a modal however high it goes.
        zIndex: 1,
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        backgroundColor: 'var(--semantics-overlays-backdrop-color)',
        backdropFilter: 'blur(4px)',
        pointerEvents: 'none',
      }}
    >
      <nldd-card>
        <nldd-container
          gap="12"
          padding="32"
          horizontal-alignment="center"
          vertical-alignment="center"
        >
          <nldd-icon icon="upload" size="32" color="accent" aria-hidden="true" />
          <nldd-text weight="bold">{message}</nldd-text>
        </nldd-container>
      </nldd-card>
    </div>
  );
}
