import { describe, it, expect } from 'vitest';

/**
 * Every nldd-* element the app renders must be imported in register.ts.
 *
 * A component that is used but never imported does NOT error. The browser keeps
 * it as an unknown element and renders its children unstyled, so the page looks
 * subtly wrong with nothing in the console, nothing in tsc and nothing in
 * eslint. On a real page it shows up as a block of unstyled markup, which is
 * what this test catches instead.
 *
 * Some elements register through their parent's module: nldd-table-row ships
 * with nldd-table, nldd-menu-item with nldd-menu. Those are listed below rather
 * than imported separately, because importing them is not wrong, just noise.
 */

/**
 * Elements that a parent module registers, verified in a browser.
 *
 * Read the parent's TEMPLATE, not just its component file, before adding a row
 * here. token-field.js imports menu.js and nothing else, which makes it look
 * like nldd-token is unregistered; the import sits in token-field.template.js,
 * which pulls in content/token/token.js and that is where
 * customElement('nldd-token') runs.
 *
 * A wrong row here is worse than a missing import, because it exempts the tag
 * from the one check that would have caught it.
 */
const REGISTERED_BY_PARENT: Record<string, string> = {
  'nldd-table-row': 'table',
  'nldd-menu-item': 'menu',
  'nldd-menu-divider': 'menu',
  'nldd-menu-group': 'menu',
  'nldd-tab-bar-item': 'tab-bar',
  'nldd-validation-item': 'validation-list',
  'nldd-form-field-help-text': 'form-field',
  'nldd-token': 'token-field',
  'nldd-breadcrumbs-item': 'breadcrumbs',
  'nldd-menu-bar-item': 'menu-bar',
  'nldd-segmented-control-item': 'segmented-control',
  'nldd-button-bar-divider': 'button-bar',
  'nldd-toolbar-item': 'toolbar',
  'nldd-toolbar-title': 'toolbar',
  'nldd-split-view-divider': 'split-view-pane',
  'nldd-page-footer-legal-bar': 'page-footer',
  'nldd-page-footer-legal-bar-item': 'page-footer',
  'nldd-document-tab-bar-item': 'document-tab-bar',
  'nldd-progress-bar-segment-indicator': 'progress-bar',
  'nldd-progress-circle-segment-indicator': 'progress-circle',
  'nldd-avatar-group': 'avatar',
  'nldd-tooltip': 'icon-button',
  'nldd-radio-button': 'radio-button-field',
  'nldd-button-bar': 'collection',
};

// Vite inlines these at build time, so the test needs no filesystem access and
// works the same in CI as it does locally.
const SOURCES = import.meta.glob('/src/**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;
const REGISTER_SOURCE = import.meta.glob('/src/components/nldd/register.ts', { query: '?raw', import: 'default', eager: true }) as Record<string, string>;

describe('nldd component registry', () => {
  it('imports every element the app renders', () => {
    const registerSource = Object.values(REGISTER_SOURCE)[0] ?? '';
    const registered = new Set(
      [...registerSource.matchAll(/@nldd\/design-system\/([a-z-]+)/g)].map((m) => `nldd-${m[1]}`),
    );

    const used = new Set<string>();
    const whereUsed = new Map<string, string>();
    for (const [file, source] of Object.entries(SOURCES)) {
      for (const m of source.matchAll(/<(nldd-[a-z-]+)/g)) {
        used.add(m[1]);
        if (!whereUsed.has(m[1])) whereUsed.set(m[1], file);
      }
    }

    const missing = [...used]
      .filter((tag) => !registered.has(tag) && !(tag in REGISTERED_BY_PARENT))
      .map((tag) => `${tag} (used in ${whereUsed.get(tag)})`);

    expect(
      missing,
      'Used but not imported in components/nldd/register.ts. These render ' +
        'their children unstyled with no error anywhere. Add the import, or ' +
        'add the tag to REGISTERED_BY_PARENT if a parent module registers it.',
    ).toEqual([]);
  });
});
