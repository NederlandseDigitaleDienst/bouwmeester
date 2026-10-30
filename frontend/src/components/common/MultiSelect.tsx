import { useRef } from 'react';
import { useNlddEvent, orUndef } from '@/components/nldd/events';

export interface MultiSelectOption {
  value: string;
  label: string;
}

interface MultiSelectProps {
  value: Set<string>;
  onChange: (value: Set<string>) => void;
  options: MultiSelectOption[];
  allLabel?: string;
}

/** One checkable row in the menu. */
function Option({
  text,
  selected,
  onSelect,
}: {
  text: string;
  selected: boolean;
  onSelect: () => void;
}) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'select', onSelect);
  return <nldd-menu-item ref={ref} type="checkbox" text={text} selected={orUndef(selected)} />;
}

/**
 * A filter that picks several values, as a button with a checkbox menu.
 *
 * The menu is slotted into the button, so the browser owns opening, closing on
 * Escape and light dismiss, and the button gets aria-expanded and
 * aria-haspopup. That replaces a mousedown listener on document, a keydown
 * listener for Escape and a hand-managed z-index.
 *
 * The rows are real checkbox items rather than a div with a drawn square: they
 * announce their checked state, and the whole list is reachable with the arrow
 * keys, which a list of clickable <li> elements never was.
 */
export function MultiSelect({
  value,
  onChange,
  options,
  allLabel = 'Alles',
}: MultiSelectProps) {
  const allRef = useRef<HTMLElement>(null);

  const allSelected = options.length > 0 && options.every((o) => value.has(o.value));
  const noneSelected = options.every((o) => !value.has(o.value));
  const selectedCount = options.filter((o) => value.has(o.value)).length;

  const toggleOption = (optValue: string) => {
    const next = new Set(value);
    if (next.has(optValue)) next.delete(optValue);
    else next.add(optValue);
    onChange(next);
  };

  useNlddEvent(allRef, 'select', () => {
    onChange(allSelected ? new Set() : new Set(options.map((o) => o.value)));
  });

  // Nothing selected and everything selected filter the same thing, so they
  // read the same: the filter is simply not narrowing anything.
  const displayLabel =
    allSelected || noneSelected ? allLabel : `${selectedCount} van ${options.length}`;

  return (
    <nldd-button
      text={displayLabel}
      appearance="secondary"
      width="full"
      expandable
      popup-type="menu"
    >
      <nldd-menu slot="popup">
        <nldd-menu-item ref={allRef} type="checkbox" text={allLabel} selected={orUndef(allSelected)} />
        <nldd-menu-divider />
        {options.map((opt) => (
          <Option
            key={opt.value}
            text={opt.label}
            selected={value.has(opt.value)}
            onSelect={() => toggleOption(opt.value)}
          />
        ))}
      </nldd-menu>
    </nldd-button>
  );
}
