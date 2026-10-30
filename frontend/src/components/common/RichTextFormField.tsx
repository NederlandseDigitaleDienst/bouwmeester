import { RichTextEditor } from '@/components/common/RichTextEditor';

interface RichTextFormFieldProps {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
  /** Marks the field as required; without it the label shows "Optioneel". */
  required?: boolean;
  /**
   * Geen "Optioneel" naast het label, ook al is het veld niet verplicht. Voor
   * een venster waar de andere velden (keuzelijsten met een vaste waarde) het
   * ook niet tonen; één badge tussen velden zonder valt op als fout.
   */
  hideOptional?: boolean;
  /** Enter verstuurt (zie RichTextEditor); Shift+Enter is een nieuwe regel. */
  onEnter?: () => void;
}

const DEFAULT_PLACEHOLDER =
  'Optionele beschrijving... Gebruik @ voor personen, # voor nodes/taken, **vet** voor opmaak';

/**
 * A description field.
 *
 * `nldd-form-field` owns the label, so this draws none of its own: the field
 * associates the two without a for/id pair, and it also sets the editor's
 * accessible name. A hand-written `<label>` beside the editor would break both,
 * and leave this field framed differently from a text field on the same form.
 *
 * The design guidelines mark the optional fields rather than the required ones,
 * which the field does itself through `optional`.
 */
export function RichTextFormField({
  label,
  value,
  onChange,
  rows = 3,
  placeholder = DEFAULT_PLACEHOLDER,
  required,
  hideOptional = false,
  onEnter,
}: RichTextFormFieldProps) {
  return (
    <nldd-form-field label={label} {...(required || hideOptional ? {} : { optional: true })}>
      <RichTextEditor value={value} onChange={onChange} placeholder={placeholder} rows={rows} onEnter={onEnter} />
    </nldd-form-field>
  );
}
