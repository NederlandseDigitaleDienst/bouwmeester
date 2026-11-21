import { useRef, useState } from 'react';
import { Modal } from '@/components/common/Modal';
import { useNlddEvent } from '@/components/nldd/events';
import { NlddButton } from '@/components/nldd/NlddButton';

interface AutoTagDialogProps {
  open: boolean;
  onClose: () => void;
  matchedTags: string[];
  suggestedNewTags: string[];
  onAccept: (tags: { name: string; isNew: boolean }[]) => void;
  onSkip: () => void;
}

export function AutoTagDialog({
  open,
  onClose,
  matchedTags,
  suggestedNewTags,
  onAccept,
  onSkip,
}: AutoTagDialogProps) {
  const [selected, setSelected] = useState<Set<string>>(
    new Set([...matchedTags, ...suggestedNewTags]),
  );

  const toggleTag = (name: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });
  };

  const handleAcceptAll = () => {
    const newTagSet = new Set(suggestedNewTags);
    const tags = [...selected].map((name) => ({
      name,
      isNew: newTagSet.has(name),
    }));
    onAccept(tags);
    onClose();
  };

  const handleSkip = () => {
    onSkip();
    onClose();
  };

  return (
    <Modal
      open={open}
      onClose={handleSkip}
      title="Tag-suggesties"
      footer={
        <nldd-container layout="row" gap="8" horizontal-alignment="right">
          <NlddButton variant="neutral-transparent" onClick={handleSkip} text="Overslaan" />
          <NlddButton
            onClick={handleAcceptAll}
            disabled={selected.size === 0}
            startIcon="sparkles"
            text={`Toevoegen (${selected.size})`}
          />
        </nldd-container>
      }
    >
      <nldd-container gap="12">
        <nldd-text size="sm" color="secondary">
          <p>Deze node heeft weinig tags. Wil je de volgende suggesties toevoegen?</p>
        </nldd-text>

        {matchedTags.length > 0 && (
          <nldd-container gap="6">
            <nldd-text size="xs" weight="medium" color="secondary"><p>Bestaande tags</p></nldd-text>
            <nldd-container layout="wrap" gap="6">
              {matchedTags.map((tag) => (
                <TagChip
                  key={tag}
                  name={tag}
                  selected={selected.has(tag)}
                  onToggle={() => toggleTag(tag)}
                />
              ))}
            </nldd-container>
          </nldd-container>
        )}

        {suggestedNewTags.length > 0 && (
          <nldd-container gap="6">
            <nldd-text size="xs" weight="medium" color="secondary"><p>Nieuwe tags</p></nldd-text>
            <nldd-container layout="wrap" gap="6">
              {suggestedNewTags.map((tag) => (
                <TagChip
                  key={tag}
                  name={tag}
                  isNew
                  selected={selected.has(tag)}
                  onToggle={() => toggleTag(tag)}
                />
              ))}
            </nldd-container>
          </nldd-container>
        )}
      </nldd-container>
    </Modal>
  );
}

function TagChip({
  name,
  isNew = false,
  selected,
  onToggle,
}: {
  name: string;
  isNew?: boolean;
  selected: boolean;
  onToggle: () => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'change', onToggle);
  return (
    <nldd-toggle-button
      ref={ref}
      text={name}
      icon={selected ? 'check-mark' : isNew ? 'plus' : 'check-mark'}
      selected={selected ? true : undefined}
      size="sm"
    />
  );
}
