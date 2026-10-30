import { useCallback, useRef, useState } from 'react';
import { Badge } from '@/components/common/Badge';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, useNlddEvent, useNlddValue } from '@/components/nldd/events';
import {
  useInitiatiefUpdates,
  useCreateInitiatiefUpdate,
  useEditInitiatiefUpdate,
  usePublishInitiatiefUpdate,
  useUnpublishInitiatiefUpdate,
  useDeleteInitiatiefUpdate,
} from '@/hooks/useInitiatieven';
import type { InitiatiefDetail, InitiatiefUpdatePost } from '@/types';
import { SectionHeading } from './SectionHeading';
import { NlddButton } from '@/components/nldd/NlddButton';

/** Controlled `nldd-text-field` for an update post's title. */
function UpdateTitleField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddValue(ref, value);
  useNlddEvent(ref, 'input', useCallback((e: Event) => onChange(eventValue(e)), [onChange]));
  return <nldd-text-field ref={ref} placeholder="Titel" accessible-label="Titel" />;
}

/**
 * The "Updates" tab: posts for the public page. A draft stays here; a
 * published one appears on `/c/:slug` as soon as the public page is on.
 */
export function InitiatiefUpdates({ initiatief }: { initiatief: InitiatiefDetail }) {
  const canEdit =
    initiatief.access_level === 'eigenaar' || initiatief.access_level === 'contributor';
  const { data: posts = [] } = useInitiatiefUpdates(initiatief.id);
  const createMutation = useCreateInitiatiefUpdate();
  const editMutation = useEditInitiatiefUpdate();
  const publishMutation = usePublishInitiatiefUpdate();
  const unpublishMutation = useUnpublishInitiatiefUpdate();
  const deleteMutation = useDeleteInitiatiefUpdate();

  const [composing, setComposing] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState({ titel: '', body: '' });
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const concepts = posts.filter((p) => !p.published_at);
  const published = posts.filter((p) => p.published_at);

  const startCompose = () => {
    setDraft({ titel: '', body: '' });
    setEditingId(null);
    setComposing(true);
  };

  const startEdit = (post: InitiatiefUpdatePost) => {
    setDraft({ titel: post.titel, body: post.body ?? '' });
    setEditingId(post.id);
    setComposing(true);
  };

  const handleSave = async (publish: boolean) => {
    if (!draft.titel.trim()) return;
    if (editingId) {
      await editMutation.mutateAsync({
        initiatiefId: initiatief.id,
        postId: editingId,
        data: { titel: draft.titel, body: draft.body || null },
      });
      if (publish) {
        await publishMutation.mutateAsync({
          initiatiefId: initiatief.id,
          postId: editingId,
        });
      }
    } else {
      await createMutation.mutateAsync({
        initiatiefId: initiatief.id,
        data: { titel: draft.titel, body: draft.body || null, publish },
      });
    }
    setComposing(false);
    setEditingId(null);
  };

  const handlePublish = (post: InitiatiefUpdatePost) =>
    publishMutation.mutate({
      initiatiefId: initiatief.id,
      postId: post.id,
    });

  const handleUnpublish = (post: InitiatiefUpdatePost) =>
    unpublishMutation.mutate({
      initiatiefId: initiatief.id,
      postId: post.id,
    });

  const handleDelete = async () => {
    if (!confirmDelete) return;
    await deleteMutation.mutateAsync({
      initiatiefId: initiatief.id,
      postId: confirmDelete,
    });
    setConfirmDelete(null);
  };

  return (
    <nldd-container gap="8">
      <nldd-container layout="row" width="full" gap="8" vertical-alignment="center">
        {/* The heading takes what the button does not need, rather than the
            row pushing both to one side. */}
        <nldd-container width="fit-content" className="row-fill">
          <SectionHeading icon="megaphone" text={`Updates (${posts.length})`} />
        </nldd-container>
        {canEdit && !composing && (
          <NlddButton variant="secondary" size="sm" onClick={startCompose} text="Nieuwe update" />
        )}
      </nldd-container>

      <PublicPageNote initiatief={initiatief} />

      {composing && (
        <nldd-card>
          <nldd-container gap="8" padding="12">
            <UpdateTitleField
              value={draft.titel}
              onChange={(v) => setDraft({ ...draft, titel: v })}
            />
            <RichTextFormField
              label="Inhoud"
              value={draft.body}
              onChange={(value) => setDraft({ ...draft, body: value })}
              rows={4}
            />
            <nldd-container layout="row" gap="8" horizontal-alignment="right">
              <NlddButton
                variant="secondary"
                size="sm"
                onClick={() => {
                  setComposing(false);
                  setEditingId(null);
                }}
                text="Annuleren"
              />
              <NlddButton
                variant="secondary"
                size="sm"
                onClick={() => handleSave(false)}
                disabled={!draft.titel.trim()}
                text="Opslaan als concept"
              />
              <NlddButton
                size="sm"
                onClick={() => handleSave(true)}
                disabled={!draft.titel.trim()}
                text={editingId ? 'Opslaan + publiceren' : 'Direct publiceren'}
              />
            </nldd-container>
          </nldd-container>
        </nldd-card>
      )}

      {concepts.length > 0 && (
        <nldd-container gap="4">
          <nldd-text size="xs" color="secondary">Concepten</nldd-text>
          <nldd-list type="list" appearance="box-tinted">
            {concepts.map((post) => (
              <PostRow
                key={post.id}
                post={post}
                canEdit={canEdit}
                onEdit={() => startEdit(post)}
                onPublish={() => handlePublish(post)}
                onUnpublish={() => handleUnpublish(post)}
                onDelete={() => setConfirmDelete(post.id)}
              />
            ))}
          </nldd-list>
        </nldd-container>
      )}

      {published.length > 0 ? (
        <nldd-container gap="4">
          <nldd-text size="xs" color="secondary">Gepubliceerd</nldd-text>
          <nldd-list type="list" appearance="box-tinted">
            {published.map((post) => (
              <PostRow
                key={post.id}
                post={post}
                canEdit={canEdit}
                onEdit={() => startEdit(post)}
                onPublish={() => handlePublish(post)}
                onUnpublish={() => handleUnpublish(post)}
                onDelete={() => setConfirmDelete(post.id)}
              />
            ))}
          </nldd-list>
        </nldd-container>
      ) : (
        concepts.length === 0 &&
        !composing && (
          <nldd-text size="sm" color="secondary">
            Nog geen updates. Klik op &quot;Nieuwe update&quot; om iets te publiceren.
          </nldd-text>
        )
      )}

      <ConfirmDialog
        open={!!confirmDelete}
        onClose={() => setConfirmDelete(null)}
        onConfirm={handleDelete}
        title="Update verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
        loading={deleteMutation.isPending}
      >
        Weet je zeker dat je deze update wilt verwijderen?
      </ConfirmDialog>
    </nldd-container>
  );
}

