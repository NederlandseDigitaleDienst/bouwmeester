import type { ReactNode } from 'react';

interface MetadataItem {
  label: string;
  value: ReactNode;
  icon?: ReactNode;
  span?: 1 | 2;
}

interface DetailMetadataGridProps {
  items: MetadataItem[];
  separated?: boolean;
}

/**
 * The label/value pairs in a detail view, two per row.
 *
 * `nldd-container layout="grid"` carries the columns and the gap. An item that
 * asks for the full width gets its own single-column container rather than a
 * col-span, since the grid has no span attribute: a row of its own reads the
 * same and needs no escape hatch.
 */
export function DetailMetadataGrid({ items, separated = false }: DetailMetadataGridProps) {
  const visibleItems = items.filter((item) => item.value != null && item.value !== '');
  if (visibleItems.length === 0) return null;

  const renderItem = (item: MetadataItem) => (
    <nldd-container key={item.label} gap="4">
      <nldd-text size="xs" weight="bold" color="secondary">
        <p>{item.label}</p>
      </nldd-text>
      <nldd-container layout="row" gap="6" vertical-alignment="center">
        {item.icon}
        <nldd-text size="sm" color="secondary">
          {item.value}
        </nldd-text>
      </nldd-container>
    </nldd-container>
  );

  // The grid has no span attribute, so a full-width item interrupts the
  // two-column run: the pairs before it, then the item on its own, then the
  // pairs after it. That keeps the source order, which is the order someone
  // reads the record in.
  const runs: { full: boolean; items: MetadataItem[] }[] = [];
  for (const item of visibleItems) {
    const full = item.span === 2;
    const last = runs[runs.length - 1];
    if (last && last.full === full) last.items.push(item);
    else runs.push({ full, items: [item] });
  }

  return (
    <nldd-container gap="16">
      {separated && <nldd-divider />}
      {runs.map((run, index) =>
        run.full ? (
          <nldd-container key={index} gap="16">
            {run.items.map(renderItem)}
          </nldd-container>
        ) : (
          <nldd-container
            key={index}
            layout="grid"
            column-count={2}
            sm-column-count={1}
            gap="16"
          >
            {run.items.map(renderItem)}
          </nldd-container>
        ),
      )}
    </nldd-container>
  );
}
