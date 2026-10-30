import { useCallback, useRef } from 'react';
import { useNlddEvent } from '@/components/nldd/events';
import { isOverdue, formatDateShort } from '@/utils/dates';
import { LeadStage } from '@/types';
import type { Lead } from '@/types';

interface LeadCardProps {
  lead: Lead;
  onClick: () => void;
}

export function LeadCard({ lead, onClick }: LeadCardProps) {
  const ref = useRef<HTMLElement>(null);
  const handleClick = useCallback(() => onClick(), [onClick]);
  useNlddEvent(ref, 'click', handleClick);

  const overdue = lead.next_action_date && isOverdue(lead.next_action_date);
  const isInbox = lead.stage === LeadStage.INBOX;
  const contacts = lead.contact_names ?? [];
  const hasFunnelScores =
    lead.score_strategisch != null &&
    lead.score_politiek != null &&
    lead.score_positie != null;

  return (
    <nldd-card ref={ref} button accessible-label={lead.title}>
      <nldd-container gap="6" padding="12">
        <nldd-text size="sm" weight="medium" className="line-clamp-2">
          {lead.title}
        </nldd-text>

        {lead.organization && (
          <nldd-text size="xs" color="secondary" className="truncate">
            {lead.organisatie_eenheid?.naam ?? lead.organization}
          </nldd-text>
        )}

        {lead.tags.length > 0 && (
          <nldd-container layout="wrap" gap="4" style={{ maxHeight: '3.25rem', overflow: 'hidden' }}>
            {lead.tags.slice(0, 3).map((tag) => (
              <nldd-tag key={tag} text={tag} color="neutral" size="sm" />
            ))}
            {lead.tags.length > 3 && (
              <nldd-text size="xs" color="secondary">
                +{lead.tags.length - 3}
              </nldd-text>
            )}
          </nldd-container>
        )}

        <nldd-container layout="row" gap="8" vertical-alignment="center">
          {isInbox ? (
            lead.brought_by && (
              <nldd-text size="xs" color="secondary" className="truncate" style={{ maxWidth: '120px' }}>
                via {lead.brought_by.naam}
              </nldd-text>
            )
          ) : (
            <>
              {lead.assignee && (
                <nldd-text size="xs" color="secondary" className="truncate" style={{ maxWidth: '120px' }}>
                  {lead.assignee.naam}
                </nldd-text>
              )}
              {contacts.length > 0 && (
                <div className="hug hug-gap-2 hug-truncate" title={contacts.join(', ')}>
                  <nldd-icon icon="users" size="16" aria-hidden="true" />
                  <nldd-text size="xs" color="secondary">
                    {contacts[0]}
                    {contacts.length > 1 && ` +${contacts.length - 1}`}
                  </nldd-text>
                </div>
              )}
            </>
          )}

          {lead.next_action_date && (
            <div className="hug hug-gap-2">
              <nldd-icon icon="calendar" size="16" aria-hidden="true" />
              <nldd-text size="xs" color={overdue ? 'critical' : 'secondary'} weight={overdue ? 'medium' : 'regular'}>
                {formatDateShort(lead.next_action_date)}
              </nldd-text>
            </div>
          )}

          {lead.attachment_count > 0 && (
            <div className="hug hug-gap-2">
              <nldd-icon icon="paperclip" size="16" aria-hidden="true" />
              <nldd-text size="xs" color="secondary">{lead.attachment_count}</nldd-text>
            </div>
          )}

          {hasFunnelScores && (
            <nldd-text
              size="xs"
              color="secondary"
              title={`Strategisch ${lead.score_strategisch} · Politiek ${lead.score_politiek} · Positie ${lead.score_positie}`}
              style={{ fontVariantNumeric: 'tabular-nums' }}
            >
              {lead.score_strategisch}·{lead.score_politiek}·{lead.score_positie}
            </nldd-text>
          )}
        </nldd-container>
      </nldd-container>
    </nldd-card>
  );
}
