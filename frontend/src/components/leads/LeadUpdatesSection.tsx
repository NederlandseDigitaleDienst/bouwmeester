import { useCallback, useEffect, useRef, useState } from 'react';

import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { DetailSection } from '@/components/common/DetailSection';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { Icon } from '@/components/nldd/Icon';
import { orUndef, useNlddEvent } from '@/components/nldd/events';
import { getLeadUpdateEmlUrl } from '@/api/leadUpdates';
import {
  useCreateLeadUpdate,
  useDeleteLeadUpdate,
  useEditLeadUpdate,
  useLeadUpdates,
  useParseLeadUpdate,
  usePublishLeadUpdate,
  useUnpublishLeadUpdate,
} from '@/hooks/useLeadUpdates';
import { formatDateLong } from '@/utils/dates';
import type { LeadUpdatePost } from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';

interface Draft {
  titel: string;
  body_internal: string;
  body_public: string;
  mail_subject: string;
  mail_to: string[];
  mail_cc: string[];
  source_raw_text: string;
}

const emptyDraft = (): Draft => ({
  titel: '',
  body_internal: '',
  body_public: '',
  mail_subject: '',
  mail_to: [],
  mail_cc: [],
  source_raw_text: '',
});

export function LeadUpdatesSection({ leadId }: { leadId: string }) {
  const { data: posts = [] } = useLeadUpdates(leadId);
  const createMutation = useCreateLeadUpdate();
  const editMutation = useEditLeadUpdate();
  const publishMutation = usePublishLeadUpdate();
  const unpublishMutation = useUnpublishLeadUpdate();
  const deleteMutation = useDeleteLeadUpdate();
  const parseMutation = useParseLeadUpdate();

  const [composing, setComposing] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<Draft>(emptyDraft());
  const [rawText, setRawText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [includeAttachments, setIncludeAttachments] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const titelRef = useRef<HTMLElement>(null);
  const mailSubjectRef = useRef<HTMLElement>(null);
  const rawTextRef = useRef<HTMLElement>(null);
  const includeAttachmentsRef = useRef<HTMLElement>(null);
  const fileFieldRef = useRef<HTMLElement & { files?: FileList | File[] }>(null);

  useNlddEvent(titelRef, 'input', (e) => setDraft((d) => ({ ...d, titel: eventTargetValue(e) })));
  useNlddEvent(mailSubjectRef, 'input', (e) => setDraft((d) => ({ ...d, mail_subject: eventTargetValue(e) })));
  useNlddEvent(rawTextRef, 'input', (e) => setRawText(eventTargetValue(e)));
  useNlddEvent(includeAttachmentsRef, 'change', (e) =>
    setIncludeAttachments((e.target as HTMLInputElement | null)?.checked ?? false),
  );
  useNlddEvent(
    fileFieldRef,
    'change',
    useCallback((e: Event) => {
      const picked = (e.target as { files?: FileList | null } | null)?.files;
      setFiles(picked ? Array.from(picked) : []);
    }, []),
  );

  const concepts = posts.filter((p) => !p.published_at);
  const published = posts.filter((p) => p.published_at);

  const startCompose = () => {
    setDraft(emptyDraft());
    setRawText('');
    setFiles([]);
    setIncludeAttachments(false);
    setEditingId(null);
    setComposing(true);
    setError(null);
  };

  const startEdit = (post: LeadUpdatePost) => {
    setDraft({
      titel: post.titel,
      body_internal: post.body_internal ?? '',
      body_public: post.body_public ?? '',
      mail_subject: post.mail_subject ?? '',
      mail_to: post.mail_to ?? [],
      mail_cc: post.mail_cc ?? [],
      source_raw_text: '',
    });
    setRawText('');
    setFiles([]);
    setEditingId(post.id);
    setComposing(true);
    setError(null);
  };

  const cancel = () => {
    setComposing(false);
    setEditingId(null);
    setError(null);
  };

  const runExtract = async (useLeadHistory: boolean) => {
    setError(null);
    try {
      const result = await parseMutation.mutateAsync({
        leadId,
        rawText: rawText || undefined,
        useLeadHistory,
        // Lead-history mode pulls attachments automatically; for raw-input
        // mode it's the user's choice via the checkbox.
        includeAttachments: useLeadHistory ? false : includeAttachments,
        files: files.length ? files : undefined,
      });
      setDraft((d) => ({
        ...d,
        titel: result.titel ?? d.titel,
        body_internal: result.body_internal ?? d.body_internal,
        body_public: result.body_public ?? d.body_public,
        mail_subject: result.mail_subject ?? d.mail_subject,
        mail_to: d.mail_to.length ? d.mail_to : result.suggested_to ?? [],
        mail_cc: d.mail_cc.length ? d.mail_cc : result.suggested_cc ?? [],
        source_raw_text: rawText,
      }));
      // Reset the upload list so the same files don't get re-sent on the
      // next click; the extracted output is now in draft state.
      setFiles([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Onbekende fout bij AI-extract.');
    }
  };

  const handleSave = async (publish: boolean) => {
    if (!draft.titel.trim()) return;
    const payload = {
      titel: draft.titel,
      body_internal: draft.body_internal || null,
      body_public: draft.body_public || null,
      mail_subject: draft.mail_subject || null,
      mail_to: draft.mail_to.length ? draft.mail_to : null,
      mail_cc: draft.mail_cc.length ? draft.mail_cc : null,
    };
    if (editingId) {
      await editMutation.mutateAsync({ leadId, postId: editingId, data: payload });
      if (publish) {
        await publishMutation.mutateAsync({ leadId, postId: editingId });
      }
    } else {
      await createMutation.mutateAsync({
        leadId,
        data: {
          ...payload,
          source_raw_text: draft.source_raw_text || null,
          publish,
        },
      });
    }
    cancel();
  };

  const handleDelete = async () => {
    if (!confirmDelete) return;
    await deleteMutation.mutateAsync({ leadId, postId: confirmDelete });
    setConfirmDelete(null);
  };

  return (
    <DetailSection title="Updates" icon={<Icon name="megaphone" size="sm" />}>
      <nldd-container layout="row" gap="8" vertical-alignment="center" padding-bottom="8">
        <nldd-text size="xs" color="secondary">
          {posts.length === 0 ? 'Nog geen updates' : `${posts.length} totaal`}
        </nldd-text>
        {!composing && (
          <NlddButton variant="secondary" size="sm" onClick={startCompose} text="Nieuwe update" />
        )}
      </nldd-container>

      {composing && (
        <nldd-card background="tinted">
          <nldd-container gap="12" padding="12" padding-bottom="20">
            {!editingId && (
              <nldd-card>
                <nldd-container gap="8" padding="8">
                  <nldd-form-field label="Ruwe invoer (plak tekst, of upload bestand)">
                    <nldd-multi-line-text-field
                      ref={rawTextRef}
                      value={rawText}
                      rows={4}
                      placeholder="Plak hier een mailfragment, gespreksnotitie, of korte beschrijving..."
                    />
                  </nldd-form-field>
                  <nldd-container layout="wrap" gap="8" vertical-alignment="center">
                    <nldd-file-field ref={fileFieldRef} multiple accept=".pdf,.docx,.doc,.odt,.txt,image/*" accessible-label="Bestand toevoegen" />
                    {files.length > 0 && (
                      <nldd-text size="xs" color="secondary">
                        {files.map((f) => f.name).join(', ')}
                      </nldd-text>
                    )}
                  </nldd-container>
                  <nldd-checkbox-field
                    ref={includeAttachmentsRef}
                    checked={orUndef(includeAttachments)}
                    label="Neem bestaande bijlagen op deze lead mee (screenshots, documenten)"
                  />
                  <nldd-container layout="wrap" gap="8" vertical-alignment="center">
                    <NlddButton
                      size="sm"
                      variant="secondary"
                      startIcon="sparkles"
                      onClick={() => runExtract(false)}
                      disabled={
                        parseMutation.isPending ||
                        (!rawText.trim() && files.length === 0 && !includeAttachments)
                      }
                      text="AI: extract uit invoer"
                    />
                    <NlddButton
                      size="sm"
                      variant="secondary"
                      startIcon="sparkles"
                      onClick={() => runExtract(true)}
                      disabled={parseMutation.isPending}
                      title="Genereer een update op basis van notities, contacten, recente activity én bestaande bijlagen op deze lead"
                      text="AI: uit lead-historie"
                    />
                    {parseMutation.isPending && (
                      <nldd-text size="xs" color="secondary">Bezig...</nldd-text>
                    )}
                  </nldd-container>
                  {error && (
                    <nldd-validation-list>
                      <nldd-validation-item>{error}</nldd-validation-item>
                    </nldd-validation-list>
                  )}
                </nldd-container>
              </nldd-card>
            )}

            <nldd-text-field ref={titelRef} value={draft.titel} placeholder="Titel" accessible-label="Titel" />

            <RichTextFormField
              label="Interne mailtekst (voor team)"
              value={draft.body_internal}
              onChange={(v) => setDraft({ ...draft, body_internal: v })}
              rows={6}
            />

            <RichTextFormField
              label="Publieke samenvatting (community-pagina)"
              value={draft.body_public}
              onChange={(v) => setDraft({ ...draft, body_public: v })}
              rows={3}
            />

            <nldd-container gap="8">
              <nldd-form-field label="Mail-onderwerp">
                <nldd-text-field ref={mailSubjectRef} value={draft.mail_subject} />
              </nldd-form-field>
              <EmailListInput
                label="To"
                value={draft.mail_to}
                onChange={(v) => setDraft({ ...draft, mail_to: v })}
              />
              <EmailListInput
                label="Cc"
                value={draft.mail_cc}
                onChange={(v) => setDraft({ ...draft, mail_cc: v })}
              />
            </nldd-container>

            <nldd-container layout="row" gap="8" horizontal-alignment="right">
              <NlddButton variant="secondary" size="sm" onClick={cancel} text="Annuleren" />
              <NlddButton
                variant="secondary"
                size="sm"
                onClick={() => handleSave(false)}
                disabled={!draft.titel.trim() || parseMutation.isPending}
                text="Opslaan als concept"
              />
              <NlddButton
                size="sm"
                onClick={() => handleSave(true)}
                disabled={!draft.titel.trim() || parseMutation.isPending}
                text={editingId ? 'Opslaan + publiceren' : 'Direct publiceren'}
              />
            </nldd-container>
          </nldd-container>
        </nldd-card>
      )}

      {concepts.length > 0 && (
        <nldd-container gap="4" padding-bottom="12">
          <nldd-text size="xs" color="secondary">Concepten</nldd-text>
          <nldd-list appearance="box-tinted" dividers="always" accessible-label="Conceptupdates">
            {concepts.map((post) => (
              <UpdateRow
                key={post.id}
                leadId={leadId}
                post={post}
                onEdit={() => startEdit(post)}
                onPublish={() =>
                  publishMutation.mutate({ leadId, postId: post.id })
                }
                onUnpublish={() =>
                  unpublishMutation.mutate({ leadId, postId: post.id })
                }
                onDelete={() => setConfirmDelete(post.id)}
              />
            ))}
          </nldd-list>
        </nldd-container>
      )}

      {published.length > 0 && (
        <nldd-container gap="4">
          <nldd-text size="xs" color="secondary">Gepubliceerd</nldd-text>
          <nldd-list appearance="box-tinted" dividers="always" accessible-label="Gepubliceerde updates">
            {published.map((post) => (
              <UpdateRow
                key={post.id}
                leadId={leadId}
                post={post}
                onEdit={() => startEdit(post)}
                onPublish={() =>
                  publishMutation.mutate({ leadId, postId: post.id })
                }
                onUnpublish={() =>
                  unpublishMutation.mutate({ leadId, postId: post.id })
                }
                onDelete={() => setConfirmDelete(post.id)}
              />
            ))}
          </nldd-list>
        </nldd-container>
      )}

      <ConfirmDialog
        open={!!confirmDelete}
        title="Update verwijderen?"
        onConfirm={handleDelete}
        onClose={() => setConfirmDelete(null)}
        variant="danger"
      >
        Weet je zeker dat je deze update wilt verwijderen?
      </ConfirmDialog>
    </DetailSection>
  );
}

/** Read a plain input/textarea's value out of a native `input`/`change` event. */
function eventTargetValue(e: Event): string {
  return (e.target as HTMLInputElement | HTMLTextAreaElement | null)?.value ?? '';
}

function UpdateRow({
  leadId,
  post,
  onEdit,
  onPublish,
  onUnpublish,
  onDelete,
}: {
  leadId: string;
  post: LeadUpdatePost;
  onEdit: () => void;
  onPublish: () => void;
  onUnpublish: () => void;
  onDelete: () => void;
}) {
  const isPublished = !!post.published_at;

  const editRef = useRef<HTMLElement>(null);
  const publishRef = useRef<HTMLElement>(null);
  const deleteRef = useRef<HTMLElement>(null);

  useNlddEvent(editRef, 'click', useCallback(() => onEdit(), [onEdit]));
  useNlddEvent(publishRef, 'click', useCallback(() => (isPublished ? onUnpublish() : onPublish()), [isPublished, onUnpublish, onPublish]));
  useNlddEvent(deleteRef, 'click', useCallback(() => onDelete(), [onDelete]));

  return (
    <nldd-list-item>
      <nldd-text-cell width="full" text={post.titel}>
        <span slot="supporting-text">
          <nldd-container gap="2">
            <nldd-text size="xs" color="secondary">
              {isPublished
                ? `Gepubliceerd ${formatDateLong(post.published_at!)}${post.published_by_naam ? ` · ${post.published_by_naam}` : ''}`
                : `Concept · ${formatDateLong(post.created_at)}`}
            </nldd-text>
            {post.body_public && (
              <nldd-text size="xs" color="secondary" className="line-clamp-2 whitespace-pre-wrap">
                {post.body_public}
              </nldd-text>
            )}
          </nldd-container>
        </span>
      </nldd-text-cell>
      <nldd-list-item-segment href={getLeadUpdateEmlUrl(leadId, post.id)} accessible-label="Download .eml voor Outlook" title="Download .eml — opent als nieuw concept in Outlook (Windows) met onderwerp en ontvangers ingevuld">
        <Icon name="envelope" size="sm" />
        Outlook
      </nldd-list-item-segment>
      <nldd-list-item-segment ref={editRef} button accessible-label="Bewerken">
        <Icon name="pencil" size="sm" />
      </nldd-list-item-segment>
      <nldd-list-item-segment ref={publishRef} button accessible-label={isPublished ? 'Depubliceren' : 'Publiceren'}>
        <Icon name={isPublished ? 'eye-slash' : 'globe'} size="sm" />
      </nldd-list-item-segment>
      <nldd-list-item-segment ref={deleteRef} button accessible-label="Verwijderen">
        <Icon name="trash" size="sm" />
      </nldd-list-item-segment>
    </nldd-list-item>
  );
}

function EmailListInput({
  label,
  value,
  onChange,
}: {
  label: string;
  value: string[];
  onChange: (next: string[]) => void;
}) {
  const [text, setText] = useState(value.join(', '));
  const ref = useRef<HTMLElement>(null);

  // Sync local edit-text with the canonical value when the parent updates
  // it (e.g. after AI suggested recipients land via setDraft). Without this
  // the input keeps showing the previous string until the user focuses+blurs.
  useEffect(() => {
    setText(value.join(', '));
  }, [value]);

  useNlddEvent(ref, 'input', useCallback((e: Event) => setText(eventTargetValue(e)), []));
  useNlddEvent(
    ref,
    'blur',
    useCallback(() => {
      const list = text
        .split(/[,;\s]+/)
        .map((s) => s.trim())
        .filter(Boolean);
      onChange(list);
      setText(list.join(', '));
    }, [text, onChange]),
  );

  return (
    <nldd-form-field label={label}>
      <nldd-text-field ref={ref} value={text} placeholder="email@example.org, ..." />
    </nldd-form-field>
  );
}
