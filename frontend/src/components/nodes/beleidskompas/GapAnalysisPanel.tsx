import { useState } from 'react';
import { AiActionButton } from '@/components/common/AiActionButton';
import { analyzeGaps } from '@/api/llm';
import { NODE_TYPE_LABELS, type GapAnalysisResponse, type NodeType } from '@/types';

interface GapAnalysisPanelProps {
  dossierId: string;
}

export function GapAnalysisPanel({ dossierId }: GapAnalysisPanelProps) {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<GapAnalysisResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleAnalyze = async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await analyzeGaps(dossierId);
      setResult(res);
    } catch {
      setError('Fout bij uitvoeren van de analyse.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <nldd-container gap="12">
      <nldd-container layout="row" gap="8" vertical-alignment="center">
        <nldd-title size={6}><h3>Voltooiheidsanalyse</h3></nldd-title>
        <nldd-spacer size="flexible" />
        <AiActionButton
          label="Analyse voltooiheid"
          loading={loading}
          onClick={handleAnalyze}
        />
      </nldd-container>

      {error && <nldd-text size="xs" color="critical">{error}</nldd-text>}

      {result && (
        <nldd-container gap="12">
          {/* Score */}
          <nldd-container layout="row" gap="8" vertical-alignment="center">
            <nldd-icon
              icon={result.completed_count === result.total_steps ? 'check-mark-circle' : 'exclamation-triangle'}
              size="16"
              color={result.completed_count === result.total_steps ? 'success' : 'warning'}
              aria-hidden="true"
            />
            <nldd-text size="sm" weight="medium">
              {result.completed_count}/{result.total_steps} stappen voltooid
            </nldd-text>
          </nldd-container>

          {/* Gap list */}
          {result.gaps.length > 0 && (
            <nldd-container gap="6">
              {result.gaps.map((gap) => (
                <nldd-inline-dialog
                  key={gap.step_number}
                  variant="alert"
                  size="md"
                  horizontal-alignment="left"
                  text={`Stap ${gap.step_number}: ${gap.step_question}`}
                  supporting-text={`Ontbreekt: ${gap.missing_types.map((t) => NODE_TYPE_LABELS[t as NodeType] ?? t).join(', ')}`}
                />
              ))}
            </nldd-container>
          )}

          {/* LLM narrative */}
          {result.narrative && (
            <nldd-inline-dialog
              size="md"
              horizontal-alignment="left"
              icon="sparkles"
              icon-color="accent"
              text="AI-analyse"
              supporting-text={result.narrative}
            />
          )}

          {/* Recommendations */}
          {result.recommendations.length > 0 && (
            <nldd-container gap="4">
              <nldd-container layout="row" gap="6" vertical-alignment="center">
                <nldd-icon icon="lightbulb" size="16" color="warning" aria-hidden="true" />
                <nldd-text size="xs" color="secondary" weight="medium">Aanbevelingen</nldd-text>
              </nldd-container>
              <nldd-rich-text>
                <ul>
                  {result.recommendations.map((rec, i) => (
                    <li key={i}>{rec}</li>
                  ))}
                </ul>
              </nldd-rich-text>
            </nldd-container>
          )}
        </nldd-container>
      )}
    </nldd-container>
  );
}
