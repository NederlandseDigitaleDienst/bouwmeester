import { useCallback, useEffect, useRef, type ReactNode } from 'react';
import { createPortal } from 'react-dom';
import type { EntityColor } from '@/types';
import { useNlddEvent, useNlddOverlay } from '@/components/nldd/events';

/** Window width per size step. */
const SIZE_WIDTH = {
  sm: 'min(448px, calc(100vw - 32px))',
  md: 'min(512px, calc(100vw - 32px))',
  lg: 'min(672px, calc(100vw - 32px))',
  xl: 'min(896px, calc(100vw - 32px))',
} as const;

/** Breedte van een zijpaneel per stap. De sheet begrenst zelf tot het scherm. */
const SHEET_WIDTH = { sm: '448px', md: '512px', lg: '672px', xl: '896px' } as const;

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
  size?: 'sm' | 'md' | 'lg' | 'xl';
  closeable?: boolean;
  headerIcon?: ReactNode;
  entityLabel?: string;
  accentColor?: EntityColor;
  /** Small back-link above the title for modal stacking navigation */
  backLabel?: string;
  onBack?: () => void;
  /**
   * Waar het venster staat. Standaard in het midden. `left` en `right` maken
   * er een paneel van over de volle hoogte aan die kant, zodat wat ernaast
   * staat (een kaartje op een bord) in beeld blijft. Een zijpaneel sluit
   * altijd bij een klik ernaast, dus niet combineren met `closeable={false}`.
   */
  placement?: 'center' | 'left' | 'right';
  /**
   * Knoppen in de titelbalk, links van Sluiten. Elk element heeft
   * `slot="toolbar"` nodig (NlddButton heeft daar een prop voor).
   */
  toolbar?: ReactNode;
  /** De tekst van de sluitknop rechtsboven. Standaard "Sluiten". */
  dismissText?: string;
  /**
   * Een veld om de titel ter plekke te bewerken. Zolang het er is, staat het
   * in de kop op de plek van de titelbalk: die balk toont alleen tekst en
   * heeft geen plek voor een invoerveld. De balk blijft gemount (verborgen),
   * zodat Sluiten en Terug daarna gewoon blijven werken.
   */
  titleEditor?: ReactNode;
}

/**
 * `nldd-window` + `nldd-page` as a modal dialog.
 *
 * The window is a native `<dialog>`, always modal, so the browser owns four
 * things a caller never has to: the backdrop, the top layer (stacking needs no
 * z-index of its own), the focus trap, and Escape.
 *
 * The title bar is `nldd-top-title-bar` in the page's sticky header, which
 * supplies the heading, the back affordance and the dismiss button, each with
 * its own accessible name.
 *
 * Links of rechts is het geen zwevend venster maar een `nldd-sheet`: die loopt
 * over de volle hoogte (op de overlay-marge na) en wordt op een smal scherm
 * vanzelf een paneel van onderen. Een `nldd-window` kan dat niet, die is
 * begrensd op de hoogte van het scherm min twee keer de marge en bleef
 * daardoor bovenaan plakken met onderin een strook pagina.
 */
export function Modal(props: ModalProps) {
  // Een ander element (sheet of window) betekent een nieuwe open-cyclus: de
  // effecten hieronder moeten opnieuw lopen, anders blijft het nieuwe element
  // dicht terwijl `open` al true is. De key regelt dat.
  return <ModalOverlay key={props.placement && props.placement !== 'center' ? 'sheet' : 'window'} {...props} />;
}

function ModalOverlay({
  open,
  onClose,
  title,
  children,
  footer,
  size = 'md',
  closeable = true,
  headerIcon: _headerIcon,
  entityLabel,
  accentColor,
  backLabel,
  onBack,
  placement = 'center',
  toolbar,
  dismissText = 'Sluiten',
  titleEditor,
}: ModalProps) {
  const windowRef = useRef<HTMLElement>(null);
  const barRef = useRef<HTMLElement>(null);
  const openedAt = useRef(0);

  const handleClose = useCallback(() => {
    // Suppress the close for the first 250ms after opening. Without this, a
    // synthetic click that follows a drag-and-drop (Outlook on Windows/Citrix)
    // lands on the freshly opened window and closes it before the user sees it.
    // Kept from the previous implementation: it was reported from the field.
    if (Date.now() - openedAt.current < 250) return;
    if (!closeable) return;
    onClose();
  }, [closeable, onClose]);

  // Remember when this became visible, for the guard above. In an effect, not
  // during render: a render may run more than once per commit (and does under
  // StrictMode), so a timestamp written there can be re-stamped by a re-render
  // that has nothing to do with opening, and the guard would then swallow a
  // click the user meant.
  //
  // This has to stand BEFORE useNlddOverlay: effects run in the order they are
  // declared, and the overlay's effect is the one that calls show(). Stamped
  // afterwards, the window would be on screen for one effect longer with
  // openedAt still at 0, and a click arriving in that gap reads as 250ms past
  // an open that had not happened yet. That gap is exactly the one the guard
  // exists for.
  useEffect(() => {
    openedAt.current = open ? Date.now() : 0;
  }, [open]);

  useNlddOverlay(windowRef, open, handleClose);

  // The title bar's own dismiss and back buttons.
  useNlddEvent(barRef, 'dismiss', closeable ? onClose : undefined);
  useNlddEvent(barRef, 'back', onBack);

  const content = (
    <>
      {/* A 3px line in the entity color along the top edge, which is how this app
          signals "you are looking at a lead / a node / an opdracht". */}
      {accentColor && (
        <div
          style={{
            height: '3px',
            backgroundColor: `var(--primitives-color-${accentColor}-500)`,
          }}
        />
      )}
      <nldd-page sticky-header {...(footer ? { 'sticky-footer': true } : {})}>
        {titleEditor && (
          <nldd-container slot="header" padding-inline="16" padding-block="8">
            {titleEditor}
          </nldd-container>
        )}
        <nldd-top-title-bar
          ref={barRef}
          slot="header"
          hidden={!!titleEditor}
          text={title}
          {...(entityLabel ? { 'supporting-text': entityLabel } : {})}
          {...(backLabel && onBack ? { 'back-text': `Terug naar ${backLabel}` } : {})}
          {...(closeable ? { 'dismiss-text': dismissText } : {})}
        >
          {toolbar}
        </nldd-top-title-bar>
        {/* `headerIcon` has nowhere to go: nldd-top-title-bar has only a
            `toolbar` slot, beside the dismiss button, and an icon there would
            read as an action rather than as the entity's type. The type is
            already named in `supporting-text`, so the icon is dropped. */}

        <nldd-container padding="24">{children}</nldd-container>

        {footer && (
          <nldd-container
            slot="footer"
            layout="row"
            gap="12"
            padding="16"
            horizontal-alignment="right"
            vertical-alignment="center"
          >
            {footer}
          </nldd-container>
        )}
      </nldd-page>
    </>
  );

  if (placement !== 'center') {
    // Aan de documentwortel, zoals de sheet vraagt: binnen een split view
    // zou hij als flex-kind hoogte van het paneel afsnoepen. Een portal houdt
    // de React-context gewoon vast.
    return createPortal(
      <nldd-sheet ref={windowRef} accessible-label={title} placement={placement} width={SHEET_WIDTH[size]}>
        {content}
      </nldd-sheet>,
      document.body,
    );
  }

  return (
    <nldd-window
      ref={windowRef}
      accessible-label={title}
      centered
      width={SIZE_WIDTH[size]}
      {...(closeable ? {} : { 'no-light-dismiss': true })}
    >
      {content}
    </nldd-window>
  );
}
