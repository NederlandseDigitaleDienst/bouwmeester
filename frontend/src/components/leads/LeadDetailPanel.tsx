import { useCallback, useState, useRef } from 'react';
import { Modal } from '@/components/common/Modal';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { Input } from '@/components/common/Input';
import { Select } from '@/components/common/Select';
import { ImageLightbox } from '@/components/common/ImageLightbox';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { Icon } from '@/components/nldd/Icon';
import { eventValue, orUndef, useNlddEvent } from '@/components/nldd/events';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { RichTextEditor } from '@/components/common/RichTextEditor';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { LinkLeadNodeModal } from './LinkLeadNodeModal';
import { AddLeadContactModal } from './AddLeadContactModal';
import { LeadGitHubLinks } from './LeadGitHubLinks';
import { LeadUpdatesSection } from './LeadUpdatesSection';
import { MattermostChannelsSection } from '@/components/mattermost/MattermostChannelsSection';
import { Badge } from '@/components/common/Badge';
import { DetailSection } from '@/components/common/DetailSection';
import { DetailMetadataGrid } from '@/components/common/DetailMetadataGrid';
import { DetailModalFooter } from '@/components/common/DetailModalFooter';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import {
  useLead,
  useUpdateLead,
  useDeleteLead,
  useCreateLeadActivity,
  useDeleteLeadActivity,
  useRemoveLeadContact,
  useUnlinkLeadNode,
  useUploadLeadAttachment,
  useDeleteLeadAttachment,
  useLeadTags,
  useAddTagToLead,
  useRemoveTagFromLead,
} from '@/hooks/useLeads';
import { useAuth } from '@/contexts/AuthContext';
import { usePeople, useCreatePerson } from '@/hooks/usePeople';
import { useInitiatieven, useCreateInitiatief } from '@/hooks/useInitiatieven';
import { getLeadAttachmentDownloadUrl } from '@/api/leads';
import { isOverdue, formatDateLong, timeAgo } from '@/utils/dates';
import {
  LeadStage,
  LEAD_STAGE_LABELS,
  LEAD_STAGE_ORDER,
  LeadActivityType,
  LEAD_ACTIVITY_TYPE_LABELS,
  INITIATIEF_COLORS,
  LEAD_CONTACT_ROL_LABELS,
  ENGAGEMENT_TYPE_LABELS,
} from '@/types';
import type { LeadUpdate, LeadActivityCreate, EngagementType, LeadAttachment } from '@/types';
import { stageTagColor, engagementTagColor } from './stageColors';
import { initiatiefTagColor } from '@/components/initiatieven/initiatiefColors';
import { NlddButton } from '@/components/nldd/NlddButton';

/** Stages where a lead can publicly appear; mirrors the backend filter in
 *  public_initiatief.py — keep in sync. */
const PUBLIC_VISIBLE_STAGES: LeadStage[] = [
  LeadStage.EERSTE_GESPREK,
  LeadStage.INTERNE_CHECK,
  LeadStage.FOLLOW_UP,
  LeadStage.IN_THE_POCKET,
];

interface PublicationStatus {
  /** Will this lead actually appear on the public page right now? */
  visible: boolean;
  /** Human-readable reason when not visible. Null when visible. */
  reason: string | null;
}

function publicationStatus(args: {
  publicVisible: boolean;
  publicTitle: string | null;
  stage: string;
}): PublicationStatus {
  if (!args.publicVisible) {
    return { visible: false, reason: 'Toggle "Publiek tonen" staat uit.' };
  }
  if (!args.publicTitle?.trim()) {
    return { visible: false, reason: 'Publieke titel is leeg.' };
  }
  // Heuristiek-fallback: voor de detail-panel-hint gebruiken we de
  // 7-default whitelist. De backend doet de echte check op
  // LeadColumn.is_public_visible per initiatief; deze UI-hint hoeft
  // alleen "ongeveer juist" te zijn voor default-stages.
  if (!PUBLIC_VISIBLE_STAGES.includes(args.stage as LeadStage)) {
    const label = LEAD_STAGE_LABELS[args.stage] ?? args.stage;
    return {
      visible: false,
      reason: `Lead in stage "${label}" — alleen actieve stages worden publiek.`,
    };
  }
  return { visible: true, reason: null };
}

interface LeadDetailPanelProps {
  leadId: string | null;
  open: boolean;
  onClose: () => void;
}

/** nldd-icon names for each activity type. */
const ACTIVITY_ICONS: Record<LeadActivityType, string> = {
  [LeadActivityType.NOTE]: 'message-rectangle-text',
  [LeadActivityType.STAGE_CHANGE]: 'file-text',
  [LeadActivityType.MEETING]: 'person',
  [LeadActivityType.CALL]: 'at',
  [LeadActivityType.EMAIL]: 'envelope',
  [LeadActivityType.EVALUATIE]: 'file-text',
};

