import { useState, useRef, useEffect, useMemo, useCallback } from 'react';
import { useSearch } from '@/hooks/useSearch';
import { usePermissions } from '@/hooks/usePermissions';
import { eventValue, useNlddEvent, useNlddOverlay } from '@/components/nldd/events';
import {
  ALL_RESULT_TYPES,
  FilterChips,
  GroupedListboxRows,
  useResultNavigation,
} from './SearchResults';
import { SEARCH_TYPE_PERMISSIONS, type SearchResultType } from '@/types';

interface SearchModalProps {
  open: boolean;
  onClose: () => void;
}

/**
 * Command palette, opened with "/". Rendered at the document root by
 * AppLayout, deliberately outside the split view (rule: overlays never sit as
 * a light-DOM sibling of the split view or they get slotted into the main
 * pane).
 *
 * `nldd-list type="listbox"` owns the search field, ArrowUp/Down/Home/End,
 * Enter-to-activate and Escape-to-clear-then-close itself (see list.js): when
 * the search value is empty, Escape falls through instead of being consumed,
 * which is what lets this component's own Escape handler close the modal. So
 * there is no input, selected-index state or keydown listener here.
 */
export function SearchModal({ open, onClose }: SearchModalProps) {
  const [query, setQuery] = useState('');
  const [activeTypes, setActiveTypes] = useState<SearchResultType[]>([]);
  const listRef = useRef<HTMLElement>(null);
  const windowRef = useRef<HTMLElement>(null);
  const { hasPermission } = usePermissions();

  const allowedTypes = useMemo(
    () => ALL_RESULT_TYPES.filter((t) => hasPermission(SEARCH_TYPE_PERMISSIONS[t])),
    [hasPermission],
  );

  const filterTypes = activeTypes.length > 0 ? activeTypes : undefined;
  const { data, isLoading } = useSearch(query, filterTypes);
  const results = data?.results ?? [];

  const handleResultClick = useResultNavigation(onClose);

  const toggleType = useCallback((type: SearchResultType) => {
    setActiveTypes((prev) => (prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]));
  }, []);

  const handleSearchInput = useCallback((e: Event) => setQuery(eventValue(e)), []);
  useNlddEvent(listRef, 'input', handleSearchInput);

  // Mirror `open` onto the window's imperative API rather than mounting and
  // unmounting it, so the open and close animation plays. nldd-window is a
  // native <dialog>, so it brings the backdrop, the scroll lock, the focus trap
  // and Escape with it; none of that is this component's job.
  useNlddOverlay(windowRef, open, onClose);

  // Reset state and focus the listbox's own search field when the modal opens.
  useEffect(() => {
    if (!open) return;
    setQuery('');
    setActiveTypes([]);
    requestAnimationFrame(() => {
      const input = listRef.current?.shadowRoot?.querySelector('input');
      input?.focus();
    });
  }, [open]);

  return (
    // A native <dialog>, always modal: it owns the backdrop, the top layer, the
    // focus trap and Escape.
    //
    // The surface belongs here rather than on the list: `variant="box-base"`
    // paints only `.list__main` (the options), because the search bar and the
    // toolbar are meant to float above the box rather than sit on a panel. In a
    // window there is nothing behind them, so the window provides the surface.
    <nldd-window
      ref={windowRef}
      accessible-label="Zoeken"
      centered
      top="15vh"
      width="min(672px, calc(100vw - 32px))"
    >
      <nldd-container padding="16">
        <nldd-list
          ref={listRef}
          type="listbox"
          appearance="box-base"
          height="50vh"
          accessible-label="Zoeken"
        >
          {/* The toolbar slot lays its own children out (row, wrap, gap), so the
              button group goes straight in without a wrapper of its own. */}
          <FilterChips
            slot="toolbar"
            activeTypes={activeTypes}
            onToggle={toggleType}
            allowedTypes={allowedTypes}
          />

          {/* Zero rows always routes here (never `no-results`, which is only for
              rows hidden by client-side filtering — this search is server-driven
              and simply renders nothing while there are no hits). */}
          {isLoading ? (
            <nldd-inline-dialog slot="empty" variant="loading" text="Zoeken..." />
          ) : query.length < 2 ? (
            <nldd-inline-dialog slot="empty" text="Voer minimaal 2 tekens in om te zoeken." />
          ) : (
            <nldd-inline-dialog slot="empty" text={`Geen resultaten voor "${query}"`} />
          )}

          {!isLoading && <GroupedListboxRows results={results} onResultClick={handleResultClick} />}
        </nldd-list>
      </nldd-container>
    </nldd-window>
  );
}
