import { useState, useRef, useEffect, useLayoutEffect, useCallback, type ReactNode, type RefObject } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { useNlddEvent, useNlddValue, eventValue } from '@/components/nldd/events';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { useVocabulary } from '@/contexts/VocabularyContext';
import { useAuth } from '@/contexts/AuthContext';
import { VOCABULARY_LABELS, type VocabularyId } from '@/vocabulary';
import { NotificationBell } from '@/components/common/NotificationBell';
import { useManagedEenheden } from '@/hooks/useOrganisatie';
import { useInitiatief } from '@/hooks/useInitiatieven';
import { formatOrganisatieType, formatFunctie, type Person } from '@/types';
import { useUIStore } from '@/store/ui';

const pageTitles: Record<string, string> = {
  '/': 'Inbox',
  '/corpus': 'Corpus',
  '/tasks': 'Taken',
  '/people': 'Personen',
  '/organisatie': 'Organisatie',
  '/parlementair': 'Kamerstukken',
  '/debatten': 'Debatten',
  '/opdrachten': 'Opdrachten & Subsidies',
  '/admin': 'Beheer',
  '/instellingen': 'Instellingen',
  '/auditlog': 'Auditlog',
  '/search': 'Zoeken',
  '/docs': 'Handleiding',
  '/initiatieven': 'Initiatieven',
  '/samenwerkingsverbanden': 'Samenwerkingsverbanden',
  '/share-target': 'Nieuwe lead',
  // A node detail page lives under Corpus. Without an entry the bar fell back
  // to "Bouwmeester", which named the app rather than the page and left the
  // route's only real title to an h2 in the body.
  '/nodes': 'Corpus',
};

/**
 * Breakpoint helpers.
 *
 * nldd-container has no responsive visibility: `hide-above` / `hide-below` are
 * attributes of the CELL components, and on a container they are silently
 * ignored, which is how three of these ended up doing nothing. A matchMedia
 * hook is honest about being app-level logic rather than pretending the
 * container supports it.
 */
function useWiderThan(px: number): boolean {
  const [matches, setMatches] = useState(() => window.matchMedia(`(min-width: ${px}px)`).matches);
  useEffect(() => {
    const mq = window.matchMedia(`(min-width: ${px}px)`);
    const onChange = () => setMatches(mq.matches);
    mq.addEventListener('change', onChange);
    setMatches(mq.matches);
    return () => mq.removeEventListener('change', onChange);
  }, [px]);
  return matches;
}

function ShowAbove({ width, slot, children }: { width: number; slot?: string; children: ReactNode }) {
  if (!useWiderThan(width)) return null;
  return slot ? <span slot={slot}>{children}</span> : <>{children}</>;
}

function ShowBelow({ width, slot, children }: { width: number; slot?: string; children: ReactNode }) {
  if (useWiderThan(width)) return null;
  return slot ? <span slot={slot}>{children}</span> : <>{children}</>;
}

