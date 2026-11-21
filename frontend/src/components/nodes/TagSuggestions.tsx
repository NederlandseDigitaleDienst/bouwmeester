import { useState } from 'react';
import { AiActionButton } from '@/components/common/AiActionButton';
import { NlddButton } from '@/components/nldd/NlddButton';
import { suggestTags } from '@/api/llm';
import type { TagSuggestionResponse } from '@/types';

interface TagSuggestionsProps {
  title: string;
  description?: string;
  nodeType: string;
  /** Tags already on the node — these are filtered from matched suggestions */
  existingTagNames?: string[];
  onAcceptTag: (tagName: string, isNew: boolean) => void;
}

export function TagSuggestions({
  title,
  description,
  nodeType,
  existingTagNames = [],
  onAcceptTag,
}: TagSuggestionsProps) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<TagSuggestionResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [acceptedTags, setAcceptedTags] = useState<Set<string>>(new Set());

  const handleSuggest = async () => {
    if (!title.trim()) return;
    setLoading(true);
    setError(null);
    setResult(null);
    setAcceptedTags(new Set());
    try {
      const res = await suggestTags({
        title: title.trim(),
        description: description?.trim() || undefined,
        node_type: nodeType,
      });
      if (!res.available) {
        setError('Tag-suggesties zijn niet beschikbaar (geen LLM-provider geconfigureerd).');
        return;
      }
      setResult(res);
    } catch {
      setError('Fout bij ophalen van tag-suggesties.');
    } finally {
      setLoading(false);
    }
  };

  const handleAccept = (tagName: string, isNew: boolean) => {
    setAcceptedTags((prev) => new Set([...prev, tagName]));
    onAcceptTag(tagName, isNew);
  };

  const existingSet = new Set(existingTagNames.map((n) => n.toLowerCase()));
  const filteredMatched = result?.matched_tags.filter(
    (t) => !existingSet.has(t.toLowerCase()),
  ) ?? [];

  const hasResults = filteredMatched.length > 0 || (result?.suggested_new_tags.length ?? 0) > 0;

  return (
    <nldd-container gap="8">
      <AiActionButton
        label="Tags suggereren"
        loading={loading}
        onClick={handleSuggest}
        disabled={!title.trim()}
      />

      {error && <nldd-text size="xs" color="critical"><p>{error}</p></nldd-text>}

      {result && !hasResults && (
        <nldd-text size="xs" color="secondary"><p>Geen suggesties gevonden.</p></nldd-text>
      )}

      {result && hasResults && (
        <nldd-container gap="8">
          {filteredMatched.length > 0 && (
            <nldd-container gap="4">
              <nldd-text size="xs" color="secondary"><p>Bestaande tags</p></nldd-text>
              <nldd-container layout="wrap" gap="6">
                {filteredMatched.map((tag) => (
                  <TagChip
                    key={tag}
                    name={tag}
                    accepted={acceptedTags.has(tag)}
                    onAccept={() => handleAccept(tag, false)}
                  />
                ))}
              </nldd-container>
            </nldd-container>
          )}

          {result.suggested_new_tags.length > 0 && (
            <nldd-container gap="4">
              <nldd-text size="xs" color="secondary"><p>Nieuwe tags</p></nldd-text>
              <nldd-container layout="wrap" gap="6">
                {result.suggested_new_tags.map((tag) => (
                  <TagChip
                    key={tag}
                    name={tag}
                    isNew
                    accepted={acceptedTags.has(tag)}
                    onAccept={() => handleAccept(tag, true)}
                  />
                ))}
              </nldd-container>
            </nldd-container>
          )}
        </nldd-container>
      )}
    </nldd-container>
  );
}

function TagChip({
  name,
  isNew = false,
  accepted,
  onAccept,
}: {
  name: string;
  isNew?: boolean;
  accepted: boolean;
  onAccept: () => void;
}) {
  if (accepted) {
    return <nldd-tag text={name} icon="check-mark" color="success" size="sm" />;
  }

  return (
    <NlddButton
      text={name}
      variant="neutral-tinted"
      size="xs"
      startIcon={isNew ? 'plus' : 'check-mark'}
      onClick={onAccept}
    />
  );
}
