import {
  forwardRef,
  useCallback,
  useImperativeHandle,
  useRef,
  type ChangeEvent,
  type SelectHTMLAttributes,
} from 'react';
import { eventValue, useNlddEvent, useNlddValue } from '@/components/nldd/events';

interface SelectOption {
  value: string;
  label: string;
}

interface SelectProps extends Omit<SelectHTMLAttributes<HTMLSelectElement>, 'size'> {
  label?: string;
  error?: string;
  options: SelectOption[];
  placeholder?: string;
  /** nldd-dropdown size. Replaces the native `size` (visible rows), which a
   *  dropdown never wants. */
  size?: 'xs' | 'sm' | 'md';
  /** Fixed width as a CSS length; without it the dropdown fills its container. */
  width?: string;
}

/** Id linking the field's `unmet` to the validation item that explains it. */
const ERROR_ID = 'select-error';

/**
 * A select, as an `nldd-dropdown`.
 *
 * The dropdown is a visual shell around a real `<select>`, which stays slotted
 * as a child. That is deliberate on the design system's part: the browser keeps
 * ownership of the keyboard, the form value and the native picker on mobile, so
 * a ref and the `<select>` props behave normally.
 *
 * `onChange` is the exception, and it has to be relayed. The dropdown listens
 * on the slotted select and calls `stopPropagation()` on the native `change`
 * before re-dispatching its own `CustomEvent` from the host. React 19
 * delegates from the root container, so the stopped native event never
 * reaches the delegate, and the replacement is a CustomEvent React does not
 * map to `onChange`. Without the relay the handler never runs at all and
 * picking a value does nothing. `Input.tsx` relays the same way for text
 * fields.
 */
export const Select = forwardRef<HTMLSelectElement, SelectProps>(
  (
    {
      label,
      error,
      options,
      placeholder,
      className,
      id,
      required,
      disabled,
      onChange,
      name,
      value,
      size,
      width,
      ...props
    },
    ref,
  ) => {
    const dropdownRef = useRef<HTMLElement>(null);

    // `value` goes onto the DOM property instead of staying a JSX prop. As a
    // prop it makes the select a controlled field, and React then warns that
    // it has no `onChange`. That is true and deliberate: the handler sits on
    // the nldd-dropdown, because the element stops the native change event and
    // re-dispatches its own. Writing the property keeps the select in step
    // without claiming React owns it.
    const selectRef = useRef<HTMLSelectElement>(null);
    useImperativeHandle(ref, () => selectRef.current as HTMLSelectElement, []);
    useNlddValue(selectRef, typeof value === 'string' ? value : undefined);

    // Hand the caller something shaped like the change event it expects, so
    // the existing `e.target.value` call sites keep working untouched.
    const relay = useCallback(
      (event: Event) => {
        if (!onChange) return;
        const next = eventValue(event);
        const target = { value: next, name: name ?? '' } as EventTarget & HTMLSelectElement;
        onChange({
          ...(event as unknown as ChangeEvent<HTMLSelectElement>),
          target,
          currentTarget: target,
        });
      },
      [onChange, name],
    );

    useNlddEvent(dropdownRef, 'change', onChange ? relay : undefined);

    const dropdown = (
      <nldd-dropdown
        ref={dropdownRef}
        className={className}
        {...(size ? { size } : {})}
        {...(width ? { width } : {})}
        {...(disabled ? { disabled: true } : {})}
        {...(error ? { invalid: true, unmet: ERROR_ID } : {})}
      >
        <select
          ref={selectRef}
          id={id}
          name={name}
          required={required}
          disabled={disabled}
          {...props}
        >
          {placeholder && (
            <option value="" disabled>
              {placeholder}
            </option>
          )}
          {options.map((option) => (
            <option key={option.value} value={option.value}>
              {option.label}
            </option>
          ))}
        </select>
      </nldd-dropdown>
    );

    if (!label) return dropdown;

    return (
      <nldd-form-field label={label} {...(required ? {} : { optional: true })}>
        {dropdown}
        {error && (
          <nldd-validation-list>
            <nldd-validation-item id={ERROR_ID}>{error}</nldd-validation-item>
          </nldd-validation-list>
        )}
      </nldd-form-field>
    );
  },
);

Select.displayName = 'Select';
