/**
 * `Initiatief.kleur` as the design system understands it.
 *
 * The stored value is an nldd color name, so the same string drives three
 * different elements: `nldd-tag`'s `color` (the chip in a list or a detail
 * row), `nldd-icon`'s `color` (the dot in a toggle pill or a swatch), and the
 * `--semantics-categories-*` token family (a decorative accent that is neither,
 * such as the stripe on the public page). Each of the three takes a slightly
 * different vocabulary, hence a function per element rather than one cast.
 */

type NlddTagColor = NonNullable<React.ComponentProps<'nldd-tag'>['color']>;
type NlddIconColor = NonNullable<React.ComponentProps<'nldd-icon'>['color']>;

/**
 * The full set the backend accepts, mirrored by hand from
 * `schema.initiatief.INITIATIEF_COLORS`. Wider than the picker's
 * `INITIATIEF_COLORS` in `src/types`, because a row may hold any of these:
 * from another environment, or from before the picker was narrowed.
 */
const KLEUR_NAMES: ReadonlySet<NlddTagColor> = new Set([
  'neutral',
  'accent',
  'success',
  'warning',
  'critical',
  'lintblauw',
  'donkerblauw',
  'hemelblauw',
  'lichtblauw',
  'paars',
  'violet',
  'robijnrood',
  'roze',
  'rood',
  'oranje',
  'donkergeel',
  'geel',
  'donkerbruin',
  'bruin',
  'donkergroen',
  'groen',
  'mosgroen',
  'mintgroen',
]);

/** A `kleur` outside the set, or absent, falls back to grey rather than
 *  rendering in no color at all. */
export function initiatiefTagColor(kleur: string | null | undefined): NlddTagColor {
  return kleur && (KLEUR_NAMES as ReadonlySet<string>).has(kleur)
    ? (kleur as NlddTagColor)
    : 'neutral';
}

/**
 * The same name for `nldd-icon`, which takes the 18 rijkskleuren and the
 * functional semantics but has no 'neutral': grey there is
 * 'secondary'.
 */
export function initiatiefIconColor(kleur: string | null | undefined): NlddIconColor {
  const color = initiatiefTagColor(kleur);
  return color === 'neutral' ? 'secondary' : (color as NlddIconColor);
}

/**
 * A CSS color for a decorative accent that is not a tag or an icon — the
 * stripe and rails on the public page. Reads the same token the tag paints its
 * fill from, so the accent tracks the theme instead of pinning a hex.
 */
export function initiatiefAccentVar(kleur: string | null | undefined): string {
  return `var(--semantics-categories-${initiatiefTagColor(kleur)}-filled-background-color)`;
}
