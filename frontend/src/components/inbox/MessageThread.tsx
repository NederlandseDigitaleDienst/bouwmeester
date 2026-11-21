import { useState, useEffect, useRef } from 'react';
import { RichTextDisplay } from '@/components/common/RichTextDisplay';
import { RichTextEditor } from '@/components/common/RichTextEditor';
import { Modal } from '@/components/common/Modal';
import { useNotification, useReplies, useReplyToNotification, useMarkNotificationRead, useReactToMessage } from '@/hooks/useNotifications';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { timeAgo } from '@/utils/dates';
import { EmojiPicker } from './EmojiPicker';
import { ReactionBar } from './ReactionBar';
import type { Notification, ReactionSummary } from '@/types';
import { NlddButton } from '@/components/nldd/NlddButton';
import { surfaceTextColor } from '@/components/nldd/surface';

interface MessageThreadProps {
  notificationId: string;
  onClose: () => void;
}

interface MessageBubbleProps {
  message: Notification;
  isCurrentUser: boolean;
  reactions: ReactionSummary[];
  onReact: (emoji: string) => void;
}

function MessageBubble({ message, isCurrentUser, reactions, onReact }: MessageBubbleProps) {
  const [showPicker, setShowPicker] = useState(false);
  const [hovered, setHovered] = useState(false);

  const body = (
    <>
      {!isCurrentUser && message.sender_name && (
        <nldd-text size="xs" weight="medium" color="secondary">
          <p>{message.sender_name}</p>
        </nldd-text>
      )}
      <RichTextDisplay content={message.message} fallback="" />
      <nldd-text size="xxs" color="secondary">
        <p>{timeAgo(message.created_at)}</p>
      </nldd-text>
    </>
  );

  return (
    <nldd-container layout="row" horizontal-alignment={isCurrentUser ? 'right' : 'left'}>
      <div style={{ maxWidth: '80%' }}>
        {/* The row holding the bubble and its hover-revealed react-button, in
            reading order or reversed for the current user's own messages: no
            nldd-container row-reverse equivalent, so this direction switch
            stays plain CSS. */}
        <div
          style={{ display: 'flex', alignItems: 'flex-start', gap: '4px', flexDirection: isCurrentUser ? 'row-reverse' : 'row' }}
          onMouseEnter={() => setHovered(true)}
          onMouseLeave={() => { if (!showPicker) setHovered(false); }}
        >
          {isCurrentUser ? (
            // nldd-box was checked: it draws tinted, base and critical
            // surfaces only, no accent fill, so your own bubble keeps this
            // one filled surface. Radius is the surface token nldd-box uses.
            <div
              style={{
                borderRadius: 'var(--semantics-surfaces-corner-radius)',
                backgroundColor: 'var(--primitives-color-accent-600)',
                ...surfaceTextColor('var(--primitives-color-neutral-0)'),
              }}
            >
              <nldd-container gap="4" padding-inline="16" padding-block="10">{body}</nldd-container>
            </div>
          ) : (
            <nldd-box>
              <nldd-container gap="4" padding-inline="16" padding-block="10">{body}</nldd-container>
            </nldd-box>
          )}
          <div className={hovered || showPicker ? 'shrink-0' : 'shrink-0 invisible'}>
            <EmojiPicker
              icon="face-smiling"
              accessibleLabel="Reageer met een emoji"
              variant="neutral-tinted"
              onSelect={(emoji) => { onReact(emoji); setHovered(false); }}
              onOpenChange={(open) => { setShowPicker(open); if (!open) setHovered(false); }}
            />
          </div>
        </div>
        <nldd-container layout="row" horizontal-alignment={isCurrentUser ? 'right' : 'left'}>
          <ReactionBar reactions={reactions} onReact={onReact} />
        </nldd-container>
      </div>
    </nldd-container>
  );
}

export function MessageThread({ notificationId, onClose }: MessageThreadProps) {
  const [replyText, setReplyText] = useState('');
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const { currentPerson } = useCurrentPerson();
  const { data: parentMessage } = useNotification(notificationId);
  const { data: replies } = useReplies(notificationId);
  const replyMutation = useReplyToNotification();
  const markRead = useMarkNotificationRead();
  const reactMutation = useReactToMessage();

  const handleReact = (messageId: string, emoji: string) => {
    if (!currentPerson) return;
    reactMutation.mutate({
      notificationId: messageId,
      data: { sender_id: currentPerson.id, emoji },
    });
  };

  // Scroll to bottom when replies change (new messages arrive or on first load)
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [replies]);

  // Mark as read when opened — only if current user is the recipient (person_id),
  // not the sender.  After a reply the backend marks the root unread for the
  // recipient; we must not immediately re-mark it read for the sender.
  useEffect(() => {
    if (
      parentMessage &&
      !parentMessage.is_read &&
      currentPerson?.id === parentMessage.person_id
    ) {
      markRead.mutate(parentMessage.id);
    }
  }, [parentMessage?.id, parentMessage?.is_read]); // eslint-disable-line react-hooks/exhaustive-deps

  const handleSendReply = () => {
    if (!currentPerson || !replyText.trim()) return;
    replyMutation.mutate(
      {
        notificationId,
        data: {
          sender_id: currentPerson.id,
          message: replyText.trim(),
        },
      },
      {
        onSuccess: () => setReplyText(''),
      },
    );
  };

  if (!parentMessage) return null;

  return (
    <Modal
      open
      onClose={onClose}
      title={parentMessage.title}
      size="lg"
      entityLabel={
        replies ? `${replies.length} ${replies.length === 1 ? 'reactie' : 'reacties'}` : 'Laden...'
      }
      footer={
        <nldd-container layout="row" gap="8" width="full" vertical-alignment="top">
          {/* fit-content + row-fill rather than the container default of full:
              that default takes a hard 100% of the row, leaving the button
              less room than its own label, which then wraps into a two-line
              block. */}
          <nldd-container width="fit-content" className="row-fill">
            <RichTextEditor
              value={replyText}
              onChange={setReplyText}
              placeholder="Typ een reactie..."
              rows={2}
              autoFocus
            />
          </nldd-container>
          <NlddButton
            size="sm"
            onClick={handleSendReply}
            disabled={!replyText.trim() || replyMutation.isPending || !currentPerson}
            loading={replyMutation.isPending}
            startIcon="paper-plane"
            text="Verstuur"
          />
        </nldd-container>
      }
    >
      <nldd-container gap="12">
        {/* Original message */}
        <MessageBubble
          message={parentMessage}
          isCurrentUser={parentMessage.sender_id === currentPerson?.id}
          reactions={parentMessage.reactions}
          onReact={(emoji) => handleReact(parentMessage.id, emoji)}
        />

        {/* Replies */}
        {replies?.map((reply) => (
          <MessageBubble
            key={reply.id}
            message={reply}
            isCurrentUser={reply.sender_id === currentPerson?.id}
            reactions={reply.reactions}
            onReact={(emoji) => handleReact(reply.id, emoji)}
          />
        ))}
        <div ref={messagesEndRef} />
      </nldd-container>
    </Modal>
  );
}
