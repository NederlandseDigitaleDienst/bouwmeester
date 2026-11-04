import { LeadStage } from '@/types';
import type { EngagementType } from '@/types';

/**
 * Local nldd-tag color per lead stage.
 *
 * `LEAD_STAGE_COLORS` in `src/types` is the default column color per stage,
 * mirroring the backend. This is the presentation-side map: the five mid-funnel
 * stages get a distinguishing Rijkshuisstijl hue, since they are just
 * visually distinct labels, while the two stages that carry real structural
 * meaning ("won", "parked") get a semantic role instead, since that meaning
 * matters more than visual variety there.
 */
type NlddTagColor = NonNullable<React.ComponentProps<'nldd-tag'>['color']>;

const STAGE_TAG_COLOR: Record<string, NlddTagColor> = {
  [LeadStage.INBOX]: 'lintblauw',
  [LeadStage.VERKENNEN]: 'hemelblauw',
  [LeadStage.EERSTE_GESPREK]: 'geel',
  [LeadStage.INTERNE_CHECK]: 'oranje',
  [LeadStage.FOLLOW_UP]: 'paars',
  [LeadStage.IN_THE_POCKET]: 'success',
  [LeadStage.KOELKAST]: 'neutral',
};

export function stageTagColor(stage: string): NlddTagColor {
  return STAGE_TAG_COLOR[stage as LeadStage] ?? 'neutral';
}

/**
 * Same idea for `EngagementType` (a fixed 5-value union, unlike
 * `LeadColumn.color`), replacing `ENGAGEMENT_TYPE_COLORS` in `src/types`.
 */
const ENGAGEMENT_TAG_COLOR: Record<EngagementType, NlddTagColor> = {
  intern_oppakken: 'success',
  voorbereiden_eigen_team: 'lintblauw',
  betrokken_houden: 'hemelblauw',
  verkenning: 'oranje',
  nog_te_bepalen: 'neutral',
};

export function engagementTagColor(type: EngagementType): NlddTagColor {
  return ENGAGEMENT_TAG_COLOR[type] ?? 'neutral';
}

/**
 * The closed set `LeadColumn.color` may hold, mirrored by hand from backend
 * `schema.lead_column.LEAD_COLUMN_COLORS`. A stored value outside this set
 * falls back to grey.
 */
const LEAD_COLUMN_COLORS: ReadonlySet<NlddTagColor> = new Set([
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

/** A `col.color` from another environment or an older row falls back to
 *  'neutral' rather than rendering nothing. */
export function leadColumnTagColor(color: string): NlddTagColor {
  return (LEAD_COLUMN_COLORS as ReadonlySet<string>).has(color)
    ? (color as NlddTagColor)
    : 'neutral';
}

/**
 * The closed set of nldd-tag color names `LeadColumn.color` (and
 * `CasusSoort.kleur`) may hold,
 * mirrored from backend `schema.lead_column.LEAD_COLUMN_COLORS` (kept in
 * sync by hand). The swatch is an nldd-icon in that color: the icon takes the
 * same Rijkshuisstijl names and semantic roles as the tag, except that its
 * grey is 'secondary-content' rather than 'neutral'.
 */
export const TAG_KLEUR_OPTIES: { label: string; value: NlddTagColor }[] = [
  // Semantic roles
  { label: 'Neutraal', value: 'neutral' },
  { label: 'Accent', value: 'accent' },
  { label: 'Succes', value: 'success' },
  { label: 'Waarschuwing', value: 'warning' },
  { label: 'Kritiek', value: 'critical' },
  // Rijkshuisstijl
  { label: 'Lintblauw', value: 'lintblauw' },
  { label: 'Donkerblauw', value: 'donkerblauw' },
  { label: 'Hemelblauw', value: 'hemelblauw' },
  { label: 'Lichtblauw', value: 'lichtblauw' },
  { label: 'Paars', value: 'paars' },
  { label: 'Violet', value: 'violet' },
  { label: 'Robijnrood', value: 'robijnrood' },
  { label: 'Roze', value: 'roze' },
  { label: 'Rood', value: 'rood' },
  { label: 'Oranje', value: 'oranje' },
  { label: 'Donkergeel', value: 'donkergeel' },
  { label: 'Geel', value: 'geel' },
  { label: 'Donkerbruin', value: 'donkerbruin' },
  { label: 'Bruin', value: 'bruin' },
  { label: 'Donkergroen', value: 'donkergroen' },
  { label: 'Groen', value: 'groen' },
  { label: 'Mosgroen', value: 'mosgroen' },
  { label: 'Mintgroen', value: 'mintgroen' },
];
