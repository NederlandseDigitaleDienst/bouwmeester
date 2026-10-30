import { Fragment, useCallback, useRef } from 'react';
import DOMPurify from 'dompurify';
import { useNavigate } from 'react-router-dom';
import { Badge } from '@/components/common/Badge';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { EmptyState } from '@/components/common/EmptyState';
import { useNodeDetail } from '@/contexts/NodeDetailContext';
import { useTaskDetail } from '@/contexts/TaskDetailContext';
import { useLeadDetail } from '@/contexts/LeadDetailContext';
import { richTextToPlain } from '@/utils/richtext';
import { orUndef, useNlddEvent } from '@/components/nldd/events';
import { NlddListItemButton } from '@/components/nldd/NlddLink';
import {
  SEARCH_RESULT_TYPE_LABELS,
  SEARCH_RESULT_TYPE_COLORS,
  NODE_TYPE_LABELS,
  NODE_STATUS_LABELS,
  TASK_STATUS_LABELS,
  formatOrganisatieType,
  PARLEMENTAIR_TYPE_LABELS,
  LEAD_STAGE_LABELS,
  formatFunctie,
  type SearchResultType,
  type SearchResult,
  type SearchResponse,
} from '@/types';

export const ALL_RESULT_TYPES: SearchResultType[] = [
  'corpus_node',
  'task',
  'person',
  'organisatie_eenheid',
  'parlementair_item',
  'tag',
  'lead',
];

const SUBTITLE_LABEL_MAPS: Partial<
  Record<SearchResultType, Record<string, string>>
> = {
  corpus_node: { ...NODE_TYPE_LABELS, ...NODE_STATUS_LABELS },
  task: TASK_STATUS_LABELS,
  parlementair_item: PARLEMENTAIR_TYPE_LABELS,
  lead: LEAD_STAGE_LABELS as Record<string, string>,
};

function formatSubtitle(result: SearchResult): string | undefined {
  if (!result.subtitle) return undefined;
  if (result.result_type === 'person') {
    return formatFunctie(result.subtitle);
  }
  if (result.result_type === 'organisatie_eenheid') {
    return formatOrganisatieType(result.subtitle);
  }
  const map = SUBTITLE_LABEL_MAPS[result.result_type];
  return map?.[result.subtitle] ?? result.subtitle;
}

function groupResults(results: SearchResult[]) {
  return results.reduce(
    (groups, result) => {
      const key = result.result_type;
      if (!groups[key]) groups[key] = [];
      groups[key].push(result);
      return groups;
    },
    {} as Record<string, SearchResult[]>,
  );
}

export function useResultNavigation(onNavigated?: () => void) {
  const navigate = useNavigate();
  const { openNodeDetail } = useNodeDetail();
  const { openTaskDetail } = useTaskDetail();
  const { openLeadDetail } = useLeadDetail();

  return (result: SearchResult) => {
    onNavigated?.();
    if (result.result_type === 'corpus_node') {
      openNodeDetail(result.id);
    } else if (result.result_type === 'task') {
      openTaskDetail(result.id);
    } else if (result.result_type === 'lead') {
      openLeadDetail(result.id);
    } else {
      navigate(result.url);
    }
  };
}

interface FilterChipsProps {
  activeTypes: SearchResultType[];
  onToggle: (type: SearchResultType) => void;
  allowedTypes?: SearchResultType[];
  className?: string;
  /** Lets a caller place the group in a slot of its parent, e.g. a list's toolbar. */
  slot?: string;
}

