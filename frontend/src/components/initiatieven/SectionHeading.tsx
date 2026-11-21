import { Icon } from '@/components/nldd/Icon';

/**
 * A section heading on an initiatief tab: an icon and an `<h3>` in
 * `nldd-title`'s slot. The page's `<h2>` is the initiatief's name.
 *
 * Most callers stack this above their content, so it keeps the container
 * default of `width: full`. A caller that puts a button beside it wraps it in
 * `row-fill` itself; doing that here gave the others a `min-width: 0` with
 * nothing to fill, and the headings collapsed to one letter per line.
 */
export function SectionHeading({ icon, text }: { icon: string; text: string }) {
  return (
    <nldd-container layout="row" gap="6" vertical-alignment="center">
      <Icon name={icon} size="sm" />
      <nldd-title size="display-4">
        <h3>{text}</h3>
      </nldd-title>
    </nldd-container>
  );
}
