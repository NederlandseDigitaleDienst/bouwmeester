import { useCallback, useRef, useState } from 'react';
import { Badge } from '@/components/common/Badge';
import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, orUndef, useNlddEvent, useNlddValue } from '@/components/nldd/events';
import { getMailbriefUrl } from '@/api/initiatieven';
import {
  useInitiatiefUpdates,
  useKlaarOmTeDelen,
  useVrijgegevenVragen,
  useCreateInitiatiefUpdate,
  useEditInitiatiefUpdate,
  usePublishInitiatiefUpdate,
  useUnpublishInitiatiefUpdate,
  useDeleteInitiatiefUpdate,
} from '@/hooks/useInitiatieven';
import type { InitiatiefDetail, InitiatiefUpdatePost, PubliekeCasus, PubliekeVraag } from '@/types';
import { KlaarOmTeDelen } from './KlaarOmTeDelen';
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
 *
 * De tab begint bij "Klaar om te delen": afgeronde onderzoeksvragen en
 * afgeronde casussen met hun lessen. Daar schrijf je per stuk de tekst voor
 * buiten en geef je hem vrij. Een update neemt vrijgegeven vragen en casussen
 * mee; in een nieuwe update staat niets vooraf aangevinkt, je kiest zelf wat
 * meegaat. Een gepubliceerde update is ook als mailbrief te downloaden,
 * een concept voor Outlook zonder ontvangers.
 */