export function LeadDetailPanel({ leadId, open, onClose }: LeadDetailPanelProps) {
  const { data: lead, isLoading } = useLead(leadId);
  const { data: people } = usePeople();
  const { data: initiatieven } = useInitiatieven();
  const createInitiatief = useCreateInitiatief();
  const createPerson = useCreatePerson();

  const updateLead = useUpdateLead();
  const deleteLead = useDeleteLead();
  const createActivity = useCreateLeadActivity();
  const deleteActivity = useDeleteLeadActivity();
  const { person } = useAuth();
  const removeContact = useRemoveLeadContact();
  const unlinkNode = useUnlinkLeadNode();
  const uploadAttachment = useUploadLeadAttachment();
  const deleteAttachment = useDeleteLeadAttachment();
  const { data: leadTags } = useLeadTags(leadId);
  const addTagToLead = useAddTagToLead();
  const removeTagFromLead = useRemoveTagFromLead();

  const [editing, setEditing] = useState(false);
  const [editTitle, setEditTitle] = useState('');
  const [editDescription, setEditDescription] = useState('');
  const [editOrganization, setEditOrganization] = useState('');
  const [editStage, setEditStage] = useState<string>(LeadStage.VERKENNEN);
  const [editAssignee, setEditAssignee] = useState('');
  const [editNextAction, setEditNextAction] = useState('');
  const [editNextActionDate, setEditNextActionDate] = useState('');
  const [editInitiatiefId, setEditInitiatiefId] = useState('');
  const [editTags, setEditTags] = useState('');
  const [editEngagementType, setEditEngagementType] = useState<EngagementType | ''>('');
  const [editScoreStrategisch, setEditScoreStrategisch] = useState<number | ''>('');
  const [editScorePolitiek, setEditScorePolitiek] = useState<number | ''>('');
  const [editScorePositie, setEditScorePositie] = useState<number | ''>('');
  const [editPublicVisible, setEditPublicVisible] = useState(false);
  const [editPublicTitle, setEditPublicTitle] = useState('');
  const [editPublicSummary, setEditPublicSummary] = useState('');

  // Activity form
  const [activityContent, setActivityContent] = useState('');
  const [activityType, setActivityType] = useState<LeadActivityType>(LeadActivityType.NOTE);
  const [activityUitkomst, setActivityUitkomst] = useState('');
  const [activityVervolgacties, setActivityVervolgacties] = useState('');

  // Contact add form
  const [showAddContact, setShowAddContact] = useState(false);

  // Node link modal
  const [showLinkNode, setShowLinkNode] = useState(false);

  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const [lightboxSrc, setLightboxSrc] = useState<{ src: string; alt: string } | null>(null);
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [activityToDelete, setActivityToDelete] = useState<string | null>(null);

  if (!open) return null;

  const startEditing = () => {
    if (!lead) return;
    setEditTitle(lead.title);
    setEditDescription(lead.description ?? '');
    setEditOrganization(lead.organization ?? '');
    setEditStage(lead.stage);
    setEditAssignee(lead.assignee_id ?? '');
    setEditNextAction(lead.next_action ?? '');
    setEditNextActionDate(lead.next_action_date ?? '');
    setEditInitiatiefId(lead.initiatief_id ?? '');
    setEditTags((leadTags ?? []).map((lt) => lt.tag.name).join(', '));
    setEditEngagementType(lead.engagement_type ?? '');
    setEditScoreStrategisch(lead.score_strategisch ?? '');
    setEditScorePolitiek(lead.score_politiek ?? '');
    setEditScorePositie(lead.score_positie ?? '');
    setEditPublicVisible(lead.public_visible);
    setEditPublicTitle(lead.public_title ?? '');
    setEditPublicSummary(lead.public_summary ?? '');
    setEditing(true);
  };

  const saveEdit = async () => {
    if (!lead) return;
    const tagList = editTags
      .split(',')
      .map((t) => t.trim())
      .filter(Boolean);

    const data: LeadUpdate = {
      title: editTitle.trim(),
      description: editDescription.trim() || null,
      organization: editOrganization.trim() || null,
      stage: editStage,
      assignee_id: editAssignee || null,
      next_action: editNextAction.trim() || null,
      next_action_date: editNextActionDate || null,
      initiatief_id: editInitiatiefId || null,
      engagement_type: editEngagementType || null,
      score_strategisch: editScoreStrategisch === '' ? null : editScoreStrategisch,
      score_politiek: editScorePolitiek === '' ? null : editScorePolitiek,
      score_positie: editScorePositie === '' ? null : editScorePositie,
      public_visible: editPublicVisible,
      public_title: editPublicTitle.trim() || null,
      public_summary: editPublicSummary.trim() || null,
    };

    // Update lead fields
    updateLead.mutate(
      { id: lead.id, data },
      {
        onSuccess: async () => {
          // Sync tags: remove tags not in the new list, add new ones
          const currentTagNames = (leadTags ?? []).map((lt) => lt.tag.name);
          const toRemove = (leadTags ?? []).filter((lt) => !tagList.includes(lt.tag.name));
          const toAdd = tagList.filter((name) => !currentTagNames.includes(name));

          for (const lt of toRemove) {
            try {
              await removeTagFromLead.mutateAsync({ leadId: lead.id, tagId: lt.tag.id });
            } catch {
              // Non-critical
            }
          }
          for (const name of toAdd) {
            try {
              await addTagToLead.mutateAsync({ leadId: lead.id, data: { tag_name: name } });
            } catch {
              // Non-critical
            }
          }
          setEditing(false);
        },
      },
    );
  };

  const handleDelete = () => {
    if (!lead) return;
    setShowDeleteConfirm(true);
  };

  const isActivityEmpty = (() => {
    if (!activityContent) return true;
    try {
      const doc = JSON.parse(activityContent);
      if (doc?.type !== 'doc') return !activityContent.trim();
      const hasContent = doc.content?.some((node: { type: string; content?: unknown[] }) =>
        node.content && node.content.length > 0,
      );
      return !hasContent;
    } catch {
      return !activityContent.trim();
    }
  })();

  const handleAddActivity = () => {
    if (!lead || isActivityEmpty) return;
    const data: LeadActivityCreate = {
      content: activityContent,
      activity_type: activityType,
      uitkomst:
        activityType === LeadActivityType.EVALUATIE
          ? activityUitkomst.trim() || null
          : null,
      vervolgacties:
        activityType === LeadActivityType.EVALUATIE
          ? activityVervolgacties.trim() || null
          : null,
    };
    createActivity.mutate(
      { leadId: lead.id, data },
      {
        onSuccess: () => {
          setActivityContent('');
          setActivityType(LeadActivityType.NOTE);
          setActivityUitkomst('');
          setActivityVervolgacties('');
        },
      },
    );
  };

  const handleFileUpload = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!lead || !e.target.files) return;
    for (const file of Array.from(e.target.files)) {
      uploadAttachment.mutate({ leadId: lead.id, file });
    }
    e.target.value = '';
  };

  const overdue = lead?.next_action_date && isOverdue(lead.next_action_date);

  return (
    <>
    <Modal
      open={open}
      onClose={onClose}
      title={isLoading ? 'Laden...' : lead?.title ?? 'Lead niet gevonden'}
      size="lg"
      entityLabel="Lead"
      footer={
        editing ? (
          <nldd-container layout="row" gap="8" horizontal-alignment="right">
            <NlddButton variant="neutral-transparent" onClick={() => setEditing(false)} text="Annuleren" />
            <NlddButton onClick={saveEdit} loading={updateLead.isPending} text="Opslaan" />
          </nldd-container>
        ) : (
          <DetailModalFooter
            onClose={onClose}
            actions={
              <nldd-container layout="row" gap="8">
                <NlddButton variant="secondary" size="sm" startIcon="pencil" onClick={startEditing} disabled={!lead} text="Bewerken" />
                <NlddButton variant="destructive" size="sm" startIcon="trash" onClick={handleDelete} disabled={!lead} text="Verwijderen" />
              </nldd-container>
            }
          />
        )
      }
    >
      {isLoading ? (
        <LoadingSpinner padding="32" />
      ) : !lead ? (
        <nldd-container horizontal-alignment="center" padding="32">
          <nldd-text size="sm" color="secondary">Lead niet gevonden.</nldd-text>
        </nldd-container>
      ) : editing ? (
        /* Edit mode */
        <nldd-container gap="16">
          <Input label="Titel" type="text" value={editTitle} onChange={(e) => setEditTitle(e.target.value)} />
          <nldd-container layout="grid" column-count={2} gap="16">
            <CreatableSelect
              label="Stage"
              value={editStage}
              onChange={(v) => setEditStage(v as LeadStage)}
              options={LEAD_STAGE_ORDER.map((s) => ({
                value: s,
                label: LEAD_STAGE_LABELS[s],
              }))}
              placeholder="Selecteer stage..."
              searchable={false}
            />
            <CreatableSelect
              label="Toegewezen aan"
              value={editAssignee}
              onChange={setEditAssignee}
              options={[
                { value: '', label: 'Niet toegewezen' },
                ...(people?.map((p) => ({
                  value: p.id,
                  label: p.naam,
                  description: p.functie ?? undefined,
                })) ?? []),
              ]}
              placeholder="Zoek een persoon..."
              onCreate={async (name) => {
                const result = await createPerson.mutateAsync({ naam: name, force: true });
                return result?.id ?? null;
              }}
              createLabel="Nieuwe persoon aanmaken"
              onClear={editAssignee ? () => setEditAssignee('') : undefined}
            />
          </nldd-container>
          <Input label="Organisatie" type="text" value={editOrganization} onChange={(e) => setEditOrganization(e.target.value)} autoComplete="organization" />
          <CreatableSelect
            label="Initiatief"
            value={editInitiatiefId}
            onChange={setEditInitiatiefId}
            options={[
              { value: '', label: 'Geen initiatief' },
              ...(initiatieven?.map((i) => ({ value: i.id, label: i.naam })) ?? []),
            ]}
            placeholder="Selecteer initiatief..."
            onClear={editInitiatiefId ? () => setEditInitiatiefId('') : undefined}
            onCreate={async (name) => {
              const kleur = INITIATIEF_COLORS[Math.floor(Math.random() * INITIATIEF_COLORS.length)];
              const result = await createInitiatief.mutateAsync({ naam: name, kleur });
              return result.id;
            }}
            createLabel="Nieuw initiatief"
          />
          <Input label="Volgende actie" type="text" value={editNextAction} onChange={(e) => setEditNextAction(e.target.value)} />
          <Input label="Actiedatum" type="date" value={editNextActionDate} onChange={(e) => setEditNextActionDate(e.target.value)} />
          <Input
            label="Tags"
            type="text"
            value={editTags}
            onChange={(e) => setEditTags(e.target.value)}
            placeholder="Komma-gescheiden tags"
          />
          {(() => {
            const selectedInit = initiatieven?.find((i) => i.id === editInitiatiefId);
            if (!selectedInit?.funnel_enabled) return null;
            const labelStrategisch =
              selectedInit.score_strategisch_label || 'Strategisch belang';
            const labelPolitiek =
              selectedInit.score_politiek_label || 'Politiek belang';
            const labelPositie =
              selectedInit.score_positie_label || 'Positie / omgeving';
            return (
              <nldd-card background="tinted">
                <nldd-container gap="12" padding="12">
                  <nldd-title size={6}><h3>Funnel-afweging</h3></nldd-title>
                  <Select label="Engagement type" width="full" options={ENGAGEMENT_OPTIONS} value={editEngagementType} onChange={(e) => setEditEngagementType(e.target.value as EngagementType | '')} />
                  <nldd-container layout="grid" column-count={3} gap="8">
                    <ScoreSelect label={labelStrategisch} value={editScoreStrategisch} onChange={setEditScoreStrategisch} />
                    <ScoreSelect label={labelPolitiek} value={editScorePolitiek} onChange={setEditScorePolitiek} />
                    <ScoreSelect label={labelPositie} value={editScorePositie} onChange={setEditScorePositie} />
                  </nldd-container>
                </nldd-container>
              </nldd-card>
            );
          })()}
          {(() => {
            const linkedInit = initiatieven?.find((i) => i.id === editInitiatiefId);
            if (!linkedInit?.public_page_enabled) return null;
            const status = publicationStatus({
              publicVisible: editPublicVisible,
              publicTitle: editPublicTitle,
              stage: editStage,
            });
            return (
              <nldd-card background="tinted">
                <nldd-container gap="12" padding="12">
                  <nldd-container layout="row" gap="8" vertical-alignment="center">
                    <nldd-title size={6}><h3>Publicatie op /c/{linkedInit.slug}</h3></nldd-title>
                    <PublicVisibleSwitch checked={editPublicVisible} onChange={setEditPublicVisible} />
                  </nldd-container>
                  {editPublicVisible && !status.visible && (
                    <nldd-inline-dialog
                      variant="alert"
                      size="md"
                      text="Nog niet zichtbaar"
                      supporting-text={status.reason ?? undefined}
                    />
                  )}
                  <nldd-text size="xs" color="secondary">
                    Schrijf een externe titel en samenvatting. Alleen die tekst
                    verschijnt op de publieke pagina, nooit het interne titel- of
                    beschrijvingsveld.
                  </nldd-text>
                  <Input
                    label="Publieke titel"
                    type="text"
                    value={editPublicTitle}
                    onChange={(e) => setEditPublicTitle(e.target.value)}
                    placeholder="Bijv. 'Pilot bij Gemeente Utrecht'"
                  />
                  <nldd-form-field label="Publieke samenvatting">
                    <PublicSummaryField value={editPublicSummary} onChange={setEditPublicSummary} />
                  </nldd-form-field>
                  <nldd-text size="xs" color="secondary">
                    Verschijnt alleen als de stage actief is (eerste gesprek, interne
                    check, follow-up of in the pocket) én "Publiek tonen" aan staat én
                    de titel ingevuld is.
                  </nldd-text>
                </nldd-container>
              </nldd-card>
            );
          })()}
          <RichTextFormField
            label="Beschrijving"
            value={editDescription}
            onChange={setEditDescription}
            rows={5}
          />
        </nldd-container>
      ) : (
        /* View mode */
        <nldd-container gap="20">
          {/* Stage badge + next action */}
          <nldd-container layout="wrap" gap="8" vertical-alignment="center">
            <nldd-tag text={LEAD_STAGE_LABELS[lead.stage]} color={stageTagColor(lead.stage)} size="sm" />
            {lead.next_action_date && (
              <div
                className="hug"
                style={{
                  padding: '2px 8px',
                  ...(overdue ? { backgroundColor: 'var(--primitives-color-critical-25)', borderRadius: '6px' } : {}),
                }}
              >
                <nldd-icon icon="calendar" size="16" aria-hidden="true" />
                <nldd-text size="sm" color={overdue ? 'critical' : 'secondary'} weight={overdue ? 'medium' : 'regular'}>
                  {formatDateLong(lead.next_action_date)}
                </nldd-text>
              </div>
            )}
          </nldd-container>

          {/* Description */}
          {lead.description && (
            <DetailSection title="Beschrijving">
              <nldd-text size="sm">
                <RichTextDisplay content={lead.description} />
              </nldd-text>
            </DetailSection>
          )}

          {/* Metadata */}
          <DetailMetadataGrid
            items={[
              {
                label: 'Organisatie',
                value: lead.organisatie_eenheid?.naam ?? lead.organization ?? 'Onbekend',
              },
              {
                label: 'Toegewezen aan',
                value: lead.assignee ? (
                  <nldd-container layout="row" gap="6" vertical-alignment="center">
                    <Icon name="person" size="md" />
                    <nldd-text size="sm">{lead.assignee.naam}</nldd-text>
                  </nldd-container>
                ) : (
                  <nldd-text size="sm" color="secondary">Niet toegewezen</nldd-text>
                ),
              },
              {
                label: 'Binnengebracht door',
                value: lead.brought_by ? (
                  <nldd-container layout="row" gap="6" vertical-alignment="center">
                    <Icon name="person" size="md" />
                    <nldd-text size="sm">{lead.brought_by.naam}</nldd-text>
                  </nldd-container>
                ) : (
                  <nldd-text size="sm" color="secondary">Onbekend</nldd-text>
                ),
              },
              {
                label: 'Initiatief',
                value: lead.initiatief ? (
                  <nldd-tag
                    text={lead.initiatief.naam}
                    color={initiatiefTagColor(lead.initiatief.kleur)}
                    size="sm"
                  />
                ) : (
                  '-'
                ),
              },
              {
                label: 'Volgende actie',
                value: lead.next_action ?? '-',
              },
              {
                label: 'Aangemaakt',
                value: formatDateLong(lead.created_at),
                icon: <Icon name="calendar" size="md" />,
              },
            ]}
          />

          {/* Funnel-afweging (only when initiatief has funnel_enabled) */}
          {(() => {
            const linkedInit = initiatieven?.find(
              (i) => i.id === lead.initiatief_id,
            );
            if (!linkedInit?.funnel_enabled) return null;
            const hasAny =
              lead.engagement_type ||
              lead.score_strategisch != null ||
              lead.score_politiek != null ||
              lead.score_positie != null;
            if (!hasAny) return null;
            const labels = [
              [linkedInit.score_strategisch_label || 'Strategisch belang', lead.score_strategisch],
              [linkedInit.score_politiek_label || 'Politiek belang', lead.score_politiek],
              [linkedInit.score_positie_label || 'Positie / omgeving', lead.score_positie],
            ] as const;
            return (
              <DetailSection title="Funnel-afweging">
                <nldd-container gap="8">
                  {lead.engagement_type && (
                    <nldd-container layout="row" gap="6" vertical-alignment="center">
                      <nldd-text size="sm" color="secondary">Engagement:</nldd-text>
                      <nldd-tag
                        text={ENGAGEMENT_TYPE_LABELS[lead.engagement_type]}
                        color={engagementTagColor(lead.engagement_type)}
                        size="sm"
                      />
                    </nldd-container>
                  )}
                  <nldd-container layout="grid" column-count={3} gap="8">
                    {labels.map(([label, value], idx) => (
                      <nldd-container key={idx} gap="2">
                        <nldd-text size="xs" color="secondary">{label}</nldd-text>
                        <nldd-text size="sm" weight="medium">
                          {value != null ? `${value}/5` : '—'}
                        </nldd-text>
                      </nldd-container>
                    ))}
                  </nldd-container>
                </nldd-container>
              </DetailSection>
            );
          })()}

          {/* Publicatie-status */}
          {(() => {
            const linkedInit = initiatieven?.find(
              (i) => i.id === lead.initiatief_id,
            );
            if (!linkedInit?.public_page_enabled) return null;
            if (!lead.public_visible && !lead.public_title) return null;
            const status = publicationStatus({
              publicVisible: lead.public_visible,
              publicTitle: lead.public_title,
              stage: lead.stage,
            });
            return (
              <DetailSection title="Publicatie">
                <nldd-container gap="8">
                  <nldd-container layout="wrap" gap="8" vertical-alignment="center">
                    {status.visible ? (
                      // The underline lives on a nested span, not the link
                      // itself, so it needs a real group/group-hover pair
                      // (`.group` + `.group-hover-underline` in
                      // utilities.css) rather than an nldd-link, which would
                      // underline its own text, not the badge's.
                      <a
                        href={`/c/${linkedInit.slug}`}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="group"
                        style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                      >
                        <Badge color="groen">
                          <span
                            className="group-hover-underline"
                            style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}
                          >
                            Zichtbaar op /c/{linkedInit.slug}
                            <Icon name="external-link" size="xs" />
                          </span>
                        </Badge>
                      </a>
                    ) : (
                      <Badge color="coolgray">Niet zichtbaar</Badge>
                    )}
                  </nldd-container>
                  {!status.visible && status.reason && (
                    <nldd-text size="xs" color="secondary">
                      {status.reason}
                    </nldd-text>
                  )}
                  {lead.public_title && (
                    <nldd-container layout="row" gap="4">
                      <nldd-text size="sm" color="secondary">Publieke titel:</nldd-text>
                      <nldd-text size="sm" weight="medium">{lead.public_title}</nldd-text>
                    </nldd-container>
                  )}
                  {lead.public_summary && (
                    <nldd-text size="sm" color="secondary">
                      <span style={{ whiteSpace: 'pre-wrap' }}>{lead.public_summary}</span>
                    </nldd-text>
                  )}
                </nldd-container>
              </DetailSection>
            );
          })()}

          <LeadUpdatesSection leadId={lead.id} />

          {/* Tags */}
          {(leadTags ?? []).length > 0 && (
            <DetailSection title="Tags">
              <nldd-container layout="wrap" gap="6">
                {(leadTags ?? []).map((lt) => (
                  <Badge key={lt.id} color="coolgray">{lt.tag.name}</Badge>
                ))}
              </nldd-container>
            </DetailSection>
          )}

          {/* Bijlagen */}
          <DetailSection
            title="Bijlagen"
            icon={<Icon name="paperclip" size="sm" />}
            count={lead.attachments.length}
            separated
            action={
              <>
                <NlddButton variant="neutral-transparent" size="sm" startIcon="upload" onClick={() => fileInputRef.current?.click()} text="Uploaden" />
                <input
                  type="file"
                  multiple
                  hidden
                  ref={fileInputRef}
                  onChange={handleFileUpload}
                />
              </>
            }
          >
            {lead.attachments.length > 0 ? (
              <nldd-list appearance="simple" dividers="never" accessible-label="Bijlagen">
                {lead.attachments.map((att) => (
                  <AttachmentRow
                    key={att.id}
                    attachment={att}
                    downloadUrl={getLeadAttachmentDownloadUrl(lead.id, att.id)}
                    onDelete={() => deleteAttachment.mutate({ leadId: lead.id, attachmentId: att.id })}
                    onZoom={(src, alt) => setLightboxSrc({ src, alt })}
                  />
                ))}
              </nldd-list>
            ) : (
              <nldd-text size="sm" color="secondary">Geen bijlagen</nldd-text>
            )}
          </DetailSection>

          <LeadGitHubLinks leadId={lead.id} links={lead.github_links ?? []} />

          {/* Externe contactpersonen */}
          <DetailSection
            title="Externe contactpersonen"
            icon={<Icon name="person" size="sm" />}
            count={lead.contacts.length}
            separated
            action={
              <NlddButton variant="neutral-transparent" size="sm" startIcon="plus" onClick={() => setShowAddContact(true)} text="Toevoegen" />
            }
          >
            {lead.contacts.length > 0 ? (
              <nldd-list appearance="simple" dividers="never" accessible-label="Externe contactpersonen">
                {lead.contacts.map((contact) => (
                  <ContactRow
                    key={contact.id}
                    naam={contact.person_naam}
                    expertise={contact.person_expertise}
                    rolLabel={LEAD_CONTACT_ROL_LABELS[contact.rol] ?? contact.rol}
                    onRemove={() => removeContact.mutate({ leadId: lead.id, contactId: contact.id })}
                  />
                ))}
              </nldd-list>
            ) : (
              <nldd-text size="sm" color="secondary">Geen externe contactpersonen</nldd-text>
            )}

            <AddLeadContactModal
              leadId={showAddContact ? lead.id : null}
              onClose={() => setShowAddContact(false)}
            />
          </DetailSection>

          {/* Gelinkte nodes */}
          <DetailSection
            title="Gelinkte nodes"
            icon={<Icon name="link" size="sm" />}
            count={lead.linked_nodes.length}
            separated
            action={
              <NlddButton variant="neutral-transparent" size="sm" startIcon="plus" onClick={() => setShowLinkNode(true)} text="Koppelen" />
            }
          >
            {lead.linked_nodes.length > 0 ? (
              <nldd-list appearance="simple" dividers="never" accessible-label="Gelinkte nodes">
                {lead.linked_nodes.map((ln) => (
                  <LinkedNodeRow
                    key={ln.id}
                    title={ln.node_title}
                    nodeType={ln.node_type}
                    onUnlink={() => unlinkNode.mutate({ leadId: lead.id, linkId: ln.id })}
                  />
                ))}
              </nldd-list>
            ) : (
              <nldd-text size="sm" color="secondary">Geen gelinkte nodes</nldd-text>
            )}
          </DetailSection>

          {/* Activiteiten */}
          <DetailSection
            title="Activiteiten"
            icon={<Icon name="message-rectangle-text" size="sm" />}
            count={lead.activities.length}
            separated
          >
            {/* Add activity form */}
            <nldd-container gap="8" padding-bottom="16">
              <RichTextEditor
                value={activityContent}
                onChange={setActivityContent}
                placeholder="Voeg een notitie of activiteit toe... Gebruik @ voor personen, # voor nodes/taken"
                rows={2}
              />
              {activityType === LeadActivityType.EVALUATIE && (
                <nldd-container layout="grid" column-count={1} sm-column-count={2} gap="8">
                  <ActivityTextArea
                    value={activityUitkomst}
                    onChange={setActivityUitkomst}
                    placeholder="Uitkomst van de evaluatie..."
                    accessibleLabel="Uitkomst van de evaluatie"
                  />
                  <ActivityTextArea
                    value={activityVervolgacties}
                    onChange={setActivityVervolgacties}
                    placeholder="Vervolgacties / wat moet er nu gebeuren..."
                    accessibleLabel="Vervolgacties"
                  />
                </nldd-container>
              )}
              <nldd-container layout="row" gap="8" vertical-alignment="center">
                <nldd-container width="fit-content" min-width="144px">
                  <CreatableSelect
                    value={activityType}
                    onChange={(v) => setActivityType(v as LeadActivityType)}
                    options={Object.entries(LEAD_ACTIVITY_TYPE_LABELS)
                      .filter(([value]) => value !== LeadActivityType.STAGE_CHANGE)
                      .map(([value, label]) => ({ value, label }))}
                    placeholder="Type..."
                    searchable={false}
                  />
                </nldd-container>
                <NlddButton
                  size="sm"
                  onClick={handleAddActivity}
                  disabled={isActivityEmpty}
                  loading={createActivity.isPending}
                  text="Toevoegen"
                />
              </nldd-container>
            </nldd-container>

            {/* Activity list */}
            {lead.activities.length > 0 ? (
              <nldd-container gap="12">
                {[...lead.activities].reverse().map((activity) => {
                  const canDelete =
                    !!person &&
                    (person.is_admin ||
                      (person.id !== null && activity.author_id === person.id));
                  return (
                  // `group`/`group-hover` reveals the delete icon-button only
                  // on hover or keyboard focus of this row — real CSS-group
                  // behavior, no nldd-* equivalent, kept as a narrow className
                  // on the row and the button.
                  <div key={activity.id} className="group" style={{ display: 'flex', gap: '10px' }}>
                    <div
                      style={{
                        marginTop: '2px',
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                        height: '24px',
                        width: '24px',
                        borderRadius: '9999px',
                        backgroundColor: 'var(--primitives-color-neutral-100)',
                        color: 'var(--primitives-color-neutral-600)',
                        flexShrink: 0,
                      }}
                    >
                      <nldd-icon icon={ACTIVITY_ICONS[activity.activity_type]} size="16" aria-hidden="true" />
                    </div>
                    <nldd-container gap="2" width="full">
                      <nldd-container layout="row" gap="8" vertical-alignment="center">
                        {activity.author_naam && (
                          <nldd-text size="xs" weight="medium">{activity.author_naam}</nldd-text>
                        )}
                        <Badge color="coolgray">
                          {LEAD_ACTIVITY_TYPE_LABELS[activity.activity_type]}
                        </Badge>
                        {activity.metadata_?.source === 'mattermost' && (
                          (() => {
                            const permalink = activity.metadata_?.mm_permalink;
                            const badge = <nldd-tag text="via Mattermost" color="lintblauw" size="sm" />;
                            return typeof permalink === 'string' ? (
                              <a
                                href={permalink}
                                target="_blank"
                                rel="noreferrer"
                                title="Open in Mattermost"
                              >
                                {badge}
                              </a>
                            ) : badge;
                          })()
                        )}
                        <nldd-text size="xs" color="secondary">{timeAgo(activity.created_at)}</nldd-text>
                        {canDelete && (
                          // Pushed to the end of the row and revealed only on
                          // hover/focus of it (`group` on the wrapping div,
                          // above the `sm` breakpoint) — real CSS classes in
                          // utilities.css, no nldd-* equivalent for either.
                          <NlddIconButton
                            icon="trash"
                            accessibleLabel="Activiteit verwijderen"
                            variant="neutral-transparent"
                            size="sm"
                            onClick={() => setActivityToDelete(activity.id)}
                            className="margin-left-auto group-hover-reveal-above-sm"
                          />
                        )}
                      </nldd-container>
                      <nldd-text size="sm">
                        <RichTextDisplay content={activity.content} fallback="" />
                      </nldd-text>
                      {(activity.uitkomst || activity.vervolgacties) && (
                        <nldd-container layout="grid" column-count={1} sm-column-count={2} gap="8" padding-top="6">
                          {activity.uitkomst && (
                            <nldd-card background="tinted">
                              <nldd-container gap="2" padding="8">
                                <nldd-text size="xs" weight="medium" color="success">
                                  Uitkomst
                                </nldd-text>
                                <nldd-text size="xs">
                                  <span style={{ whiteSpace: 'pre-wrap' }}>{activity.uitkomst}</span>
                                </nldd-text>
                              </nldd-container>
                            </nldd-card>
                          )}
                          {activity.vervolgacties && (
                            <nldd-card background="tinted">
                              <nldd-container gap="2" padding="8">
                                <nldd-text size="xs" weight="medium" color="warning">
                                  Vervolgacties
                                </nldd-text>
                                <nldd-text size="xs">
                                  <span style={{ whiteSpace: 'pre-wrap' }}>{activity.vervolgacties}</span>
                                </nldd-text>
                              </nldd-container>
                            </nldd-card>
                          )}
                        </nldd-container>
                      )}
                    </nldd-container>
                  </div>
                  );
                })}
              </nldd-container>
            ) : (
              <nldd-text size="sm" color="secondary">Nog geen activiteiten</nldd-text>
            )}
          </DetailSection>

          {/* Mattermost-kanalen */}
          <DetailSection title="Mattermost" separated>
            <MattermostChannelsSection
              scope={{ type: 'lead', id: lead.id }}
            />
          </DetailSection>
        </nldd-container>
      )}
    </Modal>

    {/* Only ever opened from inside the open Modal, so its top-layer window
        stacks above the Modal's. */}
    {lightboxSrc && (
      <ImageLightbox
        src={lightboxSrc.src}
        alt={lightboxSrc.alt}
        onClose={() => setLightboxSrc(null)}
      />
    )}
    <ConfirmDialog
      open={showDeleteConfirm}
      onClose={() => setShowDeleteConfirm(false)}
      onConfirm={() => {
        if (lead) deleteLead.mutate(lead.id, { onSuccess: onClose });
        setShowDeleteConfirm(false);
      }}
      title="Lead verwijderen"
      confirmLabel="Verwijderen"
      variant="danger"
    >
      Weet je zeker dat je deze lead wilt verwijderen?
    </ConfirmDialog>
    <ConfirmDialog
      open={activityToDelete !== null}
      onClose={() => setActivityToDelete(null)}
      onConfirm={() => {
        if (lead && activityToDelete) {
          deleteActivity.mutate({ leadId: lead.id, activityId: activityToDelete });
        }
        setActivityToDelete(null);
      }}
      title="Activiteit verwijderen"
      confirmLabel="Verwijderen"
      variant="danger"
    >
      Weet je zeker dat je deze activiteit wilt verwijderen? Deze actie kan niet ongedaan worden gemaakt.
    </ConfirmDialog>
    {showLinkNode && lead && (
      <LinkLeadNodeModal
        leadId={lead.id}
        onClose={() => setShowLinkNode(false)}
      />
    )}
    </>
  );
}

