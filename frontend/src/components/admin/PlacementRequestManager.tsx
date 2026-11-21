import { useState } from 'react';
import { usePendingPlacements, useApprovePlacement, useDenyPlacement } from '@/hooks/useOrgPlacements';
import { DIENSTVERBAND_LABELS } from '@/types';
import { PlacementEditModal } from './PlacementEditModal';
import type { OrgPlacementRequest } from '@/api/orgPlacements';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { EmptyState } from '@/components/common/EmptyState';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';

export function PlacementRequestManager() {
  const { data: requests, isLoading } = usePendingPlacements();
  const approveRequest = useApprovePlacement();
  const denyRequest = useDenyPlacement();
  const [confirmDenyId, setConfirmDenyId] = useState<string | null>(null);
  const [editingRequest, setEditingRequest] = useState<OrgPlacementRequest | null>(null);

  const handleApprove = (id: string) => {
    approveRequest.mutate(id);
  };

  const handleDeny = (id: string) => {
    denyRequest.mutate(id, {
      onSuccess: () => setConfirmDenyId(null),
    });
  };

  if (isLoading) {
    return <LoadingSpinner padding="32" />;
  }

  return (
    <nldd-container gap="16">
      <nldd-text size="sm" color="secondary">
        <p>
          Nieuwe medewerkers die zich aanmelden kiezen een team. Hieronder kun je hun teamverzoek
          goedkeuren of afwijzen.
        </p>
      </nldd-text>

      <nldd-table
        columns="minmax(160px,1fr) minmax(160px,1fr) 160px 140px 96px"
        sm-columns="1fr 1fr 96px"
        accessible-label="Openstaande teamverzoeken"
      >
        <nldd-table-row slot="header">
          <nldd-text-cell text="Naam" />
          <nldd-text-cell text="Team" />
          <nldd-text-cell text="Dienstverband" hide-below="md" />
          <nldd-text-cell text="Datum" hide-below="md" />
          <nldd-text-cell />
        </nldd-table-row>
        {requests?.map((req) => (
          <nldd-table-row key={req.id}>
            <nldd-title-cell text={req.person_naam} />
            <nldd-cell>
              <nldd-container layout="row" gap="6" vertical-alignment="center">
                <nldd-text size="sm"><p>{req.eenheid_naam}</p></nldd-text>
                <NlddIconButton
                  icon="pencil"
                  accessibleLabel="Team wijzigen"
                  variant="neutral-transparent"
                  size="xs"
                  onClick={() => setEditingRequest(req)}
                />
              </nldd-container>
            </nldd-cell>
            <nldd-text-cell
              text={DIENSTVERBAND_LABELS[req.dienstverband] || req.dienstverband}
              color="secondary"
              hide-below="md"
            />
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
            <nldd-cell>
              {confirmDenyId === req.id ? (
                <nldd-container layout="row" gap="4">
                  <NlddButton
                    text="Bevestig"
                    variant="destructive"
                    size="xs"
                    disabled={denyRequest.isPending}
                    onClick={() => handleDeny(req.id)}
                  />
                  <NlddButton
                    text="Annuleren"
                    variant="neutral-tinted"
                    size="xs"
                    onClick={() => setConfirmDenyId(null)}
                  />
                </nldd-container>
              ) : (
                <nldd-container layout="row" gap="4" vertical-alignment="center">
                  <NlddIconButton
                    icon="check-mark"
                    accessibleLabel="Goedkeuren"
                    variant="neutral-transparent"
                    size="sm"
                    onClick={() => handleApprove(req.id)}
                    disabled={approveRequest.isPending}
                  />
                  <NlddIconButton
                    icon="close"
                    accessibleLabel="Afwijzen"
                    variant="neutral-transparent"
                    size="sm"
                    onClick={() => setConfirmDenyId(req.id)}
                  />
                </nldd-container>
              )}
            </nldd-cell>
          </nldd-table-row>
        ))}
        <div slot="empty">
          <EmptyState icon="inbox" title="Geen openstaande teamverzoeken" />
        </div>
      </nldd-table>

      <PlacementEditModal
        open={!!editingRequest}
        onClose={() => setEditingRequest(null)}
        request={editingRequest}
      />
    </nldd-container>
  );
}
