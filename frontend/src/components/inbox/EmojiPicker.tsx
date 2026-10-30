import { useCallback, useRef } from 'react';
import { useNlddEvent } from '@/components/nldd/events';
import { NlddButton } from '@/components/nldd/NlddButton';

const EMOJIS = ['👍', '👎', '❤️', '😊', '😂', '🎉', '👀', '🤔', '✅', '🔥', '💯', '👏'];

interface EmojiPickerProps {
  onSelect: (emoji: string) => void;
  /** Accessible name of the trigger button. */
  accessibleLabel: string;
  icon: string;
  variant?: 'neutral-transparent' | 'neutral-tinted';
  size?: 'xs' | 'sm' | 'md';
  /** Reports the popover opening and closing, e.g. to keep a hover-revealed trigger visible. */
  onOpenChange?: (open: boolean) => void;
}

/**
 * An icon button that opens a grid of emoji.
 *
 * The popover sits in the button's `popup` slot, so the design system anchors
 * it, toggles it and handles light dismiss and Escape. On a narrow screen it
 * becomes a bottom sheet by itself.
 */
export function EmojiPicker({
  onSelect,
  accessibleLabel,
  icon,
  variant = 'neutral-transparent',
  size = 'sm',
  onOpenChange,
}: EmojiPickerProps) {
  const popoverRef = useRef<HTMLElement>(null);

  // The popover's own events do not bubble, so listen on the popover itself.
  useNlddEvent(popoverRef, 'open', useCallback(() => onOpenChange?.(true), [onOpenChange]));
  useNlddEvent(popoverRef, 'close', useCallback(() => onOpenChange?.(false), [onOpenChange]));

  const pick = (emoji: string) => {
    onSelect(emoji);
    // The component's own hide(): it no-ops when already closed.
    (popoverRef.current as { hide?: () => void } | null)?.hide?.();
  };

  return (
    <nldd-icon-button
      icon={icon}
      appearance={variant}
      size={size}
      accessible-label={accessibleLabel}
      popup-type="dialog"
    >
      <nldd-popover
        slot="popup"
        ref={popoverRef}
        accessible-label="Kies een reactie"
        width="248px"
        placement="top-start"
      >
        <nldd-container layout="grid" column-count={6} gap="4" padding="8" horizontal-alignment="center">
          {EMOJIS.map((emoji) => (
            <NlddButton
              key={emoji}
              variant="neutral-transparent"
              size="sm"
              text={emoji}
              onClick={() => pick(emoji)}
            />
          ))}
        </nldd-container>
      </nldd-popover>
    </nldd-icon-button>
  );
}
