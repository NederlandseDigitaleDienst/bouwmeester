import { useState, useCallback, useEffect } from 'react';
import { Modal } from '@/components/common/Modal';
import { Input } from '@/components/common/Input';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { FormModalFooter } from '@/components/common/FormModalFooter';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { PersonQuickCreateForm } from '@/components/people/PersonQuickCreateForm';
import { useCreateTask, useWorkTypes } from '@/hooks/useTasks';
import { useOpdrachten } from '@/hooks/useOpdrachten';
import { useTaskFormOptions } from '@/hooks/useTaskFormOptions';
import { useEnumOptions } from '@/hooks/useEnumOptions';
import {
  TaskPriority,
  TASK_PRIORITY_LABELS,
} from '@/types';

interface TaskCreateFormProps {
  open: boolean;
  onClose: () => void;
  nodeId?: string;
  /** Casus van de bovenliggende taak, voor subtaken op een casus. */
  casusId?: string;
  parentId?: string;
  opdrachtId?: string;
  /** Stakeholder person IDs in order: eigenaar first, then betrokken */
  stakeholderPersonIds?: string[];
}

export function TaskCreateForm({
  open,
  onClose,
  nodeId,
  casusId,
  parentId,
  opdrachtId,
  stakeholderPersonIds,
}: TaskCreateFormProps) {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [priority, setPriority] = useState<string>(TaskPriority.NORMAAL);
  const [dueDate, setDueDate] = useState('');
  const [selectedNodeId, setSelectedNodeId] = useState(nodeId ?? '');
  const [assigneeId, setAssigneeId] = useState('');
  const [organisatieEenheidId, setOrganisatieEenheidId] = useState('');
  const [workType, setWorkType] = useState('');
  const [selectedOpdrachtId, setSelectedOpdrachtId] = useState(opdrachtId ?? '');

  const priorityOptions = useEnumOptions(TaskPriority, TASK_PRIORITY_LABELS);
  const { data: workTypes = [] } = useWorkTypes();
  const workTypeOptions = workTypes.map((wt) => ({ value: wt, label: wt }));
  const { data: opdrachten = [] } = useOpdrachten();
  const opdrachtOptions = opdrachten.map((o) => ({ value: o.id, label: o.titel, description: o.type }));

  // Reset form state when dialog opens + AI suggestion
  useEffect(() => {
    if (open) {
      setTitle('');
      setDescription('');
      setPriority(TaskPriority.NORMAAL);
      setDueDate('');
      setSelectedNodeId(nodeId ?? '');
      setAssigneeId('');
      setOrganisatieEenheidId('');
      setWorkType('');
      setSelectedOpdrachtId(opdrachtId ?? '');

      // Pre-select assignee from stakeholders
      if (stakeholderPersonIds && stakeholderPersonIds.length > 0) {
        setAssigneeId(stakeholderPersonIds[0]);
      }
    }
  }, [open, nodeId, opdrachtId, stakeholderPersonIds]);

  const createTask = useCreateTask();
  const {
    nodeOptions, personOptions, eenheidOptions,
    handleCreateNode, handleCreatePerson,
    personCreateName, showPersonCreate, setShowPersonCreate,
  } = useTaskFormOptions();

  const handlePersonCreated = useCallback((personId: string) => {
    setAssigneeId(personId);
  }, []);

  const handleSubmit = async (e?: React.FormEvent) => {
    e?.preventDefault();
    if (!title.trim() || (!selectedNodeId && !parentId)) return;

    await createTask.mutateAsync({
      title: title.trim(),
      description: description.trim() || undefined,
      priority: priority as TaskPriority,
      due_date: dueDate || undefined,
      node_id: selectedNodeId || nodeId || undefined,
      casus_id: casusId,
      assignee_id: assigneeId || undefined,
      organisatie_eenheid_id: organisatieEenheidId || undefined,
      parent_id: parentId || undefined,
      opdracht_id: selectedOpdrachtId || undefined,
      work_type: workType.trim() || undefined,
    });

    onClose();
  };

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title={parentId ? 'Subtaak aanmaken' : 'Nieuwe taak aanmaken'}
        footer={
          <FormModalFooter
            onCancel={onClose}
            onSubmit={handleSubmit}
            submitLabel="Aanmaken"
            isLoading={createTask.isPending}
            disabled={!title.trim() || (!selectedNodeId && !parentId)}
          />
        }
      >
        {/*
          Submit/cancel live in Modal's `footer` (FormModalFooter), a sibling
          of `children` — not a descendant of nldd-form, so nldd-form-actions
          cannot reach them from here. Wrapping the body still gets autofill
          and label-alignment inheritance for the fields.
        */}
        <nldd-form>
        <form onSubmit={handleSubmit}>
        <nldd-container gap="16">
          <Input
            label="Titel"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Wat moet er gebeuren?"
            required
            autoFocus
          />

          <RichTextFormField label="Beschrijving" value={description} onChange={setDescription} />

          <CreatableSelect
            label="Node"
            value={selectedNodeId}
            onChange={setSelectedNodeId}
            options={nodeOptions}
            placeholder="Koppel aan een node..."
            onCreate={handleCreateNode}
            createLabel="Nieuw aanmaken"
            required={!parentId}
            error={!selectedNodeId && !parentId && createTask.isError ? 'Node is verplicht' : undefined}
          />

          <CreatableSelect
            label="Verantwoordelijke eenheid"
            value={organisatieEenheidId}
            onChange={setOrganisatieEenheidId}
            options={eenheidOptions}
            placeholder="Selecteer een eenheid..."
          />

          <CreatableSelect
            label="Toegewezen aan"
            value={assigneeId}
            onChange={setAssigneeId}
            options={personOptions}
            placeholder="Selecteer een persoon..."
            onCreate={handleCreatePerson}
            createLabel="Nieuw aanmaken"
          />

          <CreatableSelect
            label="Prioriteit"
            value={priority}
            onChange={setPriority}
            options={priorityOptions}
            searchable={false}
          />

          <CreatableSelect
            label="Werktype"
            value={workType}
            onChange={setWorkType}
            options={workTypeOptions}
            placeholder="bijv. Analyse, Overleg, Review..."
            onCreate={async (text) => { setWorkType(text); return text; }}
            createLabel="Nieuw werktype"
            onClear={() => setWorkType('')}
          />

          <CreatableSelect
            label="Opdracht"
            value={selectedOpdrachtId}
            onChange={setSelectedOpdrachtId}
            options={opdrachtOptions}
            placeholder="Koppel aan een opdracht..."
            onClear={() => setSelectedOpdrachtId('')}
          />

          <Input
            label="Deadline"
            type="date"
            value={dueDate}
            onChange={(e) => setDueDate(e.target.value)}
          />
        </nldd-container>
        </form>
        </nldd-form>
      </Modal>

      <PersonQuickCreateForm
        open={showPersonCreate}
        onClose={() => setShowPersonCreate(false)}
        initialName={personCreateName}
        onCreated={handlePersonCreated}
      />
    </>
  );
}
