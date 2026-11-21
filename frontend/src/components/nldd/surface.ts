import type { CSSProperties } from 'react';

/**
 * Text color for a filled surface of our own, such as your own message
 * bubble. Since 0.23.0 nldd text, rich text, links and icons no longer follow
 * the CSS `color` around them (`color="inherit"` is gone): they read the
 * `--context-*` colors. This sets those to the one color, next to `color`
 * itself, so everything on the surface keeps reading in that color.
 */
export function surfaceTextColor(color: string): CSSProperties {
  return {
    color,
    '--context-content-color': color,
    '--context-content-secondary-color': color,
    '--context-link-color': color,
    '--context-link-is-hovered-color': color,
    '--context-link-is-active-color': color,
  } as CSSProperties;
}
