import type { ReactNode } from 'react';
import { Badge } from './Badge';
import { NlddListItemButton } from '@/components/nldd/NlddLink';
import { NlddButton } from '@/components/nldd/NlddButton';
import type { EntityColor } from '@/types';

interface RelatedItem {
  id: string;
  label: string;
  badge?: { text: string; color: EntityColor; dot?: boolean };
  secondaryText?: string;
  icon?: ReactNode;
  onClick: () => void;
}

interface RelatedItemsListProps {
  items: RelatedItem[];
  maxVisible?: number;
  onShowAll?: () => void;
  showAllLabel?: string;
  emptyLabel?: string;
}

function ItemRow({ item }: { item: RelatedItem }) {
  // No hover-revealed arrow: the row announces itself by being a button, and a
  // hint that only exists on hover never reaches a keyboard or a touch screen.
  return (
    <NlddListItemButton onClick={item.onClick} size="sm">
      {item.icon && <nldd-cell width="fit-content">{item.icon}</nldd-cell>}
      {item.badge && (
        <nldd-cell width="fit-content">
          <Badge color={item.badge.color} dot={item.badge.dot}>
            {item.badge.text}
          </Badge>
        </nldd-cell>
      )}
      <nldd-text-cell text={item.label} />
      {item.secondaryText && (
        <nldd-text-cell
          text={item.secondaryText}
          color="secondary"
          width="fit-content"
          horizontal-alignment="right"
        />
      )}
    </NlddListItemButton>
  );
}

export function RelatedItemsList({
  items,
  maxVisible = 5,
  onShowAll,
  showAllLabel,
  emptyLabel = 'Geen items',
}: RelatedItemsListProps) {
  if (items.length === 0) {
    return (
      <nldd-text size="sm" color="secondary">
        {emptyLabel}
      </nldd-text>
    );
  }

  const visible = items.slice(0, maxVisible);
  const hasMore = items.length > maxVisible;

  return (
    <nldd-container gap="4">
      <nldd-list appearance="simple" accessible-label="Gerelateerde items">
        {visible.map((item) => (
          <ItemRow key={item.id} item={item} />
        ))}
      </nldd-list>
      {hasMore &&
        (onShowAll ? (
          <NlddButton
            text={showAllLabel ?? `Bekijk alle ${items.length} items`}
            variant="accent-transparent"
            size="sm"
            onClick={onShowAll}
          />
        ) : (
          <nldd-text size="xs" color="secondary">
            +{items.length - maxVisible} meer
          </nldd-text>
        ))}
    </nldd-container>
  );
}
