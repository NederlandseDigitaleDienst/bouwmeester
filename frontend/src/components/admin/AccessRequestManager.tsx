import { useRef, useState } from 'react';
import { useAccessRequests, useReviewAccessRequest } from '@/hooks/useAdmin';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { EmptyState } from '@/components/common/EmptyState';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';

const STATUS_COLOR = {
  pending: 'warning',
  approved: 'success',
  denied: 'critical',
} as const;

const STATUS_LABEL: Record<string, string> = {
  pending: 'In afwachting',
  approved: 'Goedgekeurd',
  denied: 'Afgewezen',
};

export function AccessRequestManager() {
  const [filter, setFilter] = useState<string>('pending');
  const { data: requests, isLoading } = useAccessRequests(filter || undefined);
  const reviewRequest = useReviewAccessRequest();
  const [denyId, setDenyId] = useState<string | null>(null);
  const [denyReason, setDenyReason] = useState('');
  const filterRef = useRef<HTMLElement>(null);
  const denyReasonRef = useRef<HTMLElement>(null);

  useNlddEvent(filterRef, 'change', (e) => setFilter(eventValue(e)));
  useNlddEvent(denyReasonRef, 'input', (e) => setDenyReason(eventValue(e)));

  const handleApprove = (id: string) => {
    reviewRequest.mutate({ id, action: 'approve' });
  };

  const handleDeny = (id: string) => {
    reviewRequest.mutate(
      { id, action: 'deny', deny_reason: denyReason || undefined },
      { onSuccess: () => { setDenyId(null); setDenyReason(''); } }
    );
  };

  if (isLoading) {
    return <LoadingSpinner padding="32" />;
  }

  return (
    <nldd-container gap="16">
      {/* Filter */}
      <nldd-toggle-button-group ref={filterRef} type="radio" accessible-label="Filter op status">
        <nldd-toggle-button text="In afwachting" value="pending" selected={filter === 'pending' ? true : undefined} />
        <nldd-toggle-button text="Alle" value="" selected={filter === '' ? true : undefined} />
      </nldd-toggle-button-group>

      {/* Request list */}
      <nldd-table
        columns="minmax(160px,1fr) minmax(200px,1fr) 140px 140px 96px"
        sm-columns="1fr 1fr 96px"
        accessible-label="Toegangsverzoeken"
      >
        <nldd-table-row slot="header">
          <nldd-text-cell text="Naam" />
          <nldd-text-cell text="E-mailadres" />
          <nldd-text-cell text="Datum" hide-below="md" />
          <nldd-text-cell text="Status" hide-below="md" />
          <nldd-text-cell />
        </nldd-table-row>
        {requests?.map((req) => (
          <nldd-table-row key={req.id}>
            <nldd-title-cell text={req.naam} />
            <nldd-text-cell text={req.email} />
            <nldd-text-cell
              text={new Date(req.requested_at).toLocaleDateString('nl-NL', {
                day: 'numeric',
                month: 'short',
                hour: '2-digit',
                minute: '2-digit',
              })}
              color="secondary"
              hide-below="md"
            />
            <nldd-cell hide-below="md">
              <nldd-tag text={STATUS_LABEL[req.status] ?? req.status} color={STATUS_COLOR[req.status as keyof typeof STATUS_COLOR] ?? 'neutral'} size="sm" />
            </nldd-cell>
            <nldd-cell>
              {req.status === 'pending' && (
                <>
                  {denyId === req.id ? (
                    <nldd-container gap="4">
                      <nldd-text-field
                        ref={denyReasonRef}
                        value={denyReason}
                        placeholder="Reden (optioneel)"
                        size="sm"
                        accessible-label="Reden voor afwijzen"
                      />
                      <nldd-container layout="row" gap="4">
                        <NlddButton
                          text="Afwijzen"
                          variant="destructive"
                          size="xs"
                          disabled={reviewRequest.isPending}
                          onClick={() => handleDeny(req.id)}
                        />
                        <NlddButton
                          text="Annuleren"
                          variant="neutral-tinted"
                          size="xs"
                          onClick={() => { setDenyId(null); setDenyReason(''); }}
                        />
                      </nldd-container>
                    </nldd-container>
                  ) : (
                    <nldd-container layout="row" gap="4" vertical-alignment="center">
                      <NlddIconButton
                        icon="check-mark"
                        accessibleLabel="Goedkeuren"
                        variant="neutral-transparent"
                        size="sm"
                        onClick={() => handleApprove(req.id)}
                        disabled={reviewRequest.isPending}
                      />
                      <NlddIconButton
                        icon="close"
                        accessibleLabel="Afwijzen"
                        variant="neutral-transparent"
                        size="sm"
                        onClick={() => { setDenyId(req.id); setDenyReason(''); }}
                      />
                    </nldd-container>
                  )}
                </>
              )}
              {req.status === 'denied' && req.deny_reason && (
                <nldd-text
                  size="xs"
                  color="secondary"
                  title={req.deny_reason}
                >
                  <p>
                    {req.deny_reason.length > 20 ? `${req.deny_reason.slice(0, 20)}...` : req.deny_reason}
                  </p>
                </nldd-text>
              )}
            </nldd-cell>
          </nldd-table-row>
        ))}
        <div slot="empty">
          <EmptyState
            icon="inbox"
            title={filter === 'pending' ? 'Geen openstaande verzoeken' : 'Geen verzoeken gevonden'}
            description={filter === 'pending' ? 'Bekijk "Alle" om eerder behandelde verzoeken te zien.' : undefined}
          />
        </div>
      </nldd-table>
    </nldd-container>
  );
}
