import { useEffect, useRef } from 'react';
import { apiGet } from '@/api/client';
import { useNlddEvent } from '@/components/nldd/events';
import { mentionToMarkdown, type MentionKind } from '@/utils/mentions';
import { formatFunctie, titleCase } from '@/types';
import type { Person, OrganisatieEenheid } from '@/types';

/**
 * A description editor, as an `nldd-text-editor`.
 *
 * The document is plain markdown, not a ProseMirror JSON tree: the storage
 * format is the design system's, and `RichTextDisplay` reads the same thing.
 *
 * Mentions survive as markdown links carrying a scheme (`[@Anne](user:<id>)`).
 * The `@` list is the element's built-in mention, which writes that format
 * itself; the `#` list is ours, on its own trigger, and its `insert` writes the
 * same shape with our schemes. See `utils/mentions.ts` for the format and
 * `core/tiptap_markdown.py` for the backend side of it.
 */

interface MentionSearchResult {
  id: string;
  label: string;
  subtitle?: string;
  type: string;
}

/** One row in a typeahead list, in the element's shape. */
interface Candidate {
  id: string;
  text: string;
  supportingText?: string;
  avatar?: { src?: string; type?: 'person' | 'organization' };
  icon?: string;
}

/**
 * `@`: people and organisational units.
 *
 * No guard on an empty query: the element opens its list the moment the
 * trigger is typed, and returning nothing there means pressing `@` appears to
 * do nothing at all. The endpoints answer a blank query with their first page,
 * which is the right thing to show.
 */
async function searchPeopleAndOrgs(query: string): Promise<Candidate[]> {
  try {
    const [people, orgs] = await Promise.all([
      apiGet<Person[]>('/api/people/search', { q: query, limit: 8 }),
      apiGet<OrganisatieEenheid[]>('/api/organisatie/search', { q: query, limit: 5 }),
    ]);
    return [
      ...people.map((p) => ({
        id: `${p.id}`,
        text: p.naam,
        supportingText: formatFunctie(p.functie),
        avatar: { type: 'person' as const },
      })),
      ...orgs.map((o) => ({
        id: `org:${o.id}`,
        text: o.naam,
        supportingText: titleCase(o.type.replace(/_/g, ' ')),
        avatar: { type: 'organization' as const },
      })),
    ];
  } catch {
    // A failed lookup shows no candidates rather than an error in the menu:
    // the person is mid-sentence and can keep typing.
    return [];
  }
}

/** `#`: corpus nodes and tasks. */
async function searchMentionables(query: string): Promise<Candidate[]> {
  try {
    const results = await apiGet<MentionSearchResult[]>('/api/mentions/search', {
      q: query,
      limit: 10,
    });
    return results.map((r) => ({
      id: `${r.type}:${r.id}`,
      text: r.label,
      supportingText: r.subtitle ?? r.type,
      icon: r.type === 'task' ? 'check-list' : 'file-text',
    }));
  } catch {
    return [];
  }
}

/**
 * The kind is carried in the candidate id, because a list returns more than one
 * kind and the element hands back only the candidate it was given.
 */
function splitCandidateId(id: string, fallback: MentionKind): { kind: MentionKind; id: string } {
  const match = /^(org|node|task|person):(.*)$/.exec(id);
  if (!match) return { kind: fallback, id };
  const kind = match[1] === 'org' ? 'organisatie' : (match[1] as MentionKind);
  return { kind, id: match[2] };
}

interface RichTextEditorProps {
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
  autoFocus?: boolean;
  disabled?: boolean;
  /**
   * Blocks typing without taking the editor out of the tab order, which is what
   * `disabled` would do. Used while an answer is being generated: the text
   * stays selectable and readable.
   */
  readOnly?: boolean;
  /** Rendered bare, for a composition that draws its own frame (a chat input). */
  bare?: boolean;
  /**
   * Enter verstuurt: deze functie in plaats van een nieuwe regel. Shift+Enter
   * blijft een nieuwe regel, en zolang de @- of #-lijst open is kiest Enter
   * daar een kandidaat.
   */
  onEnter?: () => void;
}

