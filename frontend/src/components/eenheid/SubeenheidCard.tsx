import { Card } from '@/components/common/Card';
import { Icon } from '@/components/nldd/Icon';
import { formatOrganisatieType } from '@/types';
import type { EenheidSubeenheidStats } from '@/types';

interface SubeenheidCardProps {
  sub: EenheidSubeenheidStats;
  onSelect: (eenheidId: string) => void;
}

export function SubeenheidCard({ sub, onSelect }: SubeenheidCardProps) {
  return (
    <Card actionLabel={`Open ${sub.eenheid_naam}`} onClick={() => onSelect(sub.eenheid_id)}>
      <nldd-container layout="stack" gap="8">
        <nldd-container layout="row" gap="8" vertical-alignment="top" horizontal-alignment="left">
          <nldd-container layout="row" gap="8" vertical-alignment="center">
            <Icon name="apartment-building" size="md" />
            <nldd-container layout="stack" gap="0">
              <nldd-text weight="medium"><p>{sub.eenheid_naam}</p></nldd-text>
              <nldd-text size="xs" color="secondary">
                <p>{formatOrganisatieType(sub.eenheid_type)}</p>
              </nldd-text>
            </nldd-container>
          </nldd-container>
          {sub.overdue_count > 0 && (
            <nldd-tag
              text={String(sub.overdue_count)}
              icon="exclamation-triangle"
              color="critical"
              size="sm"
            />
          )}
        </nldd-container>
        {/* `wrap`, not `row`: three counts do not fit beside each other in a
            card on a phone, and a row squeezed "Open: 0" onto three lines
            while "Afgerond" ran past the card's edge. */}
        <nldd-container layout="wrap" gap="16">
          <nldd-text size="sm" color="secondary">
            <p>Open: {sub.open_count}</p>
          </nldd-text>
          <nldd-text size="sm" color="secondary">
            <p>In uitvoering: {sub.in_progress_count}</p>
          </nldd-text>
          <nldd-text size="sm" color="secondary">
            <p>Afgerond: {sub.done_count}</p>
          </nldd-text>
        </nldd-container>
      </nldd-container>
    </Card>
  );
}
