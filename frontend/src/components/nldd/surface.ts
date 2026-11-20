import type { CSSProperties } from 'react';

/**
 * The colors a surface of our own passes on to the design system components
 * on it. A component takes its text and link colors from the context, not from
 * the CSS `color` around it, so a filled surface sets them next to `color`.
 *
 * All three link colors, or a link falls back to the page's blue on hover.
 */
export function surfaceContext(content: string, background?: string): CSSProperties {
  return {
    '--context-content-color': content,
    '--context-content-secondary-color': content,
    '--context-link-color': content,
    '--context-link-is-hovered-color': content,
    '--context-link-is-active-color': content,
    ...(background ? { '--context-background-color': background } : {}),
  } as CSSProperties;
}
