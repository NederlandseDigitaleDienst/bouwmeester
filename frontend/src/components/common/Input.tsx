import { forwardRef, useCallback, useRef, type ChangeEvent, type InputHTMLAttributes } from 'react';
import { eventValue, useNlddEvent } from '@/components/nldd/events';

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  error?: string;
  helperText?: string;
}

/** Id linking the input's `unmet` to the validation item that explains it. */
const ERROR_ID = 'input-error';

/** The types nldd-text-field itself accepts; everything else needs its own element. */
const TEXT_TYPES = new Set(['text', 'email', 'tel', 'url']);

/**
 * `nldd-form-field` plus the input element that matches the requested type.
 *
 * The design system splits by type where the browser does: `nldd-text-field`
 * covers text/email/tel/url, `nldd-number-field` a number with its steppers, and
 * `nldd-date-field` a date. Routing on `type` here means a call site names the
 * type once and gets the right keyboard and controls with it.
 *
 * `onChange` is bridged by hand and NOT spread onto the element. These are
 * custom elements, so React's synthetic onChange never fires for them and the
 * value arrives in `event.detail` rather than on `event.target.value`. Spread
 * the handler onto the element instead and the field silently ignores every
 * keystroke.
 *
 * The field associates its own label, so do not derive an id from the label
 * text: two fields with the same label would collide. It also marks what is
 * OPTIONAL rather than starring what is required, per the design system's
 * convention.
 */
export const Input = forwardRef<HTMLElement, InputProps>(
  (
    {
      label,
      error,
      helperText,
      className,
      id,
      type = 'text',
      required,
      disabled,
      onChange,
      placeholder,
      name,
      value,
      autoComplete,
      readOnly,
      ...rest
    },
    ref,
  ) => {
    const innerRef = useRef<HTMLElement>(null);

    // Hand the caller something shaped like the change event it expects, so the
    // existing `e.target.value` call sites keep working untouched.
    const relay = useCallback(
      (event: Event) => {
        if (!onChange) return;
        const next = eventValue(event);
        const target = { value: next, name: name ?? '' } as EventTarget & HTMLInputElement;
        onChange({
          ...(event as unknown as ChangeEvent<HTMLInputElement>),
          target,
          currentTarget: target,
        });
      },
      [onChange, name],
    );

    // `input` fires per keystroke, which is what a controlled React field wants.
    useNlddEvent(innerRef, 'input', onChange ? relay : undefined);

    const setRefs = useCallback(
      (el: HTMLElement | null) => {
        innerRef.current = el;
        if (typeof ref === 'function') ref(el);
        else if (ref) (ref as React.MutableRefObject<HTMLElement | null>).current = el;
      },
      [ref],
    );

    // Shared across all three elements. `value` is deliberately left out: the
    // number field takes a number where the others take a string.
    const shared = {
      ref: setRefs,
      className,
      ...(id ? { 'input-id': id } : {}),
      ...(required ? { required: true as const } : {}),
      ...(disabled ? { disabled: true as const } : {}),
      ...(readOnly ? { readonly: true as const } : {}),
      ...(error ? { invalid: true as const, unmet: ERROR_ID } : {}),
      // Zonder zichtbaar label: aria-label als die er is, anders de placeholder.
      ...(label ? {} : { 'accessible-label': rest['aria-label'] ?? placeholder ?? '' }),
      // Enter in een snelinvoer (nieuwe taak, nieuwe subtaak). De toets komt
      // uit de shadow-DOM en bubbelt naar het element; zonder doorgeven viel
      // hij weg en werkte alleen de plusknop ernaast.
      ...(rest.onKeyDown ? { onKeyDown: rest.onKeyDown as unknown as React.KeyboardEventHandler<HTMLElement> } : {}),
      // Verlaten van het veld, voor opslaan bij verlaten (bijvoorbeeld een
      // naam in een lijst). React vangt het via focusout, dat wel bubbelt.
      ...(rest.onBlur ? { onBlur: rest.onBlur as unknown as React.FocusEventHandler<HTMLElement> } : {}),
      ...(placeholder ? { placeholder } : {}),
      ...(name ? { name } : {}),
      ...(autoComplete ? { autocomplete: autoComplete } : {}),
      ...(rest.maxLength !== undefined ? { maxlength: rest.maxLength } : {}),
      ...(rest.minLength !== undefined ? { minlength: rest.minLength } : {}),
    };

    const stringValue = value !== undefined ? String(value) : undefined;

    let field;
    if (type === 'number') {
      const numeric =
        stringValue === undefined || stringValue === '' ? undefined : Number(stringValue);
      field = (
        <nldd-number-field
          {...shared}
          {...(numeric !== undefined && !Number.isNaN(numeric) ? { value: numeric } : {})}
        />
      );
    } else if (type === 'date') {
      field = <nldd-date-field {...shared} {...(stringValue ? { value: stringValue } : {})} />;
    } else {
      // Only the four types the element supports reach its `type`; anything else
      // (password, search, ...) falls back to a plain text field rather than
      // landing an attribute the element does not understand.
      const textType =
        TEXT_TYPES.has(type) && type !== 'text' ? (type as 'email' | 'tel' | 'url') : undefined;
      field = (
        <nldd-text-field
          {...shared}
          {...(stringValue !== undefined ? { value: stringValue } : {})}
          {...(textType ? { type: textType } : {})}
        />
      );
    }

    if (!label) return field;

    return (
      <nldd-form-field label={label} {...(required ? {} : { optional: true })}>
        {field}
        {error ? (
          <nldd-validation-list>
            <nldd-validation-item id={ERROR_ID}>{error}</nldd-validation-item>
          </nldd-validation-list>
        ) : (
          helperText && <nldd-form-field-help-text>{helperText}</nldd-form-field-help-text>
        )}
      </nldd-form-field>
    );
  },
);

Input.displayName = 'Input';
