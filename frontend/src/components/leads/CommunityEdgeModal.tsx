import { useState, useCallback, useMemo } from 'react';
import type { Connection } from 'reactflow';
import { useQueryClient } from '@tanstack/react-query';

import { Modal } from '@/components/common/Modal';
import { CreatableSelect, type SelectOption } from '@/components/common/CreatableSelect';
import { useAddLeadContact, useLinkLeadNode, useUpdateLead } from '@/hooks/useLeads';
import { useCreateEdge } from '@/hooks/useEdges';
import { useAddNodeStakeholder } from '@/hooks/useNodes';
import { useVocabulary } from '@/contexts/VocabularyContext';
import { EDGE_TYPE_VOCABULARY } from '@/vocabulary';
import { STAKEHOLDER_ROL_LABELS, LEAD_CONTACT_ROL_LABELS } from '@/types';
import { queryKeys } from '@/hooks/queryKeys';
import { routeConnection, type ConnectionRoute } from '@/utils/communityEdgeRouting';
import { NlddButton } from '@/components/nldd/NlddButton';

const CONTACT_ROLLEN: SelectOption[] = Object.entries(LEAD_CONTACT_ROL_LABELS).map(
  ([value, label]) => ({ value, label }),
);

const STAKEHOLDER_ROLLEN: SelectOption[] = Object.entries(STAKEHOLDER_ROL_LABELS).map(
  ([value, label]) => ({ value, label }),
);

interface Props {
  pendingConnection: Connection | null;
  onClose: () => void;
}

export function CommunityEdgeModal({ pendingConnection, onClose }: Props) {
  const queryClient = useQueryClient();
  const { edgeLabel: vocabEdgeLabel } = useVocabulary();

  // Mutations
  const addContact = useAddLeadContact();
  const linkNode = useLinkLeadNode();
  const updateLead = useUpdateLead();
  const createEdge = useCreateEdge();
  const addStakeholder = useAddNodeStakeholder();

  // Form state
  const [selectedRole, setSelectedRole] = useState('contactpersoon');
  const [selectedEdgeType, setSelectedEdgeType] = useState('');
  const [selectedStakeholderRole, setSelectedStakeholderRole] = useState('betrokken');

  const route: ConnectionRoute | null = useMemo(() => {
    if (!pendingConnection?.source || !pendingConnection?.target) return null;
    return routeConnection(pendingConnection.source, pendingConnection.target);
  }, [pendingConnection]);

  const edgeTypeOptions: SelectOption[] = useMemo(
    () =>
      Object.keys(EDGE_TYPE_VOCABULARY).map((key) => ({
        value: key,
        label: vocabEdgeLabel(key),
      })),
    [vocabEdgeLabel],
  );

  const isPending =
    addContact.isPending ||
    linkNode.isPending ||
    updateLead.isPending ||
    createEdge.isPending ||
    addStakeholder.isPending;

  const resetAndClose = useCallback(() => {
    setSelectedRole('contactpersoon');
    setSelectedEdgeType('');
    setSelectedStakeholderRole('betrokken');
    onClose();
  }, [onClose]);

  const handleSubmit = useCallback(async () => {
    if (!route || route.kind === 'invalid') return;

    try {
      switch (route.kind) {
        case 'lead_contact':
          await addContact.mutateAsync({
            leadId: route.leadId,
            personId: route.personId,
            rol: selectedRole,
          });
          break;

        case 'lead_node':
          await linkNode.mutateAsync({
            leadId: route.leadId,
            nodeId: route.nodeId,
          });
          break;

        case 'lead_org':
          await updateLead.mutateAsync({
            id: route.leadId,
            data: { organisatie_eenheid_id: route.orgId },
          });
          break;

        case 'corpus_edge':
          await createEdge.mutateAsync({
            from_node_id: route.fromNodeId,
            to_node_id: route.toNodeId,
            edge_type_id: selectedEdgeType,
          });
          await queryClient.invalidateQueries({ queryKey: queryKeys.leads.all });
          break;

        case 'node_stakeholder':
          await addStakeholder.mutateAsync({
            nodeId: route.nodeId,
            data: { person_id: route.personId, rol: selectedStakeholderRole },
          });
          await queryClient.invalidateQueries({ queryKey: queryKeys.leads.all });
          break;
      }

      resetAndClose();
    } catch {
      // useMutationWithError already shows a toast; keep modal open so the user can retry
    }
  }, [
    route,
    selectedRole,
    selectedEdgeType,
    selectedStakeholderRole,
    addContact,
    linkNode,
    updateLead,
    createEdge,
    addStakeholder,
    queryClient,
    resetAndClose,
  ]);

  if (!route) return null;

  const title = {
    lead_contact: 'Contact koppelen aan lead',
    lead_node: 'Beleidsnode koppelen aan lead',
    lead_org: 'Organisatie koppelen aan lead',
    corpus_edge: 'Verbinding aanmaken',
    node_stakeholder: 'Betrokkene toevoegen',
    invalid: 'Verbinding niet mogelijk',
  }[route.kind];

  const canSubmit = (() => {
    if (route.kind === 'invalid') return false;
    if (route.kind === 'corpus_edge') return !!selectedEdgeType;
    return true;
  })();

  return (
    <Modal
      open={!!pendingConnection}
      onClose={resetAndClose}
      title={title}
      size="sm"
      footer={
        route.kind === 'invalid' ? (
          <NlddButton variant="secondary" onClick={resetAndClose} text="Sluiten" />
        ) : (
          <>
            <NlddButton variant="secondary" onClick={resetAndClose} text="Annuleren" />
            <NlddButton onClick={handleSubmit} loading={isPending} disabled={!canSubmit} text="Toevoegen" />
          </>
        )
      }
    >
      {route.kind === 'invalid' && (
        <nldd-text size="sm" color="secondary"><p>{route.reason}</p></nldd-text>
      )}

      {route.kind === 'lead_contact' && (
        <CreatableSelect
          label="Rol"
          value={selectedRole}
          onChange={setSelectedRole}
          options={CONTACT_ROLLEN}
          placeholder="Selecteer een rol..."
          searchable={false}
        />
      )}

      {route.kind === 'lead_node' && (
        <nldd-text size="sm" color="secondary">
          <p>Wil je deze beleidsnode koppelen aan de lead?</p>
        </nldd-text>
      )}

      {route.kind === 'lead_org' && (
        <nldd-text size="sm" color="secondary">
          <p>
            Wil je deze organisatie koppelen aan de lead? Een eventueel eerder gekoppelde organisatie
            wordt vervangen.
          </p>
        </nldd-text>
      )}

      {route.kind === 'corpus_edge' && (
        <CreatableSelect
          label="Type verbinding"
          value={selectedEdgeType}
          onChange={setSelectedEdgeType}
          options={edgeTypeOptions}
          placeholder="Selecteer een type..."
          required
        />
      )}

      {route.kind === 'node_stakeholder' && (
        <CreatableSelect
          label="Rol"
          value={selectedStakeholderRole}
          onChange={setSelectedStakeholderRole}
          options={STAKEHOLDER_ROLLEN}
          placeholder="Selecteer een rol..."
          searchable={false}
        />
      )}
    </Modal>
  );
}
