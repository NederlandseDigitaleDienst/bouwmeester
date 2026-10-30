/**
 * `nldd-icon` with this app's size scale.
 *
 * The design system ships a closed set (359 icons + 318 aliases); an unknown
 * name renders nothing at all, with no error. `scripts/validate-nldd-markup.mjs`
 * checks every literal name passed to `Icon` against that set.
 *
 * `nldd-icon` sizes in pixels, so the `size` prop maps this app's named scales
 * onto them.
 */
import type { CSSProperties } from 'react';

/**
 * Named icon scales, in pixels.
 *
 * nldd-icon only accepts spacer-aligned sizes (16, 20, 24, 28, 32, 40, ...),
 * so `xs` and `sm` both land on 16: that is the design system's grid, not an
 * approximation to work around.
 */
const ICON_SIZES = {
  xs: '16', // the smallest supported size
  sm: '16',
  md: '16', // by far the most common
  lg: '20',
  xl: '24',
} as const;

type IconSize = keyof typeof ICON_SIZES;

interface IconProps {
  /** An nldd-icon name. */
  name: string;
  /** A scale from ICON_SIZES, or an nldd-icon size ('full', 'inherit', '24'). */
  size?: IconSize | NlddIconSize;
  /** Screen-reader label. Without one the icon is decorative and hidden. */
  label?: string;
  /**
   * An nldd-icon colour: a role ('secondary-content', 'critical', ...) or a
   * Rijkshuisstijl name. Forwarded so a call site never has to reach for an
   * inline style, which is how a hand-picked palette step ends up standing in
   * for a role that already exists.
   */
  color?: NonNullable<React.ComponentProps<'nldd-icon'>['color']>;
  className?: string;
  style?: CSSProperties;
}

/** The sizes nldd-icon itself accepts: spacer-aligned pixels, or a keyword. */
type NlddIconSize =
  | 'full'
  | 'inherit'
  | '16'
  | '20'
  | '24'
  | '28'
  | '32'
  | '40'
  | '44'
  | '48'
  | '56'
  | '64'
  | '80'
  | '96';

export function Icon({ name, size = 'md', label, color, className, style }: IconProps) {
  const px = size in ICON_SIZES ? ICON_SIZES[size as IconSize] : (size as NlddIconSize);

  return (
    <nldd-icon
      icon={name}
      size={px}
      className={className}
      style={style}
      {...(color ? { color } : {})}
      {...(label ? { 'accessible-label': label } : { 'aria-hidden': true })}
    />
  );
}
