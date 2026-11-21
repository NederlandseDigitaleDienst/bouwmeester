import { useState, useEffect } from 'react';
import { Modal } from '@/components/common/Modal';
import { FormModalFooter } from '@/components/common/FormModalFooter';
import { CascadingOrgSelect } from '@/components/common/CascadingOrgSelect';
import { useUpdatePlacement } from '@/hooks/useOrgPlacements';
import type { OrgPlacementRequest } from '@/api/orgPlacements';

interface PlacementEditModalProps {
  open: boolean;
  onClose: () => void;
  request: OrgPlacementRequest | null;
}

export function PlacementEditModal({ open, onClose, request }: PlacementEditModalProps) {
  const [selectedEenheidId, setSelectedEenheidId] = useState('');
  const updatePlacement = useUpdatePlacement();

  useEffect(() => {
    if (request) {
      setSelectedEenheidId(request.organisatie_eenheid_id);
    }
  }, [request]);

  const handleSubmit = (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!request || !selectedEenheidId) return;
    updatePlacement.mutate(
      { id: request.id, data: { organisatie_eenheid_id: selectedEenheidId } },
      { onSuccess: onClose },
    );
  };

  const isUnchanged = selectedEenheidId === request?.organisatie_eenheid_id;

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Team wijzigen"
      size="md"
      footer={
        <FormModalFooter
          onCancel={onClose}
          onSubmit={handleSubmit}
          submitLabel="Opslaan"
          isLoading={updatePlacement.isPending}
          disabled={!selectedEenheidId || isUnchanged}
        />
      }
    >
      <nldd-container gap="16">
        <nldd-text size="sm" color="secondary">
          <p>
            Kies de juiste eenheid voor het teamverzoek van{' '}
            <strong>{request?.person_naam}</strong>.
          </p>
        </nldd-text>
        <CascadingOrgSelect
          value={selectedEenheidId}
          onChange={setSelectedEenheidId}
          label="Organisatie-eenheid"
        />
      </nldd-container>
    </Modal>
  );
}
