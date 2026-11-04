/**
 * Registers the nldd-* custom elements this app uses.
 *
 * Deliberately NOT `import '@nldd/design-system'`: that barrel is 1.9 MB and
 * pulls in CodeMirror (nldd-code-editor, nldd-text-editor), which pushed the
 * main chunk past the service worker's precache limit. The package ships a
 * subpath export per component, so we register only what we render.
 *
 * Adding a component? Add its import here, alphabetically within its group,
 * and rerun `node scripts/generate-nldd-types.mjs` so `nldd-elements.d.ts` drops
 * its NOT REGISTERED note. A tag used without an import renders its children
 * unstyled with no error; register.test.ts and validate-nldd-markup.mjs catch it.
 *
 * Only what the app renders directly is imported. Elements that a parent pulls
 * in (nldd-tooltip via nldd-icon-button, nldd-radio-button via
 * nldd-radio-button-field, nldd-button-bar via nldd-collection) are left out.
 */

// Layout
import '@nldd/design-system/shell';
import '@nldd/design-system/box';
import '@nldd/design-system/card';
import '@nldd/design-system/collection';
import '@nldd/design-system/container';
import '@nldd/design-system/divider';
import '@nldd/design-system/full-bleed-section';
import '@nldd/design-system/navigation-split-view';
import '@nldd/design-system/page';
import '@nldd/design-system/page-footer';
import '@nldd/design-system/popover';
import '@nldd/design-system/sheet';
import '@nldd/design-system/simple-section';
import '@nldd/design-system/spacer';
import '@nldd/design-system/split-view-pane';
import '@nldd/design-system/window';

// Actions
import '@nldd/design-system/button';
import '@nldd/design-system/button-group';
import '@nldd/design-system/icon-button';
import '@nldd/design-system/menu';
import '@nldd/design-system/toolbar';

// Content
import '@nldd/design-system/avatar';
import '@nldd/design-system/icon';
import '@nldd/design-system/identity';
import '@nldd/design-system/image';
import '@nldd/design-system/rich-text';
import '@nldd/design-system/tag';
import '@nldd/design-system/text';
import '@nldd/design-system/title';

// Forms
import '@nldd/design-system/form';
import '@nldd/design-system/form-actions';
import '@nldd/design-system/form-field';
import '@nldd/design-system/form-section';
import '@nldd/design-system/validation-list';

// Inputs
import '@nldd/design-system/checkbox';
import '@nldd/design-system/checkbox-field';
import '@nldd/design-system/combo-box';
import '@nldd/design-system/date-field';
import '@nldd/design-system/dropdown';
import '@nldd/design-system/file-field';
import '@nldd/design-system/multi-line-text-field';
import '@nldd/design-system/number-field';
import '@nldd/design-system/password-field';
import '@nldd/design-system/radio-button-field';
import '@nldd/design-system/radio-button-group';
import '@nldd/design-system/search-field';
import '@nldd/design-system/segmented-control';
import '@nldd/design-system/switch';
import '@nldd/design-system/switch-field';
// Brings CodeMirror with it: measured at +624 kB on the main chunk, which the
// 5 MB precache limit has room for, and it replaces TipTap (6.7 MB of source)
// rather than sitting next to it. See the note at the top about the barrel.
import '@nldd/design-system/text-editor';
import '@nldd/design-system/text-field';
import '@nldd/design-system/toggle-button';
import '@nldd/design-system/toggle-button-group';
import '@nldd/design-system/token-field';

// Navigation
import '@nldd/design-system/breadcrumbs';
import '@nldd/design-system/link';
import '@nldd/design-system/menu-bar';
import '@nldd/design-system/menu-bar-item';
import '@nldd/design-system/pagination';
import '@nldd/design-system/skip-link';
import '@nldd/design-system/tab-bar';
import '@nldd/design-system/top-title-bar';

// Status and feedback
import '@nldd/design-system/activity-indicator';
import '@nldd/design-system/badge';
import '@nldd/design-system/banner';
import '@nldd/design-system/inline-dialog';
import '@nldd/design-system/modal-dialog';
import '@nldd/design-system/notification';
import '@nldd/design-system/progress-bar';

// Lists and tables
import '@nldd/design-system/cell';
import '@nldd/design-system/description-cell';
import '@nldd/design-system/icon-cell';
import '@nldd/design-system/list';
import '@nldd/design-system/list-item';
import '@nldd/design-system/list-item-segment';
import '@nldd/design-system/spacer-cell';
import '@nldd/design-system/table';
import '@nldd/design-system/text-cell';
import '@nldd/design-system/step-cell';
import '@nldd/design-system/title-cell';
