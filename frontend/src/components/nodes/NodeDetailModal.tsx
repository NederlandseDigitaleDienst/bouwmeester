import { useState } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { Modal } from '@/components/common/Modal';
import { Badge } from '@/components/common/Badge';
import { Icon } from '@/components/nldd/Icon';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { ReferencesList } from '@/components/common/ReferencesList';
import { DetailSection } from '@/components/common/DetailSection';
import { DetailMetadataGrid } from '@/components/common/DetailMetadataGrid';
import { RelatedItemsList } from '@/components/common/RelatedItemsList';
import { DetailModalFooter } from '@/components/common/DetailModalFooter';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { NodeEditForm } from './NodeEditForm';
import { TaskCreateForm } from '@/components/tasks/TaskCreateForm';
import { useNode, useNodeStakeholders, useNodeNeighbors, useNodeParlementairItem, useDeleteNode } from '@/hooks/useNodes';
import { useNodeTags } from '@/hooks/useTags';
import { useQuery } from '@tanstack/react-query';
import { getTasks } from '@/api/tasks';
import {
  NODE_TYPE_COLORS,
  NODE_STATUS_LABELS,
  STAKEHOLDER_ROL_LABELS,
  TaskStatus,
  type NodeType,
  type NodeStatus,
} from '@/types';
import { useVocabulary } from '@/contexts/VocabularyContext';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import { formatDateLong } from '@/utils/dates';
import { NlddButton } from '@/components/nldd/NlddButton';

/**
 * Icon per node type, for the modal's header. `nldd-icon`'s closed set has no
 * "target"/"crosshair" or "landmark"/"government building" glyph, so `doel`
 * and `politieke_input` map to the nearest honest neighbour:
 *   doel             -> flag (a goal you work toward)
 *   politieke_input   -> apartment-building (same glyph Sidebar uses for
 *                        the organisation nav item, i.e. an institution)
 */
const NODE_TYPE_ICONS: Record<string, React.ReactNode> = {
  dossier: <Icon name="folder-open" size="lg" />,
  doel: <Icon name="flag" size="lg" />,
  instrument: <Icon name="screwdriver-wrench" size="lg" />,
  beleidskader: <Icon name="book" size="lg" />,
  maatregel: <Icon name="shield" size="lg" />,
  politieke_input: <Icon name="apartment-building" size="lg" />,
  probleem: <Icon name="exclamation-triangle" size="lg" />,
  effect: <Icon name="chart-x-y-axis-line" size="lg" />,
  beleidsoptie: <Icon name="git-branch" size="lg" />,
  bron: <Icon name="file-text" size="lg" />,
};

interface NodeDetailModalProps {
  nodeId: string | null;
  open: boolean;
  onClose: () => void;
}

