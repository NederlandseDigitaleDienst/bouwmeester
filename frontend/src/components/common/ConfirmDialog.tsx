import { useRef, type ReactNode } from 'react';
import { useNlddOverlay } from '@/components/nldd/events';
import { NlddButton } from '@/components/nldd/NlddButton';

interface ConfirmDialogProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => void | Promise<void>;
  title: string;
  children: ReactNode;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: 'danger' | 'default';
  loading?: boolean;
}

/**
 * A confirmation, as an `nldd-modal-dialog`.
 *
 * Button order for a destructive action: the design guidelines put the safe way
 * out FIRST and give it `variant="primary"`, with the destructive action below
 * it as `destructive`. The primary button is where someone lands on autopilot,
 * and that should be the way back, not the irreversible step.
 *
 * The wider point from the same guidelines stands and is not solved here:
 * undo beats confirm. People click OK on autopilot, so a confirmation catches
 * few mistakes. Replacing these dialogs with optimistic updates plus an undo is
 * its own piece of work, and the toast already carries an action slot for it.
 *
 * `horizontal-alignment="left"`: zonder die instelling zet het design system
 * de knoppen van een gecentreerde dialoog onder elkaar, over de volle
 * breedte. Links uitgelijnd legt het ze naast elkaar, wat bij twee knoppen
 * (annuleren, bevestigen) is wat je verwacht.
 */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  children,
  confirmLabel = 'Bevestigen',
  cancelLabel = 'Annuleren',
  variant = 'default',
  loading = false,
}: ConfirmDialogProps) {
  const ref = useRef<HTMLElement>(null);
  useNlddOverlay(ref, open, onClose);

  // The element takes its body as `supporting-text`; anything richer than a
  // string goes in the default slot instead.
  const supporting = typeof children === 'string' ? children : undefined;

  return (
    <nldd-modal-dialog
      ref={ref}
      accessible-label={title}
      text={title}
      horizontal-alignment="left"
      {...(variant === 'danger' ? { variant: 'alert' } : {})}
      {...(supporting ? { 'supporting-text': supporting } : {})}
    >
      {supporting ? null : children}

      <div slot="actions">
        <NlddButton
          text={cancelLabel}
          variant="primary"
          onClick={onClose}
          disabled={loading}
        />
      </div>
      <div slot="actions">
        <NlddButton
          text={confirmLabel}
          variant={variant === 'danger' ? 'destructive' : 'secondary'}
          onClick={() => void onConfirm()}
          loading={loading}
        />
      </div>
    </nldd-modal-dialog>
  );
}
