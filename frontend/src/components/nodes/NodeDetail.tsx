import { useState, useRef, useCallback } from 'react';
import { useNavigate, useLocation, useSearchParams } from 'react-router-dom';
import { Badge } from '@/components/common/Badge';
import { Card } from '@/components/common/Card';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { EmptyState } from '@/components/common/EmptyState';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { Select } from '@/components/common/Select';
import { Input } from '@/components/common/Input';
import { DetailMetadataGrid } from '@/components/common/DetailMetadataGrid';
import { FileUpload } from '@/components/common/FileUpload';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { PersonCardExpandable } from '@/components/people/PersonCardExpandable';
import { PersonQuickCreateForm } from '@/components/people/PersonQuickCreateForm';
import { Icon } from '@/components/nldd/Icon';
import { NlddActionText, NlddListItemButton } from '@/components/nldd/NlddLink';
import { useNlddEvent } from '@/components/nldd/events';
import { NodeEditForm } from './NodeEditForm';
import { EdgeList } from './EdgeList';
import { BeleidskompasPanel } from './beleidskompas/BeleidskompasPanel';
import { FinancieelOverzichtPanel } from '@/components/financieel/FinancieelOverzichtPanel';
import { TaskView } from '@/components/tasks/TaskView';
import { useNode, useNodeNeighbors, useNodeStakeholders, useDeleteNode, useNodeParlementairItem, useAddNodeStakeholder, useUpdateNodeStakeholder, useRemoveNodeStakeholder, useNodeTitleHistory, useNodeStatusHistory, useNodeBronDetail, useNodeBijlage } from '@/hooks/useNodes';
import { useTasks } from '@/hooks/useTasks';
import { usePeople } from '@/hooks/usePeople';
import { useNodeTags, useAddTagToNode, useRemoveTagFromNode, useTags } from '@/hooks/useTags';
import { useReferences } from '@/hooks/useMentions';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { NODE_TYPE_COLORS, NODE_STATUS_LABELS, STAKEHOLDER_ROL_LABELS, BRON_TYPE_LABELS, NodeType, type NodeStatus, formatFunctie, titleCase } from '@/types';
import { uploadBijlage, deleteBijlage, getBijlageDownloadUrl, updateNodeBronDetail } from '@/api/nodes';
import { useVocabulary } from '@/contexts/VocabularyContext';
import { useToast } from '@/contexts/ToastContext';
import { formatDate } from '@/utils/dates';
import { StakeholderTab } from '@/components/stakeholders/StakeholderTab';
import { NlddButton } from '@/components/nldd/NlddButton';

/** A single removable tag chip: `nldd-token` with its `dismiss` event bridged to React. */
function NlddTagToken({ text, onDismiss }: { text: string; onDismiss: () => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'dismiss', onDismiss);
  return <nldd-token ref={ref} text={text} control="dismiss" dismiss-text={`Verwijder tag ${text}`} />;
}

/** "13-02-2026 — heden" for an open record, both dates for a closed one. */
function historyPeriod(van: string, tot: string | null | undefined): string {
  return `${formatDate(van)} — ${tot ? formatDate(tot) : 'heden'}`;
}

type TabId = 'overview' | 'connections' | 'stakeholders' | 'tasks' | 'activity';

const tabs: { id: TabId; label: string }[] = [
  { id: 'overview', label: 'Overzicht' },
  { id: 'connections', label: 'Verbindingen' },
  { id: 'stakeholders', label: 'Betrokkenen' },
  { id: 'tasks', label: 'Taken' },
  { id: 'activity', label: 'Activiteit' },
];

interface NodeDetailProps {
  nodeId: string;
}