export function InitiatiefUpdates({ initiatief }: { initiatief: InitiatiefDetail }) {
  const canEdit =
    initiatief.access_level === 'eigenaar' || initiatief.access_level === 'contributor';
  const { data: posts = [] } = useInitiatiefUpdates(initiatief.id);
  const { data: vragen = [] } = useVrijgegevenVragen(initiatief.id);
  const { data: klaar } = useKlaarOmTeDelen(initiatief.id);
  // De casussen die een update kan meenemen: afgerond en vrijgegeven.
  const casussen = (klaar?.casussen ?? []).filter((c) => c.published_at);
  const createMutation = useCreateInitiatiefUpdate();
  const editMutation = useEditInitiatiefUpdate();
  const publishMutation = usePublishInitiatiefUpdate();
  const unpublishMutation = useUnpublishInitiatiefUpdate();
  const deleteMutation = useDeleteInitiatiefUpdate();

  const [composing, setComposing] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [draft, setDraft] = useState<{ titel: string; body: string; vraagIds: string[]; casusIds: string[] }>({
    titel: '',
    body: '',
    vraagIds: [],
    casusIds: [],
  });
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);

  const concepts = posts.filter((p) => !p.published_at);
  const published = posts.filter((p) => p.published_at);

  const startCompose = () => {
    // Niets vooraf aangevinkt: je kiest zelf wat meegaat.
    setDraft({ titel: '', body: '', vraagIds: [], casusIds: [] });
    setEditingId(null);
    setComposing(true);
  };

  const startEdit = (post: InitiatiefUpdatePost) => {
    setDraft({
      titel: post.titel,
      body: post.body ?? '',
      vraagIds: post.vragen.map((v) => v.id),
      casusIds: post.casussen.map((c) => c.id),
    });
    setEditingId(post.id);
    setComposing(true);
  };

  const handleSave = async (publish: boolean) => {
    if (!draft.titel.trim()) return;
    if (editingId) {
      await editMutation.mutateAsync({
        initiatiefId: initiatief.id,
        postId: editingId,
        data: { titel: draft.titel, body: draft.body || null, vraag_ids: draft.vraagIds, casus_ids: draft.casusIds },
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
        data: {
          titel: draft.titel,
          body: draft.body || null,
          publish,
          vraag_ids: draft.vraagIds,
          casus_ids: draft.casusIds,
        },
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
            <Kiezen
              titel="Beantwoorde onderzoeksvragen"
              leeg="Nog geen vrijgegeven vragen. Geef een afgeronde vraag vrij onder Klaar om te delen."
              items={vragen.map((v) => ({ id: v.id, label: v.vraag, al: v.in_gepubliceerde_update }))}
              gekozen={draft.vraagIds}
              onChange={(vraagIds) => setDraft({ ...draft, vraagIds })}
            />
            <Kiezen
              titel="Afgeronde casussen en lessen"
              leeg="Nog geen vrijgegeven casussen. Geef een afgeronde casus vrij onder Klaar om te delen."
              items={casussen.map((c) => ({ id: c.id, label: c.public_title ?? c.titel, al: c.in_gepubliceerde_update }))}
              gekozen={draft.casusIds}
              onChange={(casusIds) => setDraft({ ...draft, casusIds })}
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

      <KlaarOmTeDelen initiatief={initiatief} canEdit={canEdit} />

      {concepts.length > 0 && (
        <nldd-container gap="4">
          <nldd-text size="xs" color="secondary">Concepten</nldd-text>
          <nldd-list type="list" appearance="box-tinted">
            {concepts.map((post) => (
              <PostRow
                key={post.id}
                initiatiefId={initiatief.id}
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
                initiatiefId={initiatief.id}
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
            Nog geen updates. Geef hierboven iets vrij onder Klaar om te delen, en klik dan op &quot;Nieuwe update&quot;.
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
  initiatiefId,
  post,
  canEdit,
  onEdit,
  onPublish,
  onUnpublish,
  onDelete,
}: {
  initiatiefId: string;
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
          {post.vragen.length > 0 && <VragenInUpdate vragen={post.vragen} />}
          {post.casussen.length > 0 && <CasussenInUpdate casussen={post.casussen} />}
          {isPublished && post.published_at && (
            <nldd-container layout="wrap" gap="8" vertical-alignment="center">
              <nldd-text size="xs" color="secondary">
                {new Date(post.published_at).toLocaleString('nl-NL')}
                {post.published_by_naam && ` · ${post.published_by_naam}`}
              </nldd-text>
              {canEdit && (
                <nldd-link
                  href={getMailbriefUrl(initiatiefId, post.id)}
                  size="xs"
                  start-icon="envelope"
                  text="Mailbrief voor Outlook"
                  title="Download een .eml: Outlook opent hem als concept, zonder ontvangers. Zet de adressen er zelf in, in BCC."
                />
              )}
            </nldd-container>
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
 * Wat de update meeneemt: vrijgegeven vragen of casussen. Wat niet
 * vrijgegeven is, staat hier niet; dat blijft binnen.
 */
function Kiezen({
  titel,
  leeg,
  items,
  gekozen,
  onChange,
}: {
  titel: string;
  leeg: string;
  items: { id: string; label: string; al: boolean }[];
  gekozen: string[];
  onChange: (ids: string[]) => void;
}) {
  return (
    <nldd-container gap="4">
      <nldd-text size="sm" weight="medium">
        {titel}
      </nldd-text>
      {items.length === 0 ? (
        <nldd-text size="xs" color="secondary">
          {leeg}
        </nldd-text>
      ) : (
        items.map((item) => (
          <Vinkje
            key={item.id}
            label={item.label}
            al={item.al}
            checked={gekozen.includes(item.id)}
            onChange={(aan) => onChange(aan ? [...gekozen, item.id] : gekozen.filter((id) => id !== item.id))}
          />
        ))
      )}
    </nldd-container>
  );
}

function Vinkje({
  label,
  al,
  checked,
  onChange,
}: {
  label: string;
  al: boolean;
  checked: boolean;
  onChange: (aan: boolean) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'change', (e) => onChange(!!(e as CustomEvent<{ checked?: boolean }>).detail?.checked));
  // Het vinkje heeft geen eigen hulptekst, dus de stand staat eronder.
  return (
    <nldd-container gap="2">
      <nldd-checkbox-field ref={ref} label={label} checked={orUndef(checked)} />
      {al && (
        <nldd-container padding-left="32">
          <nldd-text size="xs" color="secondary">
            Stond al in een gepubliceerde update
          </nldd-text>
        </nldd-container>
      )}
    </nldd-container>
  );
}

/** De vragen onder een update, zoals ze ook buiten staan. */
function VragenInUpdate({ vragen }: { vragen: PubliekeVraag[] }) {
  return (
    <nldd-container gap="4">
      <nldd-text size="xs" weight="medium" color="secondary">Beantwoorde onderzoeksvragen</nldd-text>
      {vragen.map((v) => (
        <nldd-container key={v.id} gap="2">
          <nldd-text size="sm" weight="medium">{v.vraag}</nldd-text>
          <nldd-text size="sm" color="secondary">
            <RichTextDisplay content={v.antwoord} />
          </nldd-text>
          {v.verslag && (
            <nldd-text size="xs" color="secondary">{`Met onderzoeksverslag: ${v.verslag.bestandsnaam}`}</nldd-text>
          )}
        </nldd-container>
      ))}
    </nldd-container>
  );
}

/** De casussen onder een update, zoals ze ook buiten staan. */
function CasussenInUpdate({ casussen }: { casussen: PubliekeCasus[] }) {
  return (
    <nldd-container gap="4">
      <nldd-text size="xs" weight="medium" color="secondary">
        Afgeronde casussen
      </nldd-text>
      {casussen.map((c) => (
        <nldd-container key={c.id} gap="2">
          <nldd-text size="sm" weight="medium">
            {c.titel}
          </nldd-text>
          <nldd-text size="sm" color="secondary">
            <RichTextDisplay content={c.resultaat} />
          </nldd-text>
          {c.lessen && (
            <nldd-text size="sm" color="secondary">
              <strong>Wat we leerden: </strong>
              <RichTextDisplay content={c.lessen} />
            </nldd-text>
          )}
        </nldd-container>
      ))}
    </nldd-container>
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
