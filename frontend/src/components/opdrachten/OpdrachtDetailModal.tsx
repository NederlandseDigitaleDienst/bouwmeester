import { useState, useMemo } from 'react';
import { useNavigate } from 'react-router-dom';
import { Modal } from '@/components/common/Modal';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { Badge } from '@/components/common/Badge';
import { DetailSection } from '@/components/common/DetailSection';
import { DetailMetadataGrid } from '@/components/common/DetailMetadataGrid';
import { RelatedItemsList } from '@/components/common/RelatedItemsList';
import { DetailModalFooter } from '@/components/common/DetailModalFooter';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { Icon } from '@/components/nldd/Icon';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { NlddActionText } from '@/components/nldd/NlddLink';

/** `SyncStatus` -> the design system's five semantic roles. */
const SYNC_STATUS_TAG_COLOR: Record<SyncStatus, 'success' | 'warning' | 'accent' | 'critical'> = {
  synced: 'success',
  pending_push: 'warning',
  pending_pull: 'accent',
  conflict: 'critical',
  error: 'critical',
};

/** Small "matched by AI" indicator, shown next to a member/eenheid name. */
function AiMatchedTag({ reason, confidence }: { reason?: string | null; confidence?: number | null }) {
  return (
    <nldd-tag
      text="AI"
      icon="sparkles"
      color="warning"
      size="sm"
      title={reason ? `${reason} (${Math.round((confidence ?? 0) * 100)}%)` : 'Door AI gematcht'}
    />
  );
}
import { FccDataSection } from './FccDataSection';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { Select } from '@/components/common/Select';
import { OpdrachtForm } from './OpdrachtForm';
import { TaskCreateForm } from '@/components/tasks/TaskCreateForm';
import {
  useOpdracht, useDeleteOpdracht,
  useAddOpdrachtMember, useRemoveOpdrachtMember, useUpdateOpdrachtMemberRole,
  useAddOpdrachtEenheid, useRemoveOpdrachtEenheid, useUpdateOpdrachtEenheidRol,
  useMatchOpdrachtContacts,
} from '@/hooks/useOpdrachten';
import { useTasksByOpdracht } from '@/hooks/useTasks';
import { usePeople } from '@/hooks/usePeople';
import { useOrganisatieFlat } from '@/hooks/useOrganisatie';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { useOpdrachtDetail } from '@/contexts/OpdrachtDetailContext';
import {
  OPDRACHT_TYPE_LABELS,
  OPDRACHT_STATUS_LABELS,
  OPDRACHT_STATUS_COLORS,
  OPDRACHT_TYPE_COLORS,
  OPDRACHT_CONTACT_ROL_LABELS,
  KOSTENSOORT_LABELS,
  NODE_TYPE_COLORS,
  SYNC_STATUS_LABELS,
  OpdrachtType,
  OpdrachtStatus,
  Kostensoort,
  TaskStatus,
  type NodeType,
  type SyncStatus,
} from '@/types';
import { formatCurrency, calculateUtilization } from '@/utils/format';
import { NlddButton } from '@/components/nldd/NlddButton';

interface OpdrachtDetailModalProps {
  opdrachtId: string | null;
  open: boolean;
  onClose: () => void;
}

