import { useCallback, useState, type ReactNode } from 'react';
import { MarkdownRenderer } from '@/components/common/MarkdownRenderer';
import { ImageLightbox } from '@/components/common/ImageLightbox';
import { ChatActionCard } from './ChatActionCard';
import { ChatPendingActionCard } from './ChatPendingActionCard';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { useLeadDetail } from '@/contexts/LeadDetailContext';
import { chatAttachmentPreviewUrl, isImageContentType } from '@/api/chat';
import type { ChatMessage } from '@/api/chat';
import { surfaceContext } from '@/components/nldd/surface';

interface ChatMessageBubbleProps {
  message: ChatMessage;
}

/**
 * Fix LLM output that uses "N.\n**Title**:" instead of proper markdown headings.
 * Converts patterns like "1.\n**Bestaanszekerheid**:" into "### 1. Bestaanszekerheid"
 */
function fixNumberedBoldHeadings(text: string): string {
  return text.replace(
    /^(\d+)\.\n\*\*(.+?)\*\*:?$/gm,
    (_match, num, title) => `### ${num}. ${title}`,
  );
}

export function ChatMessageBubble({ message }: ChatMessageBubbleProps) {
  const isUser = message.role === 'user';
  const { openNodeDetail } = useNodeDetail();
  const { openTaskDetail } = useTaskDetail();
  const { openLeadDetail } = useLeadDetail();
  const [lightboxSrc, setLightboxSrc] = useState<{ src: string; alt: string } | null>(null);

  const handleBmLink = useCallback(
    (type: 'node' | 'task' | 'lead', id: string) => {
      if (type === 'node') {
        openNodeDetail(id);
      } else if (type === 'task') {
        openTaskDetail(id);
      } else if (type === 'lead') {
        openLeadDetail(id);
      }
    },
    [openNodeDetail, openTaskDetail, openLeadDetail],
  );

  const attachments = message.attachments ?? [];

  return (
    <>
      <nldd-container
        layout="row"
        gap="0"
        horizontal-alignment={isUser ? 'right' : 'left'}
      >
        <Bubble isUser={isUser}>
          {/* Attachment previews (user messages) */}
          {attachments.length > 0 && (
            <nldd-container layout="wrap" gap="6" padding-bottom="6">
              {attachments.map((att) =>
                isImageContentType(att.content_type) ? (
                  // Thumbnail button opening the lightbox. `plain-button`
                  // strips the user-agent chrome so the thumbnail is the whole
                  // control, without a grey frame around the image.
                  <button
                    key={att.id}
                    onClick={() =>
                      setLightboxSrc({
                        src: chatAttachmentPreviewUrl(att.id),
                        alt: att.bestandsnaam,
                      })
                    }
                    className="plain-button hover-dim"
                    style={{ display: 'block', cursor: 'pointer' }}
                  >
                    <nldd-image
                      src={chatAttachmentPreviewUrl(att.id)}
                      alt={att.bestandsnaam}
                      width="64"
                      height={64}
                      object-fit="cover"
                      shape="rounded"
                    />
                  </button>
                ) : (
                  // nldd-token rather than nldd-tag: a tag never shrinks
                  // below its label, and a long file name would run out of
                  // the bubble; the token cuts it off with an ellipsis.
                  <nldd-token key={att.id} text={att.bestandsnaam} title={att.bestandsnaam} />
                ),
              )}
            </nldd-container>
          )}

          {isUser ? (
            // pre-wrap keeps the user's own line breaks. On a span inside,
            // not on the host, as in RichTextDisplay: on the host it also
            // renders the whitespace around the component's slot.
            <nldd-text size="sm">
              <span className="whitespace-pre-wrap">{message.content}</span>
            </nldd-text>
          ) : message.content ? (
            // MarkdownRenderer styles its own headings and lists, so the
            // wrapper carries nothing.
            <div>
              <MarkdownRenderer content={fixNumberedBoldHeadings(message.content)} compact onBmLink={handleBmLink} />
            </div>
          ) : null}

          {/* Completed actions */}
          {message.actions.length > 0 && (
            <nldd-container gap="6" padding-top="8">
              {message.actions.map((action, i) => (
                <ChatActionCard key={action.entity_id ?? `action-${i}`} action={action} />
              ))}
            </nldd-container>
          )}

          {/* Pending actions awaiting confirmation */}
          {message.pending_actions.length > 0 && (
            <nldd-container gap="6" padding-top="8">
              {message.pending_actions.map((pa) => (
                <ChatPendingActionCard key={pa.action_id} pendingAction={pa} />
              ))}
            </nldd-container>
          )}
        </Bubble>
      </nldd-container>

      {/* Image lightbox */}
      {lightboxSrc && (
        <ImageLightbox
          src={lightboxSrc.src}
          alt={lightboxSrc.alt}
          onClose={() => setLightboxSrc(null)}
        />
      )}
    </>
  );
}

/**
 * The bubble around one message.
 *
 * The assistant's is an nldd-box. The user's own is filled, and nldd-box was
 * checked for that: it draws tinted, base and critical surfaces only, no
 * accent fill, so that one surface stays a styled div on the same radius
 * token nldd-box uses.
 */
function Bubble({ isUser, children }: { isUser: boolean; children: ReactNode }) {
  const inner = (
    <nldd-container padding-inline="12" padding-block="8">
      {children}
    </nldd-container>
  );
  return isUser ? (
    <div
      style={{
        maxWidth: '85%',
        borderRadius: 'var(--semantics-surfaces-corner-radius)',
        backgroundColor: 'var(--primitives-color-lintblauw-600)',
        color: 'var(--primitives-color-coolgray-0)',
        ...surfaceContext('var(--primitives-color-coolgray-0)', 'var(--primitives-color-lintblauw-600)'),
      }}
    >
      {inner}
    </div>
  ) : (
    // max-width: nldd-box has no width attribute of its own.
    <nldd-box style={{ maxWidth: '85%' }}>{inner}</nldd-box>
  );
}
