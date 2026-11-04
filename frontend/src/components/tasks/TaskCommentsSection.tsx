import { useRef, useState } from 'react';

import { ConfirmDialog } from '@/components/common/ConfirmDialog';
import { DetailSection } from '@/components/common/DetailSection';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { Icon } from '@/components/nldd/Icon';
import { NlddButton } from '@/components/nldd/NlddButton';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { useAuth } from '@/contexts/AuthContext';
import { useAddTaskComment, useDeleteTaskComment, useTaskComments } from '@/hooks/useTasks';
import type { TaskComment } from '@/types';
import { timeAgo } from '@/utils/dates';
import { richTextToPlain } from '@/utils/richtext';

/** Leeg is leeg, ook als de editor een lege TipTap-doc teruggeeft. */
function isRichTextEmpty(content: string): boolean {
  return !richTextToPlain(content).trim();
}

/**
 * Het gesprek over een taak, oudste bovenaan en het invoerveld eronder, zoals
 * een commentaarveld in Jira. @-vermeldingen sturen een melding (backend).
 *
 * Enter verstuurt, Shift+Enter is een nieuwe regel; met de @-lijst open kiest
 * Enter een persoon. Zonder opmerkingen staat er alleen het invoerveld.
 *
 * Verwijderen kan de auteur of een beheerder (de backend bewaakt dat ook),
 * altijd zichtbaar, met een bevestiging. Lokaal zonder ingelogde persoon
 * (dev-modus) mag het ook; de backend laat het daar toe.
 */
export function TaskCommentsSection({ taskId }: { taskId: string }) {
  const { data: comments = [] } = useTaskComments(taskId);
  const addComment = useAddTaskComment();
  const deleteComment = useDeleteTaskComment();
  const { person } = useAuth();
  const [content, setContent] = useState('');
  const [weg, setWeg] = useState<TaskComment | null>(null);
  // Enter en een klik op Plaatsen kunnen kort na elkaar komen; één keer plaatsen.
  const bezig = useRef(false);

  const plaats = async () => {
    if (bezig.current || isRichTextEmpty(content)) return;
    bezig.current = true;
    try {
      await addComment.mutateAsync({ taskId, data: { content } });
      setContent('');
    } catch {
      // toast is al getoond
    } finally {
      bezig.current = false;
    }
  };

  const verwijder = async () => {
    if (!weg || bezig.current) return;
    bezig.current = true;
    try {
      await deleteComment.mutateAsync({ taskId, commentId: weg.id });
      setWeg(null);
    } catch {
      // toast is al getoond
    } finally {
      bezig.current = false;
    }
  };

  return (
    <DetailSection title="Opmerkingen" icon={<Icon name="message-rectangle-text" size="sm" />} count={comments.length} separated>
      {comments.length > 0 && (
        <nldd-container gap="12">
          {comments.map((c) => {
            const magWeg = !person || person.is_admin || (c.author_id !== null && c.author_id === person.id);
            return (
              <div key={c.id} style={{ display: 'flex', gap: '10px' }}>
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
                  <nldd-icon icon="person" size="16" aria-hidden="true" />
                </div>
                <nldd-container gap="2" width="full">
                  <nldd-container layout="row" gap="8" vertical-alignment="center">
                    <nldd-text size="xs" weight="medium">{c.author_naam ?? 'Onbekend'}</nldd-text>
                    <nldd-text size="xs" color="secondary">{timeAgo(c.created_at)}</nldd-text>
                    {magWeg && (
                      <NlddIconButton
                        icon="trash"
                        accessibleLabel="Opmerking verwijderen"
                        variant="neutral-transparent"
                        size="sm"
                        onClick={() => setWeg(c)}
                        className="margin-left-auto"
                      />
                    )}
                  </nldd-container>
                  <nldd-text size="sm">
                    <RichTextDisplay content={c.content} fallback="" />
                  </nldd-text>
                </nldd-container>
              </div>
            );
          })}
        </nldd-container>
      )}
      <nldd-container gap="8">
        <RichTextFormField
          label="Nieuwe opmerking"
          required
          value={content}
          onChange={setContent}
          onEnter={() => void plaats()}
          rows={2}
          placeholder="Wat wil je over deze taak kwijt? Enter verstuurt, Shift+Enter is een nieuwe regel. @ noemt iemand."
        />
        <nldd-container layout="row" horizontal-alignment="right">
          <NlddButton size="sm" startIcon="message-rectangle-text" onClick={() => void plaats()} loading={addComment.isPending} disabled={isRichTextEmpty(content)} text="Plaatsen" />
        </nldd-container>
      </nldd-container>
      <ConfirmDialog
        open={!!weg}
        onClose={() => setWeg(null)}
        onConfirm={verwijder}
        title="Opmerking verwijderen"
        confirmLabel="Verwijderen"
        variant="danger"
        loading={deleteComment.isPending}
      >
        Deze opmerking wordt definitief verwijderd.
      </ConfirmDialog>
    </DetailSection>
  );
}