/** A leading empty option: every funnel field may stay unset. */
const ENGAGEMENT_OPTIONS = [
  { value: '', label: '—' },
  ...(Object.keys(ENGAGEMENT_TYPE_LABELS) as EngagementType[]).map((k) => ({
    value: k,
    label: ENGAGEMENT_TYPE_LABELS[k],
  })),
];

const SCORE_OPTIONS = [
  { value: '', label: '—' },
  ...[1, 2, 3, 4, 5].map((n) => ({ value: String(n), label: String(n) })),
];

function ScoreSelect({
  label,
  value,
  onChange,
}: {
  label: string;
  value: number | '';
  onChange: (value: number | '') => void;
}) {
  return (
    <Select
      label={label}
      width="full"
      options={SCORE_OPTIONS}
      value={String(value)}
      onChange={(e) => onChange(e.target.value === '' ? '' : Number(e.target.value))}
    />
  );
}

/** Reads `checked` off an nldd-switch-field's `change` detail. */
function checkedValue(event: Event): boolean {
  return Boolean((event as CustomEvent<{ checked?: boolean }>).detail?.checked);
}

function PublicVisibleSwitch({ checked, onChange }: { checked: boolean; onChange: (checked: boolean) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'change', useCallback((e: Event) => onChange(checkedValue(e)), [onChange]));

  return <nldd-switch-field ref={ref} checked={orUndef(checked)} label="Publiek tonen" />;
}