export function FilterChips({
  activeTypes,
  onToggle,
  allowedTypes,
  className = '',
  slot,
}: FilterChipsProps) {
  const visibleTypes = allowedTypes ?? ALL_RESULT_TYPES;
  const ref = useRef<HTMLElement>(null);

  // Each nldd-toggle-button fires its own `change` ({ selected, value }), which
  // bubbles to the group; `value` is the SearchResultType that was toggled.
  const handleChange = useCallback(
    (event: Event) => {
      const value = (event as CustomEvent<{ value?: string }>).detail?.value;
      if (value) onToggle(value as SearchResultType);
    },
    [onToggle],
  );
  useNlddEvent(ref, 'change', handleChange);

  return (
    <nldd-toggle-button-group
      ref={ref}
      type="checkbox"
      size="sm"
      className={className}
      {...(slot ? { slot } : {})}
    >
      {visibleTypes.map((type) => (
        // `selected` means "you picked this one", so an empty filter leaves
        // every button unselected rather than marking them all. Treating "no
        // filter" as "all selected" painted the whole row solid and left no
        // visible difference once you actually chose a type.
        <nldd-toggle-button
          key={type}
          value={type}
          text={SEARCH_RESULT_TYPE_LABELS[type]}
          selected={orUndef(activeTypes.includes(type))}
        />
      ))}
    </nldd-toggle-button-group>
  );
}

/**
 * A single search hit inside the command-palette listbox.
 *
 * Rendered as an `nldd-list-item` option: the list's own search input drives
 * ArrowUp/Down/Home/End/Enter, and Enter triggers this row's inner action
 * (the button `onClick` below) without DOM focus ever leaving the input — see
 * `nldd-list type="listbox"` in list.js.
 */
function ResultItem({ result, onClick }: { result: SearchResult; onClick: () => void }) {
  return (
    <NlddListItemButton onClick={onClick}>
      <ResultItemContent result={result} compact />
    </NlddListItemButton>
  );
}

function ResultItemContent({ result, compact }: { result: SearchResult; compact?: boolean }) {
  return (
    <nldd-container layout="row" width="full" gap="12" vertical-alignment="top">
      <nldd-container width="full" min-width="0" gap="2">
        <nldd-container layout="row" gap="8" vertical-alignment="center">
          <Badge color={SEARCH_RESULT_TYPE_COLORS[result.result_type]} dot>
            {SEARCH_RESULT_TYPE_LABELS[result.result_type]}
          </Badge>
          {result.subtitle && (
            <nldd-text size="xs" color="secondary">{formatSubtitle(result)}</nldd-text>
          )}
        </nldd-container>
        <nldd-text size="sm" weight="medium">{result.title}</nldd-text>
        {result.description && (
          <nldd-text size="xs" color="secondary" className={compact ? 'line-clamp-1' : 'line-clamp-2'}>
            {richTextToPlain(result.description)}
          </nldd-text>
        )}
        {result.highlights &&
          result.highlights.length > 0 &&
          (compact ? (
            // Sanitized <mark> HTML goes on an inner span, not on nldd-text:
            // setting innerHTML on the custom element itself would bypass its
            // slot rendering.
            <nldd-text size="xs" color="secondary" className="line-clamp-1">
              <span
                dangerouslySetInnerHTML={{
                  __html: DOMPurify.sanitize(result.highlights[0], {
                    ALLOWED_TAGS: ['mark'],
                  }),
                }}
              />
            </nldd-text>
          ) : (
            <nldd-container gap="2">
              {result.highlights.map((h, i) => (
                // Same inner-span reasoning as above.
                <nldd-text key={i} size="xs" color="secondary">
                  <span
                    dangerouslySetInnerHTML={{
                      __html: DOMPurify.sanitize(h, {
                        ALLOWED_TAGS: ['mark'],
                      }),
                    }}
                  />
                </nldd-text>
              ))}
            </nldd-container>
          ))}
      </nldd-container>
      {result.score > 0 && (
        <nldd-text size="xs" color="secondary">
          {Math.round(result.score * 100)}%
        </nldd-text>
      )}
    </nldd-container>
  );
}

interface SearchResultsListProps {
  query: string;
  data: SearchResponse | undefined;
  isLoading: boolean;
  isFetched: boolean;
  onResultClick: (result: SearchResult) => void;
}

