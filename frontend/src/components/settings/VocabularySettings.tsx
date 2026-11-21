import { useVocabulary } from '@/contexts/VocabularyContext';
import { VOCABULARY_LABELS, type VocabularyId } from '@/vocabulary';
import { NlddButton } from '@/components/nldd/NlddButton';
import { Icon } from '@/components/nldd/Icon';

export function VocabularySettings() {
  const { vocabularyId, setVocabularyId } = useVocabulary();

  return (
    <nldd-card>
      <nldd-container padding="24" gap="16">
        <nldd-container layout="row" gap="12" vertical-alignment="center">
          <Icon name="book" size="lg" />
          <nldd-container gap="2">
            <nldd-title size="display-5"><h2>Vocabulaire</h2></nldd-title>
            <nldd-text size="sm" color="secondary">
              <p>Kies de terminologie die je wilt gebruiken in de applicatie.</p>
            </nldd-text>
          </nldd-container>
        </nldd-container>

        <nldd-container layout="row" gap="8">
          {(Object.keys(VOCABULARY_LABELS) as VocabularyId[]).map((id) => (
            <NlddButton
              key={id}
              text={VOCABULARY_LABELS[id]}
              variant={vocabularyId === id ? 'accent-transparent' : 'secondary'}
              onClick={() => setVocabularyId(id)}
            />
          ))}
        </nldd-container>
      </nldd-container>
    </nldd-card>
  );
}