function PublicSummaryField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'input', useCallback((e: Event) => onChange(eventValue(e)), [onChange]));

  return (
    <nldd-multi-line-text-field
      ref={ref}
      value={value}
      placeholder="Korte tekst voor buitenstaanders. Geen interne details, geen namen van conflicten."
      rows={3}
      accessible-label="Publieke samenvatting"
      width="full"
    />
  );
}

interface ActivityTextAreaProps {
  value: string;
  onChange: (value: string) => void;
  placeholder: string;
  accessibleLabel: string;
}

function ActivityTextArea({ value, onChange, placeholder, accessibleLabel }: ActivityTextAreaProps) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'input', useCallback((e: Event) => onChange(eventValue(e)), [onChange]));

  return (
    <nldd-multi-line-text-field
      ref={ref}
      value={value}
      placeholder={placeholder}
      rows={2}
      accessible-label={accessibleLabel}
      width="full"
    />
  );
}

interface AttachmentRowProps {
  attachment: LeadAttachment;
  downloadUrl: string;
  onDelete: () => void;
  onZoom: (src: string, alt: string) => void;
}

function AttachmentRow({ attachment: att, downloadUrl, onDelete, onZoom }: AttachmentRowProps) {
  const isImage = att.soort === 'file' && att.bestand_beschikbaar && att.content_type?.startsWith('image/');

  return (
    <nldd-list-item>
      <nldd-container width="full" gap="8" padding="4" style={{ opacity: att.bestand_beschikbaar ? 1 : 0.5 }}>
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <nldd-icon icon={att.soort === 'link' ? 'external-link' : 'paperclip'} size="16" aria-hidden="true" />
          {att.soort === 'link' && att.url ? (
            // The link inherits its size from the text around it, so the
            // ellipsis on that text cuts the link off too.
            <nldd-text size="sm" className="truncate row-fill" title={att.url}>
              <nldd-link href={att.url} target="_blank" text={att.bestandsnaam ?? att.url} />
            </nldd-text>
          ) : (
            <nldd-text size="sm" className="truncate row-fill">
              {att.bestandsnaam ?? '(naamloos)'}
            </nldd-text>
          )}
          {att.source === 'mattermost' && (
            <nldd-tag text="via mm" color="neutral" size="sm" />
          )}
          {att.soort === 'file' && !att.bestand_beschikbaar ? (
            <nldd-text size="xs" color="critical">Bestand niet beschikbaar</nldd-text>
          ) : att.soort === 'file' ? (
            <>
              <nldd-text size="xs" color="secondary">{Math.round((att.bestandsgrootte ?? 0) / 1024)} KB</nldd-text>
              <NlddIconButton
                icon="download"
                accessibleLabel="Downloaden"
                variant="neutral-transparent"
                size="sm"
                onClick={() => window.open(downloadUrl, '_blank')}
              />
            </>
          ) : null}
          <NlddIconButton
            icon="close"
            accessibleLabel="Verwijderen"
            variant="neutral-transparent"
            size="sm"
            onClick={onDelete}
          />
        </nldd-container>
        {isImage && (
          // The hover-reveal zoom affordance over the thumbnail is a real
          // group/group-hover interaction — `group`, `.group-hover-dim-overlay`
          // and `.group-hover-reveal` are real CSS in utilities.css, no
          // nldd-* equivalent for any of the three.
          <button
            type="button"
            onClick={() => onZoom(downloadUrl, att.bestandsnaam ?? 'bijlage')}
            className="plain-button group"
            style={{ position: 'relative', marginLeft: '8px', display: 'block', width: 'fit-content' }}
          >
            {/* A fixed 4:3 box rather than the image's own height: nldd-image
                has no max-height, and a portrait scan would otherwise take the
                whole panel. `contain` shows it uncropped inside that box. */}
            <nldd-image
              src={downloadUrl}
              alt={att.bestandsnaam ?? 'bijlage'}
              width="256"
              aspect-ratio="4/3"
              object-fit="contain"
              shape="rounded"
            />
            <div className="group-hover-dim-overlay" style={{ position: 'absolute', inset: 0, borderRadius: 'var(--semantics-controls-md-corner-radius)', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
              <nldd-icon
                icon="magnifier"
                size="24"
                className="group-hover-reveal"
                style={{ color: 'white' }}
                aria-hidden="true"
              />
            </div>
          </button>
        )}
      </nldd-container>
    </nldd-list-item>
  );
}

interface ContactRowProps {
  naam: string;
  expertise: string | null | undefined;
  rolLabel: string;
  onRemove: () => void;
}

// Expertise is free text, and a tag never shrinks below its full label. As a
// tag beside the name it could take the whole row on a phone and leave the
// name zero wide, one letter per line. As the name's second line it wraps.
function ContactRow({ naam, expertise, rolLabel, onRemove }: ContactRowProps) {
  return (
    <nldd-list-item>
      <nldd-icon-cell icon="person" size="16" />
      <nldd-text-cell
        text={naam}
        width="full"
        {...(expertise ? { 'supporting-text': expertise } : {})}
      />
      <nldd-cell>
        <nldd-tag text={rolLabel} color="neutral" size="sm" />
      </nldd-cell>
      <nldd-cell>
        <NlddIconButton icon="trash" accessibleLabel="Verwijderen" variant="neutral-transparent" size="sm" onClick={onRemove} />
      </nldd-cell>
    </nldd-list-item>
  );
}

interface LinkedNodeRowProps {
  title: string;
  nodeType: string;
  onUnlink: () => void;
}

function LinkedNodeRow({ title, nodeType, onUnlink }: LinkedNodeRowProps) {
  return (
    <nldd-list-item>
      <nldd-icon-cell icon="link" size="16" />
      <nldd-text-cell text={title} width="full" />
      <nldd-cell>
        <nldd-tag text={nodeType} color="neutral" size="sm" />
      </nldd-cell>
      <nldd-cell>
        <NlddIconButton icon="close" accessibleLabel="Ontkoppelen" variant="neutral-transparent" size="sm" onClick={onUnlink} />
      </nldd-cell>
    </nldd-list-item>
  );
}