/**
 * Full-page results (SearchPage): plain result cards, no listbox semantics.
 * The command-palette rendering for SearchModal's `nldd-list type="listbox"`
 * lives in `ResultItem` / `GroupedListboxRows` instead, since a listbox owns
 * its own search field and active-option handling that this page doesn't use.
 */
export function SearchResultsList({ query, data, isLoading, isFetched, onResultClick }: SearchResultsListProps) {
  const results = data?.results ?? [];
  const grouped = groupResults(results);

  if (isLoading) {
    return (
      <nldd-container padding-block="32">
        <LoadingSpinner />
      </nldd-container>
    );
  }

  if (query.length >= 2 && isFetched && results.length === 0) {
    return (
      <EmptyState
        icon="question-mark-circle"
        title="Geen resultaten"
        description={`Geen resultaten gevonden voor "${query}". Probeer een andere zoekterm.`}
      />
    );
  }

  if (results.length > 0) {
    return (
      <nldd-container gap="24">
        <nldd-text size="sm" color="secondary">
          {data?.total ?? results.length} resultaten voor &ldquo;{data?.query ?? query}&rdquo;
        </nldd-text>
        {Object.entries(grouped).map(([resultType, groupResults]) => (
          <nldd-container key={resultType} gap="8">
            <nldd-text size="xs" weight="bold" color="secondary">
              {SEARCH_RESULT_TYPE_LABELS[resultType as SearchResultType]} ({groupResults.length})
            </nldd-text>
            <nldd-container gap="8">
              {groupResults.map((result) => (
                <ResultCard
                  key={`${result.result_type}-${result.id}`}
                  result={result}
                  onClick={() => onResultClick(result)}
                />
              ))}
            </nldd-container>
          </nldd-container>
        ))}
      </nldd-container>
    );
  }

  if (query.length < 2 && !isFetched) {
    return (
      <nldd-container gap="12" horizontal-alignment="center" padding="48">
        <nldd-icon icon="magnifier" size="40" color="secondary-content" aria-hidden="true" />
        <nldd-text size="sm" color="secondary" horizontal-alignment="center">
          Voer minimaal 2 tekens in om te zoeken.
        </nldd-text>
      </nldd-container>
    );
  }

  return null;
}

function ResultCard({ result, onClick }: { result: SearchResult; onClick: () => void }) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', onClick);
  return (
    <nldd-card ref={ref} button>
      <ResultItemContent result={result} />
    </nldd-card>
  );
}

/**
 * Grouped rows for the command-palette listbox (SearchModal): a plain-text
 * group label between runs of `nldd-list-item` options, all inside the same
 * `nldd-list type="listbox"` so arrow-key navigation and the active option
 * span every group. `nldd-list` has no built-in group heading for listbox
 * rows, and its keyboard/active-option logic queries `:scope > nldd-list-item`
 * directly, so the label has to sit as a direct-child sibling of the items
 * rather than wrap them in a container div — that would hide them from it.
 */
export function GroupedListboxRows({
  results,
  onResultClick,
}: {
  results: SearchResult[];
  onResultClick: (result: SearchResult) => void;
}) {
  const grouped = groupResults(results);
  return (
    <>
      {Object.entries(grouped).map(([resultType, groupResults]) => (
        <Fragment key={resultType}>
          {/* Must stay a direct-child sibling of the nldd-list-item rows (see
              the function doc above), so this can't be an nldd-container
              either — the list's listbox logic queries `:scope > nldd-list-item`
              and any wrapper here is invisible to it the same way a div is. The
              padding stays on the plain div. */}
          <div style={{ paddingInline: '20px', paddingTop: '12px', paddingBottom: '4px' }} role="presentation">
            <nldd-text size="xs" weight="medium" color="secondary">
              {SEARCH_RESULT_TYPE_LABELS[resultType as SearchResultType]} ({groupResults.length})
            </nldd-text>
          </div>
          {groupResults.map((result) => (
            <ResultItem
              key={`${result.result_type}-${result.id}`}
              result={result}
              onClick={() => onResultClick(result)}
            />
          ))}
        </Fragment>
      ))}
    </>
  );
}