function PostRow({
  post,
  canEdit,
  onEdit,
  onPublish,
  onUnpublish,
  onDelete,
}: {
  post: InitiatiefUpdatePost;
  canEdit: boolean;
  onEdit: () => void;
  onPublish: () => void;
  onUnpublish: () => void;
  onDelete: () => void;
}) {
  const isPublished = !!post.published_at;
  return (
    <nldd-list-item>
      <nldd-container layout="row" width="full" gap="8" horizontal-alignment="right" vertical-alignment="top">
        <nldd-container gap="4" width="full">
          <nldd-container layout="row" gap="8" vertical-alignment="center">
            <nldd-text-cell text={post.titel} width="fit-content" />
            {isPublished ? (
              <Badge color="groen">Gepubliceerd</Badge>
            ) : (
              <Badge color="coolgray">Concept</Badge>
            )}
          </nldd-container>
          {post.body && (
            <nldd-text size="sm" color="secondary">
              <RichTextDisplay content={post.body} />
            </nldd-text>
          )}
          {isPublished && post.published_at && (
            <nldd-text size="xs" color="secondary">
              {new Date(post.published_at).toLocaleString('nl-NL')}
              {post.published_by_naam && ` · ${post.published_by_naam}`}
            </nldd-text>
          )}
        </nldd-container>
        {canEdit && (
          <div className="hug">
            <NlddIconButton
              icon="pencil"
              accessibleLabel="Bewerken"
              variant="neutral-transparent"
              size="sm"
              onClick={onEdit}
            />
            {isPublished ? (
              <NlddIconButton
                icon="eye-slash"
                accessibleLabel="Terugtrekken naar concept"
                variant="neutral-transparent"
                size="sm"
                onClick={onUnpublish}
              />
            ) : (
              <NlddIconButton
                icon="eye"
                accessibleLabel="Publiceren"
                variant="neutral-transparent"
                size="sm"
                onClick={onPublish}
              />
            )}
            <NlddIconButton
              icon="trash"
              accessibleLabel="Verwijderen"
              variant="neutral-transparent"
              size="sm"
              onClick={onDelete}
            />
          </div>
        )}
      </nldd-container>
    </nldd-list-item>
  );
}

/**
 * Where a published update ends up. Without this the tab says "publiceren"
 * while nothing may be public at all: the page is opt-in and off by default.
 */
function PublicPageNote({ initiatief }: { initiatief: InitiatiefDetail }) {
  if (initiatief.public_page_enabled && initiatief.slug) {
    return (
      <nldd-container layout="row" gap="4" vertical-alignment="center">
        <nldd-text size="xs" color="secondary">Gepubliceerde updates staan op</nldd-text>
        <nldd-link
          href={`/c/${initiatief.slug}`}
          target="_blank"
          size="xs"
          text={`/c/${initiatief.slug}`}
          end-icon="external-link"
        />
      </nldd-container>
    );
  }
  return (
    <nldd-text size="xs" color="secondary">
      De publieke pagina staat uit, dus gepubliceerde updates zijn nog nergens te zien. Zet
      hem aan onder Instellingen.
    </nldd-text>
  );
}
