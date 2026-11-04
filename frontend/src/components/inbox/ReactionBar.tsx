import { useCallback, useRef, useState } from 'react';
import { useNlddEvent } from '@/components/nldd/events';
import { EmojiPicker } from './EmojiPicker';
import type { ReactionSummary } from '@/types';

interface ReactionChipProps {
  reaction: ReactionSummary;
  onReact: (emoji: string) => void;
}

function ReactionChip({ reaction, onReact }: ReactionChipProps) {
  const ref = useRef<HTMLElement>(null);
  const handleClick = useCallback(() => onReact(reaction.emoji), [onReact, reaction.emoji]);
  useNlddEvent(ref, 'click', handleClick);

  return (
    <nldd-button
      ref={ref}
      size="xs"
      appearance={reaction.reacted_by_me ? 'accent-transparent' : 'neutral-transparent'}
      text={`${reaction.emoji} ${reaction.count}`}
      accessible-label={`${reaction.emoji} ${reaction.count}, ${reaction.sender_names.join(', ')}`}
    />
  );
}

interface ReactionBarProps {
  reactions: ReactionSummary[];
  onReact: (emoji: string) => void;
}

export function ReactionBar({ reactions, onReact }: ReactionBarProps) {
  const [pickerOpen, setPickerOpen] = useState(false);

  if (reactions.length === 0 && !pickerOpen) {
    return null;
  }

  return (
    <nldd-container layout="wrap" gap="4" vertical-alignment="center">
      {reactions.map((r) => (
        <ReactionChip key={r.emoji} reaction={r} onReact={onReact} />
      ))}
      <EmojiPicker
        icon="face-smiling-badge-plus"
        accessibleLabel="Reactie toevoegen"
        size="xs"
        onSelect={onReact}
        onOpenChange={setPickerOpen}
      />
    </nldd-container>
  );
}
