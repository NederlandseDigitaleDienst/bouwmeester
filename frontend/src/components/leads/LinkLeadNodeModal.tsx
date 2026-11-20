import { useState, useCallback, useMemo } from 'react';

import { Modal } from '@/components/common/Modal';
import { CreatableSelect, type SelectOption } from '@/components/common/CreatableSelect';
import { useDebounce } from '@/hooks/useDebounce';
import { useNodes, useCreateNode } from '@/hooks/useNodes';
import { usePeople, useCreatePerson } from '@/hooks/usePeople';
import { useLead, useLinkLeadNode, useAddLeadContact } from '@/hooks/useLeads';
import { useToast } from '@/contexts/ToastContext';
import { NodeType, NODE_TYPE_LABELS, LEAD_CONTACT_ROL_LABELS } from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';

const CONTACT_ROLLEN: SelectOption[] = Object.entries(LEAD_CONTACT_ROL_LABELS).map(
  ([value, label]) => ({ value, label }),
);

const NEW_NODE_TYPE_OPTIONS: SelectOption[] = [
  NodeType.NOTITIE,
  NodeType.DOSSIER,
  NodeType.DOEL,
  NodeType.PROBLEEM,
  NodeType.INSTRUMENT,
  NodeType.MAATREGEL,
  NodeType.BELEIDSKADER,
  NodeType.BELEIDSOPTIE,
  NodeType.EFFECT,
  NodeType.OVERIG,
].map((value) => ({ value, label: NODE_TYPE_LABELS[value] }));

interface Props {
  leadId: string | null;
  onClose: () => void;
}

export function LinkLeadNodeModal({ leadId, onClose }: Props) {
  const { data: lead } = useLead(leadId);
  const [nodeQuery, setNodeQuery] = useState('');
  const debouncedNodeQuery = useDebounce(nodeQuery, 200);
  const { data: nodes = [] } = useNodes(undefined, debouncedNodeQuery);
  const { data: people = [] } = usePeople();
  const createNode = useCreateNode();
  const createPerson = useCreatePerson();
  const linkNode = useLinkLeadNode();
  const addContact = useAddLeadContact();
  const { showError, showWarning } = useToast();

  const [nodeId, setNodeId] = useState('');
  const [newNodeType, setNewNodeType] = useState<NodeType>(NodeType.NOTITIE);
  const [personId, setPersonId] = useState('');
  const [rol, setRol] = useState('contactpersoon');

  const existingContactPersonIds = useMemo(
    () => new Set((lead?.contacts ?? []).map((c) => c.person_id)),
    [lead],
  );

  const nodeOptions: SelectOption[] = useMemo(
    () =>
      nodes.map((n) => ({
        value: n.id,
        label: n.title,
        description: NODE_TYPE_LABELS[n.node_type as NodeType] ?? n.node_type?.replace(/_/g, ' '),
      })),
    [nodes],
  );

  const personOptions: SelectOption[] = useMemo(
    () =>
      people
        .filter((p) => p.is_active && !existingContactPersonIds.has(p.id))
        .map((p) => ({
          value: p.id,
          label: p.naam,
          description: p.functie ?? undefined,
        })),
    [people, existingContactPersonIds],
  );

  const handleCreateNode = useCallback(
    async (text: string): Promise<string | null> => {
      const node = await createNode.mutateAsync({ title: text, node_type: newNodeType });
      return node.id;
    },
    [createNode, newNodeType],
  );

  const handleCreatePerson = useCallback(
    async (name: string): Promise<string | null> => {
      const result = await createPerson.mutateAsync({ naam: name, force: true });
      return result?.id ?? null;
    },
    [createPerson],
  );

  const resetAndClose = useCallback(() => {
    setNodeId('');
    setNewNodeType(NodeType.NOTITIE);
    setPersonId('');
    setRol('contactpersoon');
    setNodeQuery('');
    onClose();
  }, [onClose]);

  const handleSubmit = useCallback(async () => {
    if (!leadId || !nodeId) return;
    try {
      await linkNode.mutateAsync({ leadId, nodeId });
    } catch {
      // useMutationWithError already shows a toast; keep modal open for retry
      return;
    }
    if (personId) {
      if (existingContactPersonIds.has(personId)) {
        showWarning('Persoon was al gekoppeld als externe contactpersoon');
      } else {
        try {
          await addContact.mutateAsync({ leadId, personId, rol });
        } catch {
          showError('Node gekoppeld, maar externe contactpersoon kon niet worden toegevoegd');
          // Keep modal open so the user sees the partial result and can retry the contact
          return;
        }
      }
    }
    resetAndClose();
  }, [
    leadId,
    nodeId,
    personId,
    rol,
    existingContactPersonIds,
    linkNode,
    addContact,
    resetAndClose,
    showError,
    showWarning,
  ]);

  const submitting = linkNode.isPending || addContact.isPending;

  return (
    <Modal
      open={!!leadId}
      onClose={resetAndClose}
      title="Node koppelen"
      size="sm"
      footer={
        <>
          <NlddButton variant="secondary" onClick={resetAndClose} text="Annuleren" />
          <NlddButton onClick={handleSubmit} loading={submitting} disabled={!nodeId} text="Koppelen" />
        </>
      }
    >
      <nldd-container gap="16">
        <CreatableSelect
          label="Node"
          value={nodeId}
          onChange={setNodeId}
          options={nodeOptions}
          placeholder="Zoek of maak een node..."
          onCreate={handleCreateNode}
          createLabel={`Nieuwe ${NODE_TYPE_LABELS[newNodeType].toLowerCase()} aanmaken`}
          onQueryChange={setNodeQuery}
          filterLocally={false}
          required
        />
        {!nodeId && (
          <CreatableSelect
            label="Type bij nieuwe node"
            value={newNodeType}
            onChange={(v) => setNewNodeType(v as NodeType)}
            options={NEW_NODE_TYPE_OPTIONS}
            placeholder="Selecteer een type..."
            searchable={false}
          />
        )}
        {/* nldd-divider has no top/bottom margin of its own; the gaps on
            either side come from the surrounding nldd-container, not from
            the divider itself. */}
        <nldd-divider />
        <nldd-container gap="12">
          <nldd-text size="xs" color="secondary">
            <p>Optioneel: voeg ook een externe contactpersoon toe aan deze lead.</p>
          </nldd-text>
          <CreatableSelect
            label="Externe contactpersoon"
            value={personId}
            onChange={setPersonId}
            options={personOptions}
            placeholder="Zoek of maak een persoon..."
            onCreate={handleCreatePerson}
            createLabel="Nieuwe persoon aanmaken"
            onClear={personId ? () => setPersonId('') : undefined}
          />
          {personId && (
            <CreatableSelect
              label="Rol"
              value={rol}
              onChange={setRol}
              options={CONTACT_ROLLEN}
              placeholder="Selecteer een rol..."
              searchable={false}
            />
          )}
        </nldd-container>
      </nldd-container>
    </Modal>
  );
}