export function OpdrachtDetailModal({ opdrachtId, open, onClose }: OpdrachtDetailModalProps) {
  const { data: opdracht, isLoading } = useOpdracht(opdrachtId ?? undefined);
  const { data: tasks = [] } = useTasksByOpdracht(opdrachtId);
  const deleteMutation = useDeleteOpdracht();
  const navigate = useNavigate();
  const { openNodeDetail } = useNodeDetail();
  const { openTaskDetail } = useTaskDetail();
  const { opdrachtParentLabel } = useOpdrachtDetail();
  const [showEdit, setShowEdit] = useState(false);
  const [showTaskCreate, setShowTaskCreate] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [addMemberValue, setAddMemberValue] = useState('');
  const [addEenheidValue, setAddEenheidValue] = useState('');

  // Member/eenheid hooks
  const { data: allPeople = [] } = usePeople();
  const { data: allEenheden = [] } = useOrganisatieFlat();
  const addMemberMutation = useAddOpdrachtMember();
  const removeMemberMutation = useRemoveOpdrachtMember();
  const updateMemberRoleMutation = useUpdateOpdrachtMemberRole();
  const addEenheidMutation = useAddOpdrachtEenheid();
  const removeEenheidMutation = useRemoveOpdrachtEenheid();
  const updateEenheidRolMutation = useUpdateOpdrachtEenheidRol();
  const matchContactsMutation = useMatchOpdrachtContacts();

  const members = opdracht?.members ?? [];
  const eenheden = opdracht?.eenheden ?? [];

  const availablePeopleOptions = useMemo(() => {
    const memberIds = new Set(members.map((m) => m.person_id));
    return allPeople
      .filter((p) => !memberIds.has(p.id) && !p.is_agent)
      .map((p) => ({ value: p.id, label: p.naam }));
  }, [allPeople, members]);

  const availableEenheidOptions = useMemo(() => {
    const linkedIds = new Set(eenheden.map((e) => e.eenheid_id));
    return allEenheden
      .filter((e) => !linkedIds.has(e.id))
      .map((e) => ({ value: e.id, label: e.naam }));
  }, [allEenheden, eenheden]);

  if (!open) return null;

  if (showEdit && opdracht) {
    return (
      <Modal
        open={open}
        onClose={() => { setShowEdit(false); onClose(); }}
        title="Opdracht bewerken"
        size="lg"
      >
        <OpdrachtForm
          opdracht={opdracht}
          onClose={() => setShowEdit(false)}
          onSuccess={() => setShowEdit(false)}
        />
      </Modal>
    );
  }

  const budget = Number(opdracht?.budget) || 0;
  const gerealiseerd = Number(opdracht?.gerealiseerd) || 0;
  const uitnutting = calculateUtilization(opdracht?.budget, opdracht?.gerealiseerd);

  const handleDelete = async () => {
    if (!opdrachtId) return;
    try {
      await deleteMutation.mutateAsync(opdrachtId);
      setShowDeleteConfirm(false);
      onClose();
    } catch {
      setError('Fout bij verwijderen van opdracht.');
    }
  };

  const accentColor = opdracht ? OPDRACHT_TYPE_COLORS[opdracht.type as OpdrachtType] : undefined;

  const handleAddMember = async (personId: string) => {
    if (!opdrachtId || !personId) return;
    try {
      await addMemberMutation.mutateAsync({ opdrachtId, personId });
      setAddMemberValue('');
    } catch {
      // Refusals are shown as a toast by useMutationWithError.
    }
  };

  const handleRemoveMember = async (personId: string) => {
    if (!opdrachtId) return;
    try {
      await removeMemberMutation.mutateAsync({ opdrachtId, personId });
    } catch {
      // Refusals are shown as a toast by useMutationWithError.
    }
  };

  const handleUpdateMemberRole = async (personId: string, rol: string) => {
    if (!opdrachtId) return;
    try {
      await updateMemberRoleMutation.mutateAsync({ opdrachtId, personId, rol });
    } catch {
      // Refusals are shown as a toast by useMutationWithError.
    }
  };

  const handleAddEenheid = async (eenheidId: string) => {
    if (!opdrachtId || !eenheidId) return;
    try {
      await addEenheidMutation.mutateAsync({ opdrachtId, eenheidId });
      setAddEenheidValue('');
    } catch {
      // Refusals are shown as a toast by useMutationWithError.
    }
  };

  const handleRemoveEenheid = async (eenheidId: string) => {
    if (!opdrachtId) return;
    try {
      await removeEenheidMutation.mutateAsync({ opdrachtId, eenheidId });
    } catch {
      // Refusals are shown as a toast by useMutationWithError.
    }
  };

  const handleUpdateEenheidRol = async (eenheidId: string, rol: string) => {
    if (!opdrachtId) return;
    try {
      await updateEenheidRolMutation.mutateAsync({ opdrachtId, eenheidId, rol });
    } catch {
      // Refusals are shown as a toast by useMutationWithError.
    }
  };

  const handleMatchContacts = async () => {
    if (!opdrachtId) return;
    await matchContactsMutation.mutateAsync(opdrachtId);
  };

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title={isLoading ? 'Laden...' : opdracht?.titel ?? 'Opdracht niet gevonden'}
        size="lg"
        accentColor={accentColor}
        headerIcon={<Icon name="clipboard-bullet-list" size="lg" />}
        entityLabel={opdracht ? (OPDRACHT_TYPE_LABELS[opdracht.type as OpdrachtType] || opdracht.type) : undefined}
        backLabel={opdrachtParentLabel ?? undefined}
        onBack={opdrachtParentLabel ? onClose : undefined}
        footer={
          <DetailModalFooter
            onClose={onClose}
            actions={
              <>
                <NlddButton
                  variant="secondary"
                  size="sm"
                  startIcon="pencil"
                  onClick={() => setShowEdit(true)}
                  disabled={!opdracht}
                  text="Bewerken"
                />
                <NlddButton
                  variant="destructive"
                  size="sm"
                  startIcon="trash"
                  onClick={() => setShowDeleteConfirm(true)}
                  disabled={!opdracht}
                  text="Verwijderen"
                />
              </>
            }
          />
        }
      >
        {isLoading ? (
          <LoadingSpinner padding="16" text="Laden..." />
        ) : !opdracht ? (
          <nldd-inline-dialog icon="question-mark-circle" text="Opdracht niet gevonden." />
        ) : (
          <nldd-container gap="20">
            {/* Error feedback */}
            {error && <nldd-banner variant="critical" size="sm" text={error} />}

            {/* Type + status + sync badges */}
            <nldd-container layout="wrap" gap="8" vertical-alignment="center">
              <Badge color={OPDRACHT_TYPE_COLORS[opdracht.type as OpdrachtType] || 'coolgray'}>
                {OPDRACHT_TYPE_LABELS[opdracht.type as OpdrachtType] || opdracht.type}
              </Badge>
              <Badge color={OPDRACHT_STATUS_COLORS[opdracht.status as OpdrachtStatus] || 'coolgray'}>
                {OPDRACHT_STATUS_LABELS[opdracht.status as OpdrachtStatus] || opdracht.status}
              </Badge>
              {opdracht.sync_status && (
                <nldd-tag
                  text={`FCC: ${SYNC_STATUS_LABELS[opdracht.sync_status as SyncStatus] || opdracht.sync_status}`}
                  color={SYNC_STATUS_TAG_COLOR[opdracht.sync_status as SyncStatus] ?? 'neutral'}
                  size="sm"
                />
              )}
            </nldd-container>

            {/* Description */}
            {opdracht.beschrijving && (
              <DetailSection title="Beschrijving">
                <RichTextDisplay content={opdracht.beschrijving} />
              </DetailSection>
            )}

            {/* Financial hero */}
            {budget > 0 && (
              <nldd-container layout="wrap" gap="32" vertical-alignment="bottom">
                <div className="hug hug-stack hug-gap-2">
                  <nldd-text size="xs" weight="medium" color="secondary">Budget</nldd-text>
                  <nldd-text size="lg" weight="bold">{formatCurrency(opdracht.budget)}</nldd-text>
                </div>
                {uitnutting !== null && (
                  <div className="hug hug-stack hug-gap-2">
                    <nldd-text size="xs" weight="medium" color="secondary">Uitnutting</nldd-text>
                    <nldd-text size="lg" weight="bold">{uitnutting.toFixed(1)}%</nldd-text>
                  </div>
                )}
                {gerealiseerd > 0 && (
                  <div className="hug hug-stack hug-gap-2">
                    <nldd-text size="xs" weight="medium" color="secondary">Gerealiseerd</nldd-text>
                    <nldd-text size="lg" weight="bold">{formatCurrency(opdracht.gerealiseerd)}</nldd-text>
                  </div>
                )}
              </nldd-container>
            )}
            {uitnutting !== null && (
              <nldd-progress-bar value={Math.min(uitnutting, 100)} max={100} size="sm" value-display="none" />
            )}

            {/* Details + Financieel grid */}
            <nldd-container layout="grid" gap="24">
              <nldd-container gap="12">
                <nldd-title size={6}><h2>Details</h2></nldd-title>
                <DetailMetadataGrid
                  items={[
                    { label: 'Begrotingsjaar', value: opdracht.begrotingsjaar },
                    {
                      label: 'Instrument',
                      value: opdracht.instrument ? (
                        <NlddActionText
                          text={opdracht.instrument.title}
                          onClick={() => openNodeDetail(opdracht.instrument!.id, opdracht.titel)}
                        />
                      ) : undefined,
                    },
                    {
                      label: 'Opdrachtnemer',
                      value: opdracht.opdrachtnemer ? (
                        <NlddActionText
                          text={opdracht.opdrachtnemer.afkorting || opdracht.opdrachtnemer.naam}
                          onClick={() => { onClose(); navigate('/externe-organisaties'); }}
                        />
                      ) : undefined,
                    },
                    {
                      label: 'Opdrachtgever',
                      value: opdracht.opdrachtgever ? (
                        <NlddActionText
                          text={opdracht.opdrachtgever.naam}
                          onClick={() => { onClose(); navigate('/organisatie'); }}
                        />
                      ) : undefined,
                    },
                    {
                      label: 'Verantwoordelijke',
                      value: opdracht.verantwoordelijke ? (
                        <NlddActionText
                          text={opdracht.verantwoordelijke.naam}
                          onClick={() => { onClose(); navigate('/people'); }}
                        />
                      ) : undefined,
                    },
                    { label: 'Referentie', value: opdracht.referentie },
                    {
                      label: 'Kostensoort',
                      value: opdracht.kostensoort
                        ? KOSTENSOORT_LABELS[opdracht.kostensoort as Kostensoort] || opdracht.kostensoort
                        : undefined,
                    },
                    {
                      label: 'Periode',
                      value: opdracht.startdatum
                        ? `${opdracht.startdatum} — ${opdracht.einddatum || '...'}`
                        : undefined,
                    },
                  ]}
                />
              </nldd-container>

              <nldd-container gap="12">
                <nldd-title size={6}><h2>Financieel</h2></nldd-title>
                <DetailMetadataGrid
                  items={[
                    {
                      label: 'Volgend jaar benodigd',
                      value: opdracht.volgend_jaar_benodigd != null ? formatCurrency(opdracht.volgend_jaar_benodigd) : undefined,
                    },
                    {
                      label: 'Volgend jaar aangevraagd',
                      value: opdracht.volgend_jaar_aangevraagd != null ? formatCurrency(opdracht.volgend_jaar_aangevraagd) : undefined,
                    },
                  ]}
                />
              </nldd-container>
            </nldd-container>

            {/* FCC data section */}
            {opdracht.fcc_id && opdracht.fcc_raw_data && (
              <FccDataSection
                data={opdracht.fcc_raw_data}
                funnelfase={opdracht.fcc_funnelfase}
                afdeling={opdracht.fcc_afdeling}
                portfolio={opdracht.fcc_portfolio}
                labels={opdracht.fcc_labels}
              />
            )}

            {/* Subsidie section */}
            {opdracht.type === 'subsidie' && (opdracht.subsidieregeling || opdracht.beschikking_nummer) && (
              <DetailSection title="Subsidie-gegevens" separated>
                <DetailMetadataGrid
                  items={[
                    { label: 'Subsidieregeling', value: opdracht.subsidieregeling },
                    { label: 'Beschikking nr.', value: opdracht.beschikking_nummer },
                  ]}
                />
              </DetailSection>
            )}

            {/* Linked nodes */}
            {opdracht.node_koppelingen && opdracht.node_koppelingen.length > 0 && (
              <DetailSection
                title="Gekoppelde nodes"
                icon={<Icon name="link" size="sm" />}
                count={opdracht.node_koppelingen.length}
                separated
              >
                <RelatedItemsList
                  items={opdracht.node_koppelingen.map((koppeling) => ({
                    id: koppeling.id,
                    label: koppeling.node_title || koppeling.node_id,
                    badge: koppeling.node_type ? {
                      text: koppeling.node_type,
                      color: NODE_TYPE_COLORS[koppeling.node_type as NodeType] ?? 'coolgray',
                      dot: true,
                    } : undefined,
                    secondaryText: koppeling.relatie_type ?? undefined,
                    onClick: () => openNodeDetail(koppeling.node_id, opdracht.titel),
                  }))}
                  maxVisible={5}
                  emptyLabel="Geen gekoppelde nodes"
                />
              </DetailSection>
            )}

            {/* Contactpersonen */}
            <DetailSection
              title="Contactpersonen"
              icon={<Icon name="users" size="sm" />}
              count={members.length}
              separated
              action={
                <NlddButton
                  variant="neutral-transparent"
                  size="sm"
                  startIcon="sparkles"
                  onClick={handleMatchContacts}
                  disabled={matchContactsMutation.isPending}
                  text={matchContactsMutation.isPending ? 'Matchen...' : 'Matchen'}
                />
              }
            >
              <nldd-container gap="12">
                {members.length > 0 && (
                  <nldd-list appearance="box-tinted" dividers="always">
                    {members.map((member) => (
                      <nldd-list-item key={member.person_id}>
                        {/* `full`: a fit-content cell measures its content, and a
                            container measures its parent, so the two wait on
                            each other and the name can end up zero wide. */}
                        <nldd-cell width="full">
                          <nldd-container layout="row" gap="8" vertical-alignment="center" min-width="0px">
                            <NlddActionText
                              text={member.person_naam}
                              onClick={() => { onClose(); navigate(`/people?highlight=${member.person_id}`); }}
                            />
                            {member.source === 'ai' && (
                              <AiMatchedTag reason={member.ai_reason} confidence={member.ai_confidence} />
                            )}
                          </nldd-container>
                        </nldd-cell>
                        <nldd-spacer-cell size="12" />
                        <nldd-cell width="144px">
                          <Select
                            value={member.rol}
                            aria-label="Rol van dit contact"
                            onChange={(e) => handleUpdateMemberRole(member.person_id, e.target.value)}
                            options={Object.entries(OPDRACHT_CONTACT_ROL_LABELS).map(([value, label]) => ({ value, label }))}
                          />
                        </nldd-cell>
                        <nldd-spacer-cell size="12" />
                        <NlddIconButton
                          icon="trash"
                          variant="neutral-transparent"
                          size="sm"
                          accessibleLabel="Verwijderen"
                          onClick={() => handleRemoveMember(member.person_id)}
                        />
                      </nldd-list-item>
                    ))}
                  </nldd-list>
                )}

                <nldd-container width="full">
                  <CreatableSelect
                    value={addMemberValue}
                    onChange={(val) => {
                      setAddMemberValue(val);
                      if (val) handleAddMember(val);
                    }}
                    options={availablePeopleOptions}
                    placeholder="Contactpersoon toevoegen..."
                    emptyMessage="Geen personen gevonden"
                  />
                </nldd-container>
              </nldd-container>
            </DetailSection>

            {/* Organisatie-eenheden */}
            <DetailSection
              title="Organisatie-eenheden"
              icon={<Icon name="apartment-building" size="sm" />}
              count={eenheden.length}
              separated
            >
              <nldd-container gap="12">
                {eenheden.length > 0 && (
                  <nldd-list appearance="box-tinted" dividers="always">
                    {eenheden.map((eenheid) => (
                      <nldd-list-item key={eenheid.eenheid_id}>
                        {/* `full`: a fit-content cell measures its content, and a
                            container measures its parent, so the two wait on
                            each other and the name can end up zero wide. */}
                        <nldd-cell width="full">
                          <nldd-container layout="row" gap="8" vertical-alignment="center" min-width="0px">
                            <NlddActionText
                              text={eenheid.eenheid_naam}
                              onClick={() => { onClose(); navigate(`/organisatie?highlight=${eenheid.eenheid_id}`); }}
                            />
                            {eenheid.source === 'ai' && (
                              <AiMatchedTag reason={eenheid.ai_reason} confidence={eenheid.ai_confidence} />
                            )}
                          </nldd-container>
                        </nldd-cell>
                        <nldd-spacer-cell size="12" />
                        <nldd-cell width="144px">
                          <Select
                            value={eenheid.rol}
                            aria-label="Rol van deze eenheid"
                            onChange={(e) => handleUpdateEenheidRol(eenheid.eenheid_id, e.target.value)}
                            options={Object.entries(OPDRACHT_CONTACT_ROL_LABELS).map(([value, label]) => ({ value, label }))}
                          />
                        </nldd-cell>
                        <nldd-spacer-cell size="12" />
                        <NlddIconButton
                          icon="trash"
                          variant="neutral-transparent"
                          size="sm"
                          accessibleLabel="Verwijderen"
                          onClick={() => handleRemoveEenheid(eenheid.eenheid_id)}
                        />
                      </nldd-list-item>
                    ))}
                  </nldd-list>
                )}

                <nldd-container width="full">
                  <CreatableSelect
                    value={addEenheidValue}
                    onChange={(val) => {
                      setAddEenheidValue(val);
                      if (val) handleAddEenheid(val);
                    }}
                    options={availableEenheidOptions}
                    placeholder="Eenheid toevoegen..."
                    emptyMessage="Geen eenheden gevonden"
                  />
                </nldd-container>
              </nldd-container>
            </DetailSection>

            {/* Tasks */}
            <DetailSection
              title="Taken"
              icon={<Icon name="check-list" size="sm" />}
              count={tasks.length}
              separated
              action={
                <NlddButton
                  variant="neutral-transparent"
                  size="sm"
                  startIcon="plus"
                  onClick={() => setShowTaskCreate(true)}
                  text="Taak"
                />
              }
            >
              <RelatedItemsList
                items={tasks.map((task) => ({
                  id: task.id,
                  label: task.title,
                  icon: task.status === TaskStatus.DONE
                    ? <nldd-icon icon="check-mark-circle" size="16" color="success" aria-hidden="true" />
                    : task.status === TaskStatus.IN_PROGRESS
                      ? <nldd-icon icon="clock" size="16" color="accent" aria-hidden="true" />
                      : <nldd-icon icon="circle" size="16" color="" aria-hidden="true" />,
                  secondaryText: task.assignee?.naam,
                  onClick: () => openTaskDetail(task.id, opdracht.titel),
                }))}
                maxVisible={5}
                emptyLabel="Geen taken gekoppeld"
              />
            </DetailSection>
          </nldd-container>
        )}
      </Modal>

      <TaskCreateForm
        open={showTaskCreate}
        onClose={() => setShowTaskCreate(false)}
        nodeId={opdracht?.instrument_id ?? undefined}
        opdrachtId={opdrachtId ?? undefined}
      />

      <ConfirmDialog
        open={showDeleteConfirm}
        onClose={() => setShowDeleteConfirm(false)}
        onConfirm={handleDelete}
        title="Opdracht verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
        loading={deleteMutation.isPending}
      >
        <nldd-rich-text>
          <p>Weet je zeker dat je <strong>{opdracht?.titel}</strong> wilt verwijderen?</p>
          {tasks.length > 0 && (
            <p>{tasks.length} gekoppelde taak/taken worden ook verwijderd.</p>
          )}
        </nldd-rich-text>
      </ConfirmDialog>
    </>
  );
}
