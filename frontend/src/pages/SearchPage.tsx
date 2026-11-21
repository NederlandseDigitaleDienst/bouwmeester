import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { useSearch } from '@/hooks/useSearch';
import {
  ALL_RESULT_TYPES,
  FilterChips,
  SearchResultsList,
  useResultNavigation,
} from '@/components/search/SearchResults';
import { usePermissions } from '@/hooks/usePermissions';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { SEARCH_TYPE_PERMISSIONS, type SearchResultType } from '@/types';

export function SearchPage() {
  const [query, setQuery] = useState('');
  const [activeTypes, setActiveTypes] = useState<SearchResultType[]>([]);
  const inputRef = useRef<HTMLElement>(null);
  const { hasPermission } = usePermissions();

  const allowedTypes = useMemo(
    () => ALL_RESULT_TYPES.filter((t) => hasPermission(SEARCH_TYPE_PERMISSIONS[t])),
    [hasPermission],
  );

  const filterTypes = activeTypes.length > 0 ? activeTypes : undefined;
  const { data, isLoading, isFetched } = useSearch(query, filterTypes);

  const handleResultClick = useResultNavigation();

  const toggleType = useCallback((type: SearchResultType) => {
    setActiveTypes((prev) => (prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]));
  }, []);

  useNlddEvent(
    inputRef,
    'input',
    useCallback((e: Event) => setQuery(eventValue(e)), []),
  );

  // Focus on mount, same as the old input's `autoFocus`.
  useEffect(() => {
    inputRef.current?.focus();
  }, []);

  // Focus search input on "/" key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (
        e.key === '/' &&
        !e.ctrlKey &&
        !e.metaKey &&
        !e.altKey &&
        document.activeElement !== inputRef.current &&
        !(document.activeElement instanceof HTMLInputElement) &&
        !(document.activeElement instanceof HTMLTextAreaElement) &&
        !(document.activeElement as HTMLElement)?.isContentEditable
      ) {
        e.preventDefault();
        inputRef.current?.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => document.removeEventListener('keydown', handleKeyDown);
  }, []);

  return (
    <nldd-simple-section width="768px" horizontal-alignment="center">
      <nldd-container gap="24">
        {/* Page header */}
        <nldd-text size="sm" color="secondary">
          <p>Doorzoek alles: beleidscorpus, taken, personen, organisaties, parlementaire items, tags en leads.</p>
        </nldd-text>

        {/* Search input */}
        <nldd-search-field
          ref={inputRef}
          value={query}
          placeholder="Zoek op titel, naam, beschrijving, trefwoord..."
          accessible-label="Zoeken"
        />

        {/* Filter chips */}
        <FilterChips activeTypes={activeTypes} onToggle={toggleType} allowedTypes={allowedTypes} />

        {/* Results */}
        <SearchResultsList
          query={query}
          data={data}
          isLoading={isLoading}
          isFetched={isFetched}
          onResultClick={handleResultClick}
        />
      </nldd-container>
    </nldd-simple-section>
  );
}