export function NodeDetailModal({ nodeId, open, onClose }: NodeDetailModalProps) {
  const { data: node, isLoading } = useNode(nodeId ?? undefined);
  const { data: stakeholders } = useNodeStakeholders(nodeId ?? undefined);
  const { data: neighbors } = useNodeNeighbors(nodeId ?? undefined);
  const { data: nodeTags } = useNodeTags(nodeId ?? undefined);
  const { data: tasks } = useQuery({
    queryKey: ['tasks', 'list', { node_id: nodeId }],
    queryFn: () => getTasks({ node_id: nodeId! }),
    enabled: !!nodeId,
  });
  const { data: parlementairItem } = useNodeParlementairItem(
    nodeId ?? undefined,
    node?.node_type,
  );
  const [showEdit, setShowEdit] = useState(false);
  const [showTaskCreate, setShowTaskCreate] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const deleteNode = useDeleteNode();
  const navigate = useNavigate();
  const location = useLocation();
  const { nodeLabel, nodeAltLabel } = useVocabulary();
  const { openTaskDetail } = useTaskDetail();
  const { openNodeDetail, nodeParentLabel } = useNodeDetail();

  const handleDelete = async () => {
    if (!nodeId) return;
    await deleteNode.mutateAsync(nodeId);
    setShowDeleteConfirm(false);
    onClose();
  };

  const hasRelated = (neighbors && neighbors.length > 0) || (tasks && tasks.length > 0);

  if (!open) return null;

  if (showEdit && node) {
    return (
      <NodeEditForm
        open
        onClose={() => {
          setShowEdit(false);
          onClose();
        }}
        node={node}
      />
    );
  }

  const eigenaren = stakeholders?.filter((s) => s.rol === 'eigenaar') ?? [];
  const otherStakeholders = stakeholders?.filter((s) => s.rol !== 'eigenaar') ?? [];

  const openTasks = tasks?.filter(
    (t) => t.status === TaskStatus.OPEN || t.status === TaskStatus.IN_PROGRESS,
  ) ?? [];
  const doneTasks = tasks?.filter(
    (t) => t.status === TaskStatus.DONE || t.status === TaskStatus.CANCELLED,
  ) ?? [];

  const accentColor = node ? NODE_TYPE_COLORS[node.node_type as NodeType] : undefined;

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title={isLoading ? 'Laden...' : node?.title ?? 'Node niet gevonden'}
        size="lg"
        accentColor={accentColor}
        headerIcon={node ? NODE_TYPE_ICONS[node.node_type] : undefined}
        entityLabel={node ? nodeLabel(node.node_type) : undefined}
        backLabel={nodeParentLabel ?? undefined}
        onBack={nodeParentLabel ? onClose : undefined}
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
                  disabled={!node}
                  text="Bewerken"
                />
                <NlddButton
                  variant="secondary"
                  size="sm"
                  startIcon="external-link"
                  onClick={() => {
                    onClose();
                    navigate(`/nodes/${nodeId}`, { state: { fromCorpus: location.pathname + location.search } });
                  }}
                  disabled={!node}
                  text="Openen"
                />
                <NlddButton
                  variant="destructive"
                  size="sm"
                  startIcon="trash"
                  onClick={() => setShowDeleteConfirm(true)}
                  disabled={!node}
                  text="Verwijderen"
                />
              </>
            }
          />
        }
      >
        {isLoading ? (
          <LoadingSpinner padding="16" />
        ) : !node ? (
          <nldd-container layout="row" horizontal-alignment="center" vertical-alignment="center" padding="16">
            <nldd-text size="sm" color="secondary">Node niet gevonden.</nldd-text>
          </nldd-container>
        ) : (
          <nldd-container gap="20">
            {/* Type, status, edge count badges */}
            <nldd-container layout="wrap" gap="8" vertical-alignment="center">
              <Badge color={NODE_TYPE_COLORS[node.node_type] ?? 'coolgray'} dot title={nodeAltLabel(node.node_type)}>
                {nodeLabel(node.node_type)}
              </Badge>
              {node.status && <Badge color="coolgray">{NODE_STATUS_LABELS[node.status as NodeStatus] ?? node.status}</Badge>}
              {node.edge_count != null && (
                <div className="hug">
                  <nldd-icon icon="link" size="16" aria-hidden="true" />
                  <nldd-text size="sm" color="secondary">{node.edge_count} verbindingen</nldd-text>
                </div>
              )}
              {parlementairItem?.document_url && (
                <nldd-link
                  href={parlementairItem.document_url}
                  target="_blank"
                  text="tweedekamer.nl"
                  start-icon="external-link"
                />
              )}
            </nldd-container>

            {/* Eigenaar / stakeholders compact row */}
            {stakeholders && stakeholders.length > 0 && (
              <nldd-container layout="row" gap="16" vertical-alignment="top">
                {/* Grow, not hug: the content is containers and tags, and a
                    container adds nothing to a shrink-to-fit parent's width. */}
                {eigenaren.length > 0 && (
                  <nldd-container width="fit-content" className="row-fill" gap="8">
                    <nldd-container layout="row" gap="4" vertical-alignment="center">
                      <nldd-icon icon="users" size="16" aria-hidden="true" />
                      <nldd-title size={6}><h2>Eigenaar</h2></nldd-title>
                    </nldd-container>
                    <nldd-container layout="wrap" gap="6">
                      {eigenaren.map((s) => (
                        <nldd-tag key={s.id} text={s.person.naam} color="accent" />
                      ))}
                    </nldd-container>
                  </nldd-container>
                )}
                {otherStakeholders.length > 0 && (
                  <nldd-container width="fit-content" className="row-fill" gap="8">
                    <nldd-title size={6}><h2>Betrokkenen</h2></nldd-title>
                    <nldd-container layout="wrap" gap="6">
                      {otherStakeholders.slice(0, 6).map((s) => (
                        <nldd-tag
                          key={s.id}
                          color="neutral"
                          text={`${s.person.naam} (${STAKEHOLDER_ROL_LABELS[s.rol] ?? s.rol})`}
                        />
                      ))}
                      {otherStakeholders.length > 6 && (
                        <nldd-tag color="neutral" text={`+${otherStakeholders.length - 6}`} />
                      )}
                    </nldd-container>
                  </nldd-container>
                )}
              </nldd-container>
            )}

            {/* Tags */}
            {nodeTags && nodeTags.length > 0 && (
              <nldd-container gap="6">
                <nldd-container layout="row" gap="4" vertical-alignment="center">
                  <nldd-icon icon="tag" size="16" aria-hidden="true" />
                  <nldd-title size={6}><h2>Tags</h2></nldd-title>
                </nldd-container>
                <nldd-container layout="wrap" gap="6">
                  {nodeTags.map((nt) => (
                    <nldd-tag key={nt.id} text={nt.tag.name} color="neutral" />
                  ))}
                </nldd-container>
              </nldd-container>
            )}

            {/* Description */}
            {node.description && (
              <DetailSection title="Beschrijving">
                <RichTextDisplay content={node.description} />
              </DetailSection>
            )}

            {/* Connected nodes */}
            {neighbors && neighbors.length > 0 && (
              <DetailSection
                title="Verbonden nodes"
                icon={<Icon name="link" size="sm" />}
                count={neighbors.length}
                separated
              >
                <RelatedItemsList
                  items={neighbors.map((neighbor) => ({
                    id: neighbor.id,
                    label: neighbor.title,
                    badge: {
                      text: nodeLabel(neighbor.node_type),
                      color: NODE_TYPE_COLORS[neighbor.node_type] ?? 'coolgray',
                      dot: true,
                    },
                    onClick: () => openNodeDetail(neighbor.id, node.title),
                  }))}
                  maxVisible={5}
                  onShowAll={() => {
                    onClose();
                    navigate(`/nodes/${nodeId}?tab=connections`, { state: { fromCorpus: location.pathname + location.search } });
                  }}
                  showAllLabel={`Bekijk alle ${neighbors.length} verbindingen`}
                />
              </DetailSection>
            )}

            {/* Tasks */}
            <DetailSection
              title="Taken"
              icon={<Icon name="check-list" size="sm" />}
              count={openTasks.length}
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
                items={openTasks.map((task) => ({
                  id: task.id,
                  label: task.title,
                  icon: task.status === TaskStatus.DONE
                    ? <nldd-icon icon="check-mark-circle" size="16" color="success" aria-hidden="true" />
                    : task.status === TaskStatus.IN_PROGRESS
                      ? <nldd-icon icon="clock" size="16" color="accent" aria-hidden="true" />
                      : <nldd-icon icon="circle" size="16" color="" aria-hidden="true" />,
                  secondaryText: task.assignee?.naam,
                  onClick: () => openTaskDetail(task.id, node.title),
                }))}
                maxVisible={5}
                onShowAll={() => {
                  onClose();
                  navigate(`/nodes/${nodeId}?tab=tasks`, { state: { fromCorpus: location.pathname + location.search } });
                }}
                showAllLabel={`Bekijk alle ${openTasks.length} open taken`}
                emptyLabel="Geen taken"
              />
              {doneTasks.length > 0 && (
                <nldd-container padding-top="4">
                  <nldd-text size="xs" color="secondary">{doneTasks.length} afgerond</nldd-text>
                </nldd-container>
              )}
            </DetailSection>

            {/* References */}
            <ReferencesList targetId={node.id} />

            {/* Metadata footer */}
            <DetailMetadataGrid
              separated
              items={[
                {
                  label: 'Aangemaakt',
                  value: formatDateLong(node.created_at),
                  icon: <Icon name="calendar" size="md" />,
                },
                {
                  label: 'Laatst bijgewerkt',
                  value: formatDateLong(node.updated_at),
                  icon: <Icon name="calendar" size="md" />,
                },
              ]}
            />
          </nldd-container>
        )}
      </Modal>

      {node && (
        <TaskCreateForm
          open={showTaskCreate}
          onClose={() => setShowTaskCreate(false)}
          nodeId={nodeId ?? undefined}
          stakeholderPersonIds={
            stakeholders
              ?.sort((a, b) => (a.rol === 'eigenaar' ? -1 : b.rol === 'eigenaar' ? 1 : 0))
              .map((s) => s.person.id)
          }
        />
      )}

      <ConfirmDialog
        open={showDeleteConfirm}
        onClose={() => setShowDeleteConfirm(false)}
        onConfirm={handleDelete}
        title="Node verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
        loading={deleteNode.isPending}
      >
        <nldd-rich-text>
          <p>Weet je zeker dat je <strong>{node?.title}</strong> wilt verwijderen?</p>
          {hasRelated && (
            <ul>
              {neighbors && neighbors.length > 0 && (
                <li>{neighbors.length} verbinding(en) worden verwijderd</li>
              )}
              {tasks && tasks.length > 0 && (
                <li>{tasks.length} gekoppelde taak/taken worden verwijderd</li>
              )}
            </ul>
          )}
        </nldd-rich-text>
      </ConfirmDialog>
    </>
  );
}
