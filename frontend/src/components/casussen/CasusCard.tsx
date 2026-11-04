import { useCallback, useRef } from 'react';
import { useNlddEvent } from '@/components/nldd/events';
import type { Casus, Startvraag } from '@/types';
import { CasusSoortTags } from './CasusSoorten';
import { kaartjeLabels } from './startvragen';

interface CasusCardProps {
  casus: Casus;
  onClick: () => void;
  /** De startvragen van het initiatief: wie "op het kaartje" staat, komt als tag. */
  vragen?: Startvraag[];
}

/**
 * Het casuskaartje. Anders dan een leadkaartje: geen scores en geen volgende
 * actie, wel trekker, de soorten, de antwoorden op de startvragen die op het
 * kaartje horen (instellingen).
 */
export function CasusCard({ casus, onClick, vragen = [] }: CasusCardProps) {
  const ref = useRef<HTMLElement>(null);
  const handleClick = useCallback(() => onClick(), [onClick]);
  useNlddEvent(ref, 'click', handleClick);

  const labels = kaartjeLabels(casus.startvoorwaarden, vragen);

  return (
    <nldd-card ref={ref} button accessible-label={casus.title}>
      <nldd-container gap="6" padding="12">
        <nldd-text size="sm" weight="medium" className="line-clamp-2">
          {casus.title}
        </nldd-text>
        {casus.organization && (
          <nldd-text size="xs" color="secondary" className="truncate">
            {casus.organization}
          </nldd-text>
        )}
        {(labels.length > 0 || (casus.soorten?.length ?? 0) > 0) && (
          <nldd-container layout="wrap" gap="4">
            {/* Eerst de soorten (tags uit de instellingen), dan de startvoorwaarden. */}
            <CasusSoortTags soorten={casus.soorten} />
            {labels.map((l, i) => (
              <nldd-tag key={`${i}-${l}`} text={l} color="neutral" size="sm" />
            ))}
          </nldd-container>
        )}
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <div className="hug hug-gap-2 hug-truncate">
            <nldd-icon icon="person" size="16" aria-hidden="true" />
            <nldd-text size="xs" color="secondary">
              {casus.trekker_naam ?? 'Geen trekker'}
              {casus.team_count > 1 && ` +${casus.team_count - 1}`}
            </nldd-text>
          </div>
        </nldd-container>
      </nldd-container>
    </nldd-card>
  );
}