/** The vocabulary choice, as one control rather than a row of buttons. */
function VocabularySwitch({
  value,
  onChange,
}: {
  value: VocabularyId;
  onChange: (id: VocabularyId) => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddValue(ref, value);
  useNlddEvent(ref, 'change', (e) => onChange(eventValue(e) as VocabularyId));
  return (
    <nldd-segmented-control
      ref={ref}
      type="radio"
      size="sm"
      value={value}
      accessible-label="Woordenlijst"
      className="keep-label-width"
    >
      {(Object.keys(VOCABULARY_LABELS) as VocabularyId[]).map((id) => (
        <nldd-segmented-control-item key={id} value={id} text={VOCABULARY_LABELS[id]} />
      ))}
    </nldd-segmented-control>
  );
}

/**
 * Local-development person switcher, shown only when OIDC is not configured.
 *
 * A list you filter by typing, which the design system models directly; no
 * text input, filter and document mousedown listener of our own.
 */
function DevPersonPicker({
  people,
  currentPerson,
  onPick,
}: {
  people: Person[];
  currentPerson: Person | null | undefined;
  onPick: (id: string | null) => void;
}) {
  // nldd-dropdown, not nldd-combo-box. The combo-box is "a text input with
  // autocomplete": it shows the chosen value as editable, spell-checked text
  // with a clear button beside it. Picking one of a fixed list of people is a
  // select, and the dropdown wraps a native one, so the browser keeps the
  // keyboard handling and the accessibility.
  //
  // The listener sits on the DROPDOWN, not on the slotted <select>. React's
  // onChange does not fire there: its synthetic event system never reaches a
  // native control slotted into a custom element. The dropdown re-emits the
  // change itself, with the value in `detail`.
  const ref = useRef<HTMLElement>(null);
  // The dropdown also emits `change` when its options are rebuilt (the
  // people list loading), and picking now reloads the app as that person.
  // Only a change that follows the user's own click or key counts.
  const userIsPicking = useRef(false);
  useNlddEvent(ref, 'pointerdown', () => {
    userIsPicking.current = true;
  });
  useNlddEvent(ref, 'keydown', () => {
    userIsPicking.current = true;
  });
  useNlddEvent(ref, 'change', (event) => {
    if (!userIsPicking.current) return;
    userIsPicking.current = false;
    const value =
      (event as CustomEvent<{ value?: string }>).detail?.value ??
      (event.target as HTMLSelectElement | null)?.value;
    if (value !== undefined && value !== (currentPerson?.id ?? '')) onPick(value || null);
  });

  // The selected person is mirrored onto the <select> rather than passed as
  // `defaultValue`. `people` arrives from a query, so on the first render the
  // list is empty and a default freezes on "" — after a reload the header read
  // "Kies persoon" while the app was signed in as someone. Assigning `value`
  // once the matching <option> exists is what makes it stick.
  const selectRef = useRef<HTMLSelectElement>(null);
  const currentPersonId = currentPerson?.id ?? '';
  useEffect(() => {
    const select = selectRef.current;
    if (select && select.value !== currentPersonId) {
      select.value = currentPersonId;
    }
  }, [currentPersonId, people]);

  return (
    <nldd-dropdown
      ref={ref}
      accessible-label="Persoon kiezen (ontwikkelmodus)"
      width="200px"
    >
      <select ref={selectRef}>
        <option value="">Geen persoon (alles toegestaan)</option>
        {people.map((person) => (
          <option key={person.id} value={person.id}>
            {person.naam}
            {person.functie ? ` — ${formatFunctie(person.functie)}` : ''}
          </option>
        ))}
      </select>
    </nldd-dropdown>
  );
}

export function Header() {
  const location = useLocation();
  const navigate = useNavigate();
  const { currentPerson, setDevPersonId, people } = useCurrentPerson();
  const { vocabularyId, setVocabularyId } = useVocabulary();
  const { oidcConfigured } = useAuth();
  const toggleMobileSidebar = useUIStore((s) => s.toggleMobileSidebar);

  const { data: managedEenheden } = useManagedEenheden(currentPerson?.id);

  const pathBase = '/' + (location.pathname.split('/')[1] || '');
  const eenheidTitle = (() => {
    const first = managedEenheden?.[0];
    if (first) {
      const label = formatOrganisatieType(first.type);
      return `${label} Overzicht`;
    }
    return 'Eenheid Overzicht';
  })();
  // Op een initiatiefpagina: "Initiatieven › <naam>" als één titel, met de
  // publieke link er direct achter (LinkNaTitel). Zo staan ze op één hoogte
  // en hoeft de pagina zelf geen eigen kop met naam meer te tonen.
  const initiatiefId = location.pathname.match(/^\/initiatieven\/([0-9a-f-]{36})/)?.[1];
  const { data: initiatief } = useInitiatief(initiatiefId);
  const title = pathBase === '/eenheid-overzicht'
    ? eenheidTitle
    : initiatiefId && initiatief
      ? `${pageTitles[pathBase]} › ${initiatief.naam}`
      : pageTitles[pathBase] || 'Bouwmeester';

  // Detail pages get a back affordance to the list they belong to.
  const backTarget = /^\/nodes\/.+/.test(location.pathname)
    ? { text: 'Corpus', href: '/corpus' }
    : /^\/initiatieven\/.+/.test(location.pathname)
      ? { text: 'Initiatieven', href: '/initiatieven' }
      : null;

  // `back-href` would trigger a full page load, so the bar fires `back` instead
  // and the router handles it. Bound here only: the event bubbles, and binding
  // it on an ancestor as well would run the handler twice for one press.
  const barRef = useRef<HTMLElement>(null);
  const backHref = backTarget?.href;
  const handleBack = useCallback(() => {
    if (backHref) navigate(backHref);
  }, [navigate, backHref]);
  useNlddEvent(barRef, 'back', backTarget ? handleBack : undefined);

  const publiekPad = initiatiefId && initiatief?.public_page_enabled && initiatief.slug ? `/c/${initiatief.slug}` : null;

  return (
    // The bar renders the h1 itself and, on a detail page, the back
    // affordance. The wrapper only anchors the link behind the title.
    <div style={{ position: 'relative' }}>
      <nldd-top-title-bar
        ref={barRef}
        text={title}
        {...(backTarget ? { 'back-text': backTarget.text } : {})}
      >
        <>
          {/* Only shown while the sidebar is a sheet; above lg the pane is visible. */}
          <ShowBelow width={1024} slot="toolbar">
            <NlddIconButton
              icon="menu"
              accessibleLabel="Navigatie openen"
              onClick={toggleMobileSidebar}
            />
          </ShowBelow>
          {/* Vocabulary toggle. A segmented control rather than a row of buttons:
              it is one choice out of a set, so the items are radios and the
              arrow keys move between them. */}
          <ShowAbove width={640} slot="toolbar">
            <VocabularySwitch value={vocabularyId} onChange={setVocabularyId} />
          </ShowAbove>

          {/* Notification bell */}
          <span slot="toolbar"><NotificationBell /></span>

          {/* Search. An icon button like the other toolbar actions: a labelled
              button here competed with the page title and the profile picker for
              the same row, and the magnifier is the one icon nobody has to
              learn. The shortcut stays in the accessible name. */}
          <span slot="toolbar">
            <NlddIconButton
              icon="magnifier"
              accessibleLabel="Zoeken (sneltoets /)"
              onClick={() => {
                // On the search page itself, focus the field that is already
                // there rather than stacking a modal on top of it: two search
                // boxes on one screen, each with its own results. The `/`
                // shortcut in AppLayout makes the same distinction.
                if (location.pathname === '/search') {
                  document.querySelector<HTMLElement & { focus?: () => void }>(
                    'nldd-search-field',
                  )?.focus?.();
                  return;
                }
                useUIStore.getState().setSearchModalOpen(true);
              }}
            />
          </span>

          {/* Dev-mode person picker (only when OIDC is not configured) */}
          {!oidcConfigured ? (
            <span slot="toolbar">
              <DevPersonPicker
                people={people}
                currentPerson={currentPerson}
                onPick={setDevPersonId}
              />
            </span>
          ) : (
            // The name only appears where the toolbar has room for it. It sat at
            // `sm` and up, which is not the same thing: on a wide window the
            // toolbar can still be full of controls, and the name then slid in
            // behind them. Below 1280 the avatar carries the identity on its own.
            <div className="hug hug-gap-8" slot="toolbar">
              <nldd-avatar
                size="24"
                {...(currentPerson ? { name: currentPerson.naam } : { icon: 'person' })}
                decorative
              />
              {currentPerson && (
                <ShowAbove width={1280}>
                  <nldd-text size="sm" className="truncate">
                    {currentPerson.naam}
                  </nldd-text>
                </ShowAbove>
              )}
            </div>
          )}
        </>
      </nldd-top-title-bar>
      {publiekPad && <LinkNaTitel barRef={barRef} title={title} href={publiekPad} />}
    </div>
  );
}

/** Ruimte tussen de titel en de link, en tussen de link en de toolbar. */
const LINK_RUIMTE = 12;

/**
 * De publieke link van een initiatief, direct achter de titel in de kop.
 *
 * nldd-top-title-bar heeft naast de titel geen slot, alleen de toolbar
 * rechts. Daarom ligt de link over de balk: hij meet waar de titeltekst
 * eindigt en waar de toolbar begint, en staat er alleen als hij daartussen
 * past. Op een smal scherm of bij een lange naam blijft hij weg, in plaats
 * van over de toolbar of een afgekapte titel te vallen.
 */
function LinkNaTitel({ barRef, title, href }: { barRef: RefObject<HTMLElement | null>; title: string; href: string }) {
  const linkRef = useRef<HTMLElement>(null);
  const [plek, setPlek] = useState<{ left: number; top: number } | null>(null);

  useLayoutEffect(() => {
    const bar = barRef.current as (HTMLElement & { updateComplete?: Promise<unknown> }) | null;
    const link = linkRef.current;
    const wrap = bar?.parentElement;
    if (!bar || !link || !wrap) return;
    let weg = false;

    const meet = () => {
      if (weg) return;
      const h1 = bar.shadowRoot?.querySelector('.top-title-bar__title');
      const eind = bar.shadowRoot?.querySelector<HTMLElement>('.top-title-bar__end');
      if (!h1) return setPlek(null);
      // De tekst zelf, niet de h1: die rekt op tot de toolbar.
      const bereik = document.createRange();
      bereik.selectNodeContents(h1);
      const tekst = bereik.getBoundingClientRect();
      const kop = h1.getBoundingClientRect();
      const basis = wrap.getBoundingClientRect();
      const grens = eind && !eind.hidden ? eind.getBoundingClientRect().left : kop.right;
      const links = tekst.right + LINK_RUIMTE;
      const past = tekst.width > 0 && tekst.right <= kop.right + 1 && links + link.getBoundingClientRect().width + LINK_RUIMTE <= grens;
      setPlek(past ? { left: links - basis.left, top: kop.top + kop.height / 2 - basis.top } : null);
    };

    const ro = new ResizeObserver(meet);
    ro.observe(bar);
    ro.observe(link);
    // De balk tekent zijn titel pas na een update; de toolbar kan daarna nog
    // van breedte veranderen (knoppen die per schermbreedte verschijnen).
    void customElements.whenDefined('nldd-top-title-bar').then(() => bar.updateComplete).then(() => {
      if (weg) return;
      const eind = bar.shadowRoot?.querySelector('.top-title-bar__end');
      if (eind) ro.observe(eind);
      meet();
    });
    void document.fonts?.ready.then(meet);
    return () => {
      weg = true;
      ro.disconnect();
    };
  }, [barRef, title, href]);

  return (
    <nldd-link
      ref={linkRef}
      href={href}
      target="_blank"
      size="xs"
      start-icon="globe"
      text={href}
      aria-hidden={plek ? undefined : 'true'}
      style={{
        position: 'absolute',
        left: plek ? `${plek.left}px` : 0,
        top: plek ? `${plek.top}px` : 0,
        transform: 'translateY(-50%)',
        visibility: plek ? 'visible' : 'hidden',
        whiteSpace: 'nowrap',
      }}
    />
  );
}