export function NodeDetail({ nodeId }: NodeDetailProps) {
  const navigate = useNavigate();
  const location = useLocation();
  const corpusUrl = (location.state as { fromCorpus?: string } | null)?.fromCorpus ?? '/corpus';
  const [searchParams, setSearchParams] = useSearchParams();
  const tabParam = searchParams.get('tab') as TabId | null;
  const activeTab: TabId = tabParam && tabs.some((t) => t.id === tabParam) ? tabParam : 'overview';
  const setActiveTab = useCallback((tab: TabId) => {
    setSearchParams(tab === 'overview' ? {} : { tab }, { replace: true });
  }, [setSearchParams]);
  const tabBarRef = useRef<HTMLElement>(null);
  const handleTabChange = useCallback(
    (event: Event) => {
      const item = (event as CustomEvent<{ item?: HTMLElement }>).detail?.item;
      const tabId = item?.dataset.tabId as TabId | undefined;
      if (tabId) setActiveTab(tabId);
    },
    [setActiveTab],
  );
  useNlddEvent(tabBarRef, 'tabchange', handleTabChange);
  const [showEditForm, setShowEditForm] = useState(false);
  const { data: node, isLoading, error } = useNode(nodeId);
  const { data: neighbors } = useNodeNeighbors(nodeId);
  const { data: nodeTasks } = useTasks({ node_id: nodeId });
  const { data: stakeholders } = useNodeStakeholders(nodeId);
  const deleteNode = useDeleteNode();
  const { data: nodeTags } = useNodeTags(nodeId);
  const addTag = useAddTagToNode();
  const removeTag = useRemoveTagFromNode();
  const { nodeLabel, nodeAltLabel } = useVocabulary();
  const { data: parlementairItem } = useNodeParlementairItem(nodeId, node?.node_type);
  const { data: bronDetail, refetch: refetchBronDetail } = useNodeBronDetail(nodeId, node?.node_type);
  const { data: bijlageInfo, refetch: refetchBijlage } = useNodeBijlage(nodeId, node?.node_type);
  const { data: references } = useReferences(nodeId);
  const { data: titleHistory } = useNodeTitleHistory(nodeId);
  const { data: statusHistory } = useNodeStatusHistory(nodeId);
  const { openTaskDetail } = useTaskDetail();
  const addStakeholder = useAddNodeStakeholder();
  const updateStakeholder = useUpdateNodeStakeholder();
  const removeStakeholder = useRemoveNodeStakeholder();
  const { data: allPeople } = usePeople();
  const { showError } = useToast();
  const [newStakeholderPersonId, setNewStakeholderPersonId] = useState('');
  const [newStakeholderRol, setNewStakeholderRol] = useState('betrokken');
  const [personCreateName, setPersonCreateName] = useState('');
  const [showPersonCreate, setShowPersonCreate] = useState(false);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [showBijlageDeleteConfirm, setShowBijlageDeleteConfirm] = useState(false);
  const [removeStakeholderId, setRemoveStakeholderId] = useState<{ id: string; naam: string } | null>(null);
  const [bronEditing, setBronEditing] = useState(false);
  const [bronType, setBronType] = useState('');
  const [bronAuteur, setBronAuteur] = useState('');
  const [bronPublicatieDatum, setBronPublicatieDatum] = useState('');
  const [bronUrl, setBronUrl] = useState('');
  const [bijlageUploading, setBijlageUploading] = useState(false);

  const { data: allTags } = useTags();
  const existingTagIds = new Set(nodeTags?.map((nt) => nt.tag.id) ?? []);

  const handleSelectTag = useCallback((tagId: string) => {
    addTag.mutate({ nodeId, data: { tag_id: tagId } });
  }, [addTag, nodeId]);

  if (isLoading) {
    return (
      <nldd-container padding="64">
        <LoadingSpinner />
      </nldd-container>
    );
  }

  if (error || !node) {
    return (
      <EmptyState
        title="Node niet gevonden"
        description="De gevraagde node bestaat niet of is verwijderd."
        action={
          <NlddButton variant="secondary" onClick={() => navigate('/corpus')} text="Terug naar corpus" />
        }
      />
    );
  }

  const color = NODE_TYPE_COLORS[node.node_type];

  const handleDelete = async () => {
    await deleteNode.mutateAsync(node.id);
    setShowDeleteConfirm(false);
    navigate('/corpus');
  };

  return (
    <nldd-container gap="24">
      {/* Back button and the node's own actions on one line, which wraps as
          a whole on a phone. The actions used to sit in the title's `end`
          slot, where a long title pushed them past the edge of the screen:
          all that showed of "Verwijder" was a sliver of red. */}
      <nldd-container layout="wrap" width="full" gap="8" vertical-alignment="center">
        {/* Both hug their content, so the line wraps once they no longer
            fit side by side. The link used to be row-fill, whose basis is 0:
            the line never wrapped and the link was squeezed instead. */}
        <div className="hug">
          <NlddButton
            variant="neutral-transparent"
            size="sm"
            text="Terug naar corpus"
            startIcon="arrow-left"
            onClick={() => navigate(corpusUrl)}
          />
        </div>
        <nldd-spacer direction="horizontal" size="flexible" />
        <div className="hug hug-gap-8">
          <NlddButton variant="secondary" size="sm" startIcon="pencil" onClick={() => setShowEditForm(true)} text="Bewerken" />
          <NlddButton
            variant="destructive"
            size="sm"
            startIcon="trash"
            onClick={() => setShowDeleteConfirm(true)}
            text="Verwijder"
          />
        </div>
      </nldd-container>

      {/* Header */}
      <nldd-container gap="8">
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <Badge color={color} dot title={nodeAltLabel(node.node_type)}>
            {nodeLabel(node.node_type)}
          </Badge>
          {node.status && <Badge color="coolgray">{NODE_STATUS_LABELS[node.status as NodeStatus] ?? node.status}</Badge>}
        </nldd-container>
        {/* h2, not h1: `nldd-top-title-bar` in the app header renders the
            page's h1 and nothing here anchors it away (`collapse-anchor` is
            unused across the app). Measured on this route: two visible h1s,
            "Bouwmeester" from the bar and this one, plus a level skip
            straight to the h3 section headings below. */}
        <nldd-title size={1}>
          <h2>{node.title}</h2>
        </nldd-title>
        {/* Each item as wide as its text, so they sit side by side while they
            fit. At the container's default 100% each took a line of its own. */}
        <nldd-container layout="wrap" gap="16" vertical-alignment="center">
          <div className="hug">
            <Icon name="calendar" size="xs" />
            <nldd-text size="xs" color="secondary">Aangemaakt: {formatDate(node.created_at)}</nldd-text>
          </div>
          <div className="hug">
            <Icon name="link" size="xs" />
            <nldd-text size="xs" color="secondary">{node.edge_count ?? 0} verbindingen</nldd-text>
          </div>
          {parlementairItem?.document_url && (
            <nldd-link
              href={parlementairItem.document_url}
              target="_blank"
              text="Bekijk op tweedekamer.nl"
              start-icon="external-link"
            />
          )}
        </nldd-container>
      </nldd-container>

      {/* Tabs */}
      <nldd-tab-bar ref={tabBarRef} variant="text" accessible-label="Node-secties">
        {tabs.map((tab) => (
          <nldd-tab-bar-item
            key={tab.id}
            text={tab.label}
            data-tab-id={tab.id}
            current={activeTab === tab.id ? true : undefined}
          />
        ))}
      </nldd-tab-bar>

      {/* Tab content */}
      <div>
        {activeTab === 'overview' && (
          <nldd-container gap="24">
            {/* Beleidskompas panel for dossier nodes */}
            {node.node_type === 'dossier' && (
              <BeleidskompasPanel
                nodeId={nodeId}
                stakeholderCount={stakeholders?.length ?? 0}
                onNavigateToStakeholders={() => setActiveTab('stakeholders')}
              />
            )}

            {/* Description */}
            <Card>
              <nldd-title size={3}><h3>Beschrijving</h3></nldd-title>
              <RichTextDisplay content={node.description} />
            </Card>

            {/* Financieel overzicht for instrument/maatregel/doel nodes */}
            {(node.node_type === NodeType.INSTRUMENT || node.node_type === NodeType.MAATREGEL || node.node_type === NodeType.DOEL) && (
              <Card>
                <nldd-title size={3}><h3>Financieel overzicht</h3></nldd-title>
                <FinancieelOverzichtPanel nodeId={nodeId} nodeType={node.node_type} />
              </Card>
            )}

            {/* Bron detail */}
            {node.node_type === NodeType.BRON && bronDetail && (
              <Card>
                <nldd-title size={3}>
                  <h3>Brongegevens</h3>
                  {!bronEditing && (
                    <span slot="end">
                      <NlddActionText
                        text="Bewerken"
                        size="xs"
                        onClick={() => {
                          setBronType(bronDetail.type);
                          setBronAuteur(bronDetail.auteur ?? '');
                          setBronPublicatieDatum(bronDetail.publicatie_datum ?? '');
                          setBronUrl(bronDetail.url ?? '');
                          setBronEditing(true);
                        }}
                      />
                    </span>
                  )}
                </nldd-title>
                {bronEditing ? (
                  <nldd-container gap="12">
                    <Select
                      label="Type"
                      value={bronType}
                      onChange={(e) => setBronType(e.target.value)}
                      options={Object.entries(BRON_TYPE_LABELS).map(([value, label]) => ({ value, label }))}
                    />
                    <Input
                      label="Auteur"
                      type="text"
                      value={bronAuteur}
                      onChange={(e) => setBronAuteur(e.target.value)}
                      placeholder="Naam auteur..."
                    />
                    <Input
                      label="Publicatiedatum"
                      type="date"
                      value={bronPublicatieDatum}
                      onChange={(e) => setBronPublicatieDatum(e.target.value)}
                    />
                    <Input
                      label="URL"
                      type="url"
                      value={bronUrl}
                      onChange={(e) => setBronUrl(e.target.value)}
                      placeholder="https://..."
                    />
                    <nldd-container layout="row" gap="8">
                      <NlddButton
                        size="sm"
                        onClick={async () => {
                          try {
                            await updateNodeBronDetail(nodeId, {
                              type: bronType,
                              auteur: bronAuteur || null,
                              publicatie_datum: bronPublicatieDatum || null,
                              url: bronUrl || null,
                            });
                            setBronEditing(false);
                            refetchBronDetail();
                          } catch (err) {
                            console.error('Fout bij opslaan brongegevens:', err);
                            showError('Fout bij opslaan brongegevens. Probeer het opnieuw.');
                          }
                        }}
                        text="Opslaan"
                      />
                      <NlddButton variant="secondary" size="sm" onClick={() => setBronEditing(false)} text="Annuleren" />
                    </nldd-container>
                  </nldd-container>
                ) : (
                  <DetailMetadataGrid
                    items={[
                      { label: 'Type', value: BRON_TYPE_LABELS[bronDetail.type] ?? bronDetail.type },
                      { label: 'Auteur', value: bronDetail.auteur },
                      {
                        label: 'Publicatiedatum',
                        value: bronDetail.publicatie_datum ? formatDate(bronDetail.publicatie_datum) : undefined,
                      },
                      {
                        label: 'URL',
                        span: 2,
                        value: bronDetail.url ? (
                          bronDetail.url.startsWith('http://') || bronDetail.url.startsWith('https://') ? (
                            <nldd-link href={bronDetail.url} target="_blank" text={bronDetail.url} start-icon="external-link" />
                          ) : (
                            <nldd-text size="md" color="secondary">{bronDetail.url}</nldd-text>
                          )
                        ) : undefined,
                      },
                    ]}
                  />
                )}
              </Card>
            )}

            {/* Bijlage */}
            {node.node_type === NodeType.BRON && (
              <Card>
                <nldd-title size={3}><h3>Bijlage</h3></nldd-title>
                {bijlageInfo ? (
                  <nldd-list appearance="box-tinted" dividers="never">
                    <nldd-list-item>
                      <nldd-icon-cell icon="file-text" />
                      <nldd-title-cell
                        text={bijlageInfo.bestandsnaam}
                        color={!bijlageInfo.bestand_beschikbaar ? 'critical' : undefined}
                        overline={
                          !bijlageInfo.bestand_beschikbaar
                            ? 'Bestand niet beschikbaar'
                            : bijlageInfo.bestandsgrootte >= 1024 * 1024
                              ? `${(bijlageInfo.bestandsgrootte / (1024 * 1024)).toFixed(1)} MB`
                              : `${(bijlageInfo.bestandsgrootte / 1024).toFixed(1)} KB`
                        }
                      />
                      {bijlageInfo.bestand_beschikbaar && (
                        <NlddIconButton
                          icon="download"
                          variant="neutral-transparent"
                          size="sm"
                          accessibleLabel="Downloaden"
                          onClick={() => window.open(getBijlageDownloadUrl(nodeId), '_blank')}
                        />
                      )}
                      <NlddIconButton
                        icon="trash"
                        variant="critical-transparent"
                        size="sm"
                        accessibleLabel="Verwijderen"
                        onClick={() => setShowBijlageDeleteConfirm(true)}
                      />
                    </nldd-list-item>
                  </nldd-list>
                ) : (
                  <FileUpload
                    accept=".pdf,.doc,.docx,.odt,.txt,.png,.jpg,.jpeg"
                    disabled={bijlageUploading}
                    label={bijlageUploading ? 'Uploaden...' : 'Sleep een bestand hierheen of klik om te uploaden (PDF, Word, ODT, TXT, PNG, JPEG, max. 20 MB)'}
                    onFileSelect={async (file) => {
                      setBijlageUploading(true);
                      try {
                        await uploadBijlage(nodeId, file);
                        refetchBijlage();
                      } catch (err) {
                        const msg = err instanceof Error ? err.message : 'Onbekende fout';
                        showError(`Upload mislukt: ${msg}`);
                      } finally {
                        setBijlageUploading(false);
                      }
                    }}
                  />
                )}
              </Card>
            )}

            {/* Tags */}
            <Card>
              <nldd-title size={3}><h3>Tags</h3></nldd-title>
              <nldd-container layout="wrap" gap="6" padding-bottom="12">
                {nodeTags?.map((nt) => (
                  <NlddTagToken
                    key={nt.id}
                    text={nt.tag.name}
                    onDismiss={() => removeTag.mutate({ nodeId, tagId: nt.tag.id })}
                  />
                ))}
                {(!nodeTags || nodeTags.length === 0) && (
                  <nldd-text size="xs" color="secondary">Geen tags</nldd-text>
                )}
              </nldd-container>
              {/* Add tag: search existing or create a new one */}
              <CreatableSelect
                value=""
                onChange={handleSelectTag}
                options={(allTags ?? [])
                  .filter((t) => !existingTagIds.has(t.id))
                  .map((t) => ({ value: t.id, label: t.name }))}
                placeholder="Tag zoeken of toevoegen..."
                onCreate={async (text) => {
                  addTag.mutate({ nodeId, data: { tag_name: text } });
                  return null;
                }}
              />
            </Card>

            {/* Verwijzingen (back-references from mentions) */}
            {references && references.length > 0 && (
              <Card>
                <nldd-title size={3}><h3>Verwijzingen ({references.length})</h3></nldd-title>
                <nldd-list appearance="box-tinted" dividers="never">
                  {references.map((ref) => (
                    <NlddListItemButton
                      key={`${ref.source_type}-${ref.source_id}`}
                      onClick={() => {
                        if (ref.source_type === 'node') navigate(`/nodes/${ref.source_id}`);
                        else if (ref.source_type === 'task') openTaskDetail(ref.source_id);
                      }}
                    >
                      <nldd-text-cell width="fit-content">
                        <Badge color="coolgray">
                          {ref.source_type === 'node' ? 'Node' : ref.source_type === 'task' ? 'Taak' : ref.source_type}
                        </Badge>
                      </nldd-text-cell>
                      <nldd-text-cell text={ref.source_title} />
                    </NlddListItemButton>
                  ))}
                </nldd-list>
              </Card>
            )}

            {/* Metadata */}
            {node.metadata && Object.keys(node.metadata).length > 0 && (
              <Card>
                <nldd-title size={3}><h3>Metadata</h3></nldd-title>
                <DetailMetadataGrid
                  items={Object.entries(node.metadata).map(([key, value]) => ({
                    label: titleCase(key.replace(/_/g, ' ')),
                    value: String(value),
                  }))}
                />
              </Card>
            )}

            {/* Stakeholders preview */}
            {stakeholders && stakeholders.length > 0 && (
              <nldd-container gap="12">
                <nldd-title size={3}><h3>Betrokkenen ({stakeholders.length})</h3></nldd-title>
                <nldd-container gap="8">
                  {stakeholders.slice(0, 5).map((s) => (
                    <PersonCardExpandable
                      key={s.id}
                      person={s.person}
                      extraBadge={
                        <Badge color="donkerblauw">
                          {STAKEHOLDER_ROL_LABELS[s.rol] ?? s.rol}
                        </Badge>
                      }
                    />
                  ))}
                  {stakeholders.length > 5 && (
                    <NlddActionText
                      text={`Bekijk alle ${stakeholders.length} betrokkenen`}
                      size="xs"
                      onClick={() => setActiveTab('stakeholders')}
                    />
                  )}
                </nldd-container>
              </nldd-container>
            )}

            {/* Connected nodes preview */}
            {neighbors && neighbors.length > 0 && (
              <Card>
                <nldd-title size={3}><h3>Verbonden nodes ({neighbors.length})</h3></nldd-title>
                <nldd-list appearance="box-tinted" dividers="never">
                  {neighbors.slice(0, 5).map((neighbor) => (
                    <NlddListItemButton key={neighbor.id} onClick={() => navigate(`/nodes/${neighbor.id}`)}>
                      <nldd-text-cell width="fit-content">
                        <Badge color={NODE_TYPE_COLORS[neighbor.node_type]} dot title={nodeAltLabel(neighbor.node_type)}>
                          {nodeLabel(neighbor.node_type)}
                        </Badge>
                      </nldd-text-cell>
                      <nldd-text-cell text={neighbor.title} />
                    </NlddListItemButton>
                  ))}
                </nldd-list>
                {neighbors.length > 5 && (
                  <NlddActionText
                    text={`Bekijk alle ${neighbors.length} verbindingen`}
                    size="xs"
                    onClick={() => setActiveTab('connections')}
                  />
                )}
              </Card>
            )}

          </nldd-container>
        )}

        {activeTab === 'connections' && (
          <EdgeList nodeId={nodeId} nodeType={node.node_type} />
        )}

        {activeTab === 'stakeholders' && (
          // Two sections of equal rank (who is involved, and how they stand)
          // with the same heading size, each with its content first and its
          // input after. The add form is a quiet block under the list rather
          // than a card with a heading as loud as the section's own.
          <nldd-container gap="32">
            <nldd-container gap="16">
              <nldd-title size={3}><h3>Betrokkenen ({stakeholders?.length ?? 0})</h3></nldd-title>

              {/* Stakeholder list. A row wraps on a phone: the person keeps
                  the full width and the role and delete button move under it,
                  instead of a fixed 192px select squeezing the name. */}
              {stakeholders && stakeholders.length > 0 ? (
                <nldd-container gap="8">
                  {stakeholders.map((s) => (
                    <nldd-container key={s.id} layout="wrap" gap="8" vertical-alignment="center">
                      <nldd-container width="fit-content" className="grow" min-width="240px">
                        <PersonCardExpandable person={s.person} />
                      </nldd-container>
                      <div className="hug hug-gap-8">
                        <nldd-container width="160px">
                          <Select
                            value={s.rol}
                            aria-label={`Rol van ${s.person.naam}`}
                            onChange={(e) => {
                              updateStakeholder.mutate({
                                nodeId,
                                stakeholderId: s.id,
                                data: { rol: e.target.value },
                              });
                            }}
                            options={Object.entries(STAKEHOLDER_ROL_LABELS).map(([value, label]) => ({ value, label }))}
                          />
                        </nldd-container>
                        <NlddIconButton
                          icon="trash"
                          variant="critical-transparent"
                          size="sm"
                          accessibleLabel={`${s.person.naam} verwijderen`}
                          onClick={() => setRemoveStakeholderId({ id: s.id, naam: s.person.naam })}
                        />
                      </div>
                    </nldd-container>
                  ))}
                </nldd-container>
              ) : (
                <nldd-text size="sm" color="secondary">
                  Er zijn nog geen personen gekoppeld aan deze node.
                </nldd-text>
              )}

              {/* Add form. Persoon gets a line of its own, so the select and
                  its "Nieuwe persoon aanmaken" option have room; Rol and the
                  button share the next line and wrap together on a phone. */}
              <Card>
                <nldd-container gap="12">
                  <nldd-title size={6}><h4>Betrokkene toevoegen</h4></nldd-title>
                  <CreatableSelect
                    label="Persoon"
                    value={newStakeholderPersonId}
                    onChange={setNewStakeholderPersonId}
                    options={(allPeople ?? []).map((p) => ({
                      value: p.id,
                      label: p.naam,
                      description: formatFunctie(p.functie),
                    }))}
                    placeholder="Selecteer persoon..."
                    onCreate={async (text) => {
                      setPersonCreateName(text);
                      setShowPersonCreate(true);
                      return null;
                    }}
                    createLabel="Nieuwe persoon aanmaken"
                  />
                  <nldd-container layout="wrap" gap="12" vertical-alignment="bottom">
                    <nldd-container width="fit-content" className="grow" min-width="160px">
                      <Select
                        label="Rol"
                        value={newStakeholderRol}
                        onChange={(e) => setNewStakeholderRol(e.target.value)}
                        options={Object.entries(STAKEHOLDER_ROL_LABELS).map(([value, label]) => ({ value, label }))}
                      />
                    </nldd-container>
                    <div className="hug hug-stack">
                      <NlddButton
                        startIcon="plus"
                        disabled={!newStakeholderPersonId || addStakeholder.isPending}
                        onClick={() => {
                          addStakeholder.mutate(
                            { nodeId, data: { person_id: newStakeholderPersonId, rol: newStakeholderRol } },
                            {
                              onSuccess: () => {
                                setNewStakeholderPersonId('');
                                setNewStakeholderRol('betrokken');
                              },
                            },
                          );
                        }}
                        text="Toevoegen"
                      />
                    </div>
                  </nldd-container>
                </nldd-container>
              </Card>
            </nldd-container>

            <nldd-container gap="8">
              <nldd-title size={3}><h3>Belang, houding &amp; invloed</h3></nldd-title>
              <nldd-text size="sm" color="secondary">
                Inschatting per stakeholder, los van rol. Aparte assessment voor
                analyse-doeleinden.
              </nldd-text>
              <StakeholderTab scopeType="corpus_node" scopeId={nodeId} />
            </nldd-container>
          </nldd-container>
        )}

        {activeTab === 'tasks' && (
          <TaskView tasks={nodeTasks ?? []} defaultNodeId={nodeId} />
        )}

        {activeTab === 'activity' && (
          <nldd-container gap="24">
            {/* Title history */}
            <Card>
              <nldd-title size={3}><h3>Titelgeschiedenis</h3></nldd-title>
              <nldd-spacer size="8" />
              {titleHistory && titleHistory.length > 0 ? (
                <nldd-list dividers="never">
                  {titleHistory.map((record, idx) => (
                    <nldd-list-item key={record.id}>
                      <nldd-step-cell
                        status={!record.geldig_tot ? 'current' : 'past'}
                        direction="up"
                        position={
                          titleHistory.length === 1
                            ? 'only'
                            : idx === 0
                              ? 'first'
                              : idx === titleHistory.length - 1
                                ? 'last'
                                : 'between'
                        }
                      />
                      <nldd-spacer-cell size="8" />
                      <nldd-text-cell
                        text={record.title}
                        supporting-text={historyPeriod(record.geldig_van, record.geldig_tot)}
                      />
                    </nldd-list-item>
                  ))}
                </nldd-list>
              ) : (
                <nldd-text size="sm" color="secondary">Geen titelgeschiedenis beschikbaar.</nldd-text>
              )}
            </Card>

            {/* Status history */}
            <Card>
              <nldd-title size={3}><h3>Statusgeschiedenis</h3></nldd-title>
              <nldd-spacer size="8" />
              {statusHistory && statusHistory.length > 0 ? (
                <nldd-list dividers="never">
                  {statusHistory.map((record, idx) => (
                    <nldd-list-item key={record.id}>
                      <nldd-step-cell
                        status={!record.geldig_tot ? 'current' : 'past'}
                        direction="up"
                        position={
                          statusHistory.length === 1
                            ? 'only'
                            : idx === 0
                              ? 'first'
                              : idx === statusHistory.length - 1
                                ? 'last'
                                : 'between'
                        }
                      />
                      <nldd-spacer-cell size="8" />
                      <nldd-text-cell
                        text={NODE_STATUS_LABELS[record.status as NodeStatus] ?? record.status}
                        supporting-text={historyPeriod(record.geldig_van, record.geldig_tot)}
                      />
                    </nldd-list-item>
                  ))}
                </nldd-list>
              ) : (
                <nldd-text size="sm" color="secondary">Geen statusgeschiedenis beschikbaar.</nldd-text>
              )}
            </Card>
          </nldd-container>
        )}
      </div>

      {showEditForm && (
        <NodeEditForm
          open={showEditForm}
          onClose={() => setShowEditForm(false)}
          node={node}
        />
      )}

      <PersonQuickCreateForm
        open={showPersonCreate}
        onClose={() => setShowPersonCreate(false)}
        initialName={personCreateName}
        onCreated={(personId) => {
          setNewStakeholderPersonId(personId);
        }}
      />

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
          <p>Weet je zeker dat je <strong>{node.title}</strong> wilt verwijderen?</p>
          {((neighbors && neighbors.length > 0) || (nodeTasks && nodeTasks.length > 0)) && (
            <ul>
              {neighbors && neighbors.length > 0 && (
                <li>{neighbors.length} verbinding(en) worden verwijderd</li>
              )}
              {nodeTasks && nodeTasks.length > 0 && (
                <li>{nodeTasks.length} gekoppelde taak/taken worden verwijderd</li>
              )}
            </ul>
          )}
        </nldd-rich-text>
      </ConfirmDialog>

      <ConfirmDialog
        open={showBijlageDeleteConfirm}
        onClose={() => setShowBijlageDeleteConfirm(false)}
        onConfirm={async () => {
          try {
            await deleteBijlage(nodeId);
            refetchBijlage();
            setShowBijlageDeleteConfirm(false);
          } catch {
            showError('Bijlage verwijderen mislukt.');
          }
        }}
        title="Bijlage verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
      >
        <nldd-rich-text>
          <p>Weet je zeker dat je de bijlage <strong>{bijlageInfo?.bestandsnaam}</strong> wilt verwijderen?</p>
        </nldd-rich-text>
      </ConfirmDialog>

      <ConfirmDialog
        open={!!removeStakeholderId}
        onClose={() => setRemoveStakeholderId(null)}
        onConfirm={() => {
          if (removeStakeholderId) {
            removeStakeholder.mutate({ nodeId, stakeholderId: removeStakeholderId.id });
            setRemoveStakeholderId(null);
          }
        }}
        title="Betrokkene verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
      >
        <nldd-rich-text>
          <p>Weet je zeker dat je <strong>{removeStakeholderId?.naam}</strong> wilt verwijderen als betrokkene?</p>
        </nldd-rich-text>
      </ConfirmDialog>
    </nldd-container>
  );
}
