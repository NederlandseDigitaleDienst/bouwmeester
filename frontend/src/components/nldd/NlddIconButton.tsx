/**
 * `nldd-icon-button` with a React-shaped onClick.
 *
 * An icon-only control has no visible label, so `accessibleLabel` is required
 * rather than optional: without it the button is announced as nothing.
 */
import { useCallback, useRef } from 'react';
import { useNlddEvent } from './events';

interface NlddIconButtonProps {
  /** An nldd-icon name from the closed set. */
  icon: string;
  /** Required: the button shows no text, so this is its whole accessible name. */
  accessibleLabel: string;
  /**
   * The DOM event is passed through, so a button inside a clickable row can
   * call `stopPropagation()` on it. Without that the row's own handler fires
   * too and a click on "mark as read" also opens the notification.
   */
  onClick?: (event: Event) => void;
  variant?:
    | 'primary'
    | 'secondary'
    | 'destructive'
    | 'accent-filled'
    | 'accent-transparent'
    | 'neutral-tinted'
    | 'neutral-base'
    | 'neutral-transparent'
    | 'critical-tinted'
    | 'critical-transparent'
    | 'inherit-filled'
    | 'inherit-tinted';
  size?: 'xs' | 'sm' | 'md' | 'lg';
  disabled?: boolean;
  type?: 'button' | 'submit' | 'reset';
  className?: string;
  /** De named slot om in te landen, zoals `toolbar` in een titelbalk (zie NlddButton). */
  slot?: string;
}

export function NlddIconButton({
  icon,
  accessibleLabel,
  onClick,
  variant = 'neutral-transparent',
  size = 'md',
  disabled,
  type = 'button',
  className,
  slot,
}: NlddIconButtonProps) {
  const ref = useRef<HTMLElement>(null);
  const handler = useCallback((event: Event) => onClick?.(event), [onClick]);
  useNlddEvent(ref, 'click', onClick ? handler : undefined);

  return (
    <nldd-icon-button
      ref={ref}
      icon={icon}
      appearance={variant}
      size={size}
      type={type}
      accessible-label={accessibleLabel}
      className={className}
      {...(slot ? { slot } : {})}
      {...(disabled ? { disabled: true } : {})}
    />
  );
}
