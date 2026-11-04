import { useCallback, useRef, type ReactNode } from 'react';
import { useMediaQuery } from '@/hooks/useMediaQuery';
import { useNlddEvent } from './events';

/** The `sm` breakpoint, the same one as `hidden-below-sm-block` in utilities.css. */
const SM_UP = '(min-width: 640px)';

interface NlddButtonProps {
  onClick?: () => void;
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
  text?: string;
  startIcon?: string;
  endIcon?: string;
  /**
   * Below `sm`, show only the icon; `text` then becomes the accessible name.
   * For toolbar buttons that have no room for their label on a phone.
   */
  compactBelowSm?: boolean;
  /**
   * Clips an over-long label with an ellipsis instead of letting it wrap. It
   * has to be the element's own attribute: the label lives in the shadow
   * root, where a `truncate` class on the host never reaches. Give the button
   * (or an ancestor) a width to clip against.
   */
  singleLine?: boolean;
  type?: 'button' | 'submit' | 'reset';
  /** The id of the form this button submits, when it sits outside that form. */
  form?: string;
  disabled?: boolean;
  loading?: boolean;
  width?: string;
  accessibleLabel?: string;
  id?: string;
  title?: string;
  /**
   * The named slot to land in.
   *
   * Needed because a wrapper around a slotted button is not neutral: the
   * element places an `nldd-button-group` around whatever lands in its
   * `actions` slot, and a `<div>` in between becomes that group's single item.
   * The buttons then line up against the left edge of a centred dialog rather
   * than under its heading.
   */
  slot?: string;
  children?: ReactNode;
  className?: string;
}

/**
 * `nldd-button` with a React-shaped onClick.
 *
 * Note the label goes in the `text` attribute, not in children. Children land
 * in the `text` slot, which the element only uses when `text` is unset — pass
 * children only for a label with inline markup.
 */
export function NlddButton(props: NlddButtonProps) {
  return props.compactBelowSm ? <CompactBelowSm {...props} /> : <BaseButton {...props} />;
}

/** Separate so only compact buttons listen to the viewport width. */
function CompactBelowSm({ text, accessibleLabel, ...props }: NlddButtonProps) {
  const wide = useMediaQuery(SM_UP);
  return (
    <BaseButton
      {...props}
      text={wide ? text : undefined}
      accessibleLabel={accessibleLabel ?? (wide ? undefined : text)}
    />
  );
}

function BaseButton({
  onClick,
  variant = 'primary',
  size = 'md',
  text,
  startIcon,
  endIcon,
  singleLine,
  type = 'button',
  form,
  disabled,
  loading,
  width,
  accessibleLabel,
  id,
  title,
  slot,
  children,
  className,
}: NlddButtonProps) {
  const ref = useRef<HTMLElement>(null);
  const handler = useCallback(() => onClick?.(), [onClick]);
  useNlddEvent(ref, 'click', onClick ? handler : undefined);

  return (
    <nldd-button
      ref={ref}
      appearance={variant}
      size={size}
      type={type}
      className={className}
      {...(id ? { id } : {})}
      {...(title ? { title } : {})}
      {...(form ? { form } : {})}
      {...(text ? { text } : {})}
      {...(startIcon ? { 'start-icon': startIcon } : {})}
      {...(endIcon ? { 'end-icon': endIcon } : {})}
      {...(singleLine ? { 'single-line': true } : {})}
      {...(disabled ? { disabled: true } : {})}
      {...(loading ? { loading: true } : {})}
      {...(width ? { width } : {})}
      {...(accessibleLabel ? { 'accessible-label': accessibleLabel } : {})}
      {...(slot ? { slot } : {})}
    >
      {children}
    </nldd-button>
  );
}