export function RichTextEditor({
  value,
  onChange,
  placeholder,
  rows = 3,
  autoFocus,
  disabled,
  readOnly,
  bare = false,
  onEnter,
}: RichTextEditorProps) {
  const ref = useRef<HTMLElement>(null);

  // Enter vangen vóór de editor hem krijgt: een listener in de capture-fase
  // op het element zelf loopt vóór CodeMirror in de shadow-DOM, die Enter
  // anders als nieuwe regel verwerkt. De @- en #-lijst zijn CodeMirror-
  // tooltips in die shadow-DOM; is er een open, dan laten we Enter gaan.
  const onEnterRef = useRef(onEnter);
  useEffect(() => {
    onEnterRef.current = onEnter;
  }, [onEnter]);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const opEnter = (e: KeyboardEvent) => {
      if (!onEnterRef.current || e.key !== 'Enter' || e.shiftKey || e.isComposing) return;
      if (el.shadowRoot?.querySelector('.cm-tooltip-autocomplete')) return;
      e.preventDefault();
      e.stopPropagation();
      onEnterRef.current();
    };
    el.addEventListener('keydown', opEnter, true);
    return () => el.removeEventListener('keydown', opEnter, true);
  }, []);

  // `typeaheads` and `mentionSource` are properties, not attributes: a function
  // cannot travel through an attribute, and React would stringify it.
  useEffect(() => {
    const el = ref.current as
      | (HTMLElement & {
          mentionSource?: (q: string) => Promise<Candidate[]>;
          typeaheads?: unknown[];
        })
      | null;
    if (!el) return;

    el.mentionSource = searchPeopleAndOrgs;
    el.typeaheads = [
      {
        trigger: '#',
        source: searchMentionables,
        insert: (candidate: Candidate) => {
          const { kind, id } = splitCandidateId(candidate.id, 'node');
          return `${mentionToMarkdown(kind, id, candidate.text)} `;
        },
      },
    ];
  }, []);

  // The built-in @-mention writes `[text](user:id)` with the candidate's own id.
  // An organisation comes through the same list, so its token is rewritten to
  // the org scheme after insertion.
  useNlddEvent(ref, 'nldd-text-editor-mention', (event) => {
    const detail = (event as CustomEvent<{ id: string; text: string; from: number; to: number }>)
      .detail;
    if (!detail?.id?.startsWith('org:')) return;
    const el = ref.current as
      | (HTMLElement & { replaceRange?: (from: number, to: number, text: string) => void })
      | null;
    const { kind, id } = splitCandidateId(detail.id, 'person');
    el?.replaceRange?.(detail.from, detail.to, mentionToMarkdown(kind, id, detail.text));
  });

  useNlddEvent(ref, 'input', (event) => {
    const detail = (event as CustomEvent<{ value?: string }>).detail;
    onChange(detail?.value ?? (event.target as HTMLElement & { value?: string }).value ?? '');
  });

  // Writing `value` on every render would reset the caret mid-word, so only
  // when it has actually diverged (an external reset, a refetch).
  useEffect(() => {
    const el = ref.current as (HTMLElement & { value?: string }) | null;
    if (el && el.value !== value) el.value = value;
  }, [value]);

  useEffect(() => {
    if (!autoFocus) return;
    (ref.current as (HTMLElement & { focus?: () => void }) | null)?.focus?.();
  }, [autoFocus]);

  return (
    <nldd-text-editor
      ref={ref}
      appearance={bare ? 'simple' : 'input-field'}
      rows={rows}
      resize="auto"
      {...(placeholder ? { placeholder } : {})}
      {...(disabled ? { disabled: true } : {})}
      {...(readOnly ? { readonly: true } : {})}
    />
  );
}
