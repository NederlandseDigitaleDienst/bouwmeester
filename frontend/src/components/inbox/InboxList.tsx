import { InboxItemCard } from './InboxItem';
import { EmptyState } from '@/components/common/EmptyState';
import type { InboxItem } from '@/types';

interface InboxListProps {
  items: InboxItem[];
  onOpenThread?: (id: string) => void;
  onMarkRead?: (id: string) => void;
}

/**
 * One list, newest first, as the API returns it.
 *
 * It used to group by type, with a label per group. Almost everything is a
 * `notification`, so in practice that printed one label, "Meldingen (49)",
 * right under the "Meldingen" heading, and when there were several groups it
 * broke the one order an inbox should have: when did this come in. Each row
 * now carries its type as an icon instead.
 *
 * `box-base` because the page behind it is tinted: the rows sit on one card
 * with dividers, instead of 49 separate cards each with its own border and
 * shadow competing for attention.
 */
export function InboxList({ items, onOpenThread, onMarkRead }: InboxListProps) {
  if (items.length === 0) {
    return (
      <EmptyState
        icon="inbox"
        title="Inbox is leeg"
        description="Er zijn geen nieuwe berichten of meldingen. Zodra er activiteit is, verschijnt deze hier."
      />
    );
  }

  return (
    <nldd-list appearance="box-base" accessible-label="Meldingen">
      {items.map((item) => (
        <InboxItemCard key={item.id} item={item} onOpenThread={onOpenThread} onMarkRead={onMarkRead} />
      ))}
    </nldd-list>
  );
}
