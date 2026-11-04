import { useState, useRef, useCallback, useEffect, useMemo } from 'react';
import { Modal } from '@/components/common/Modal';
import { Input } from '@/components/common/Input';
import { NlddIconButton } from '@/components/nldd/NlddIconButton';
import { eventValue, useNlddEvent } from '@/components/nldd/events';
import { LoadingSpinner } from '@/components/common/LoadingSpinner';
import { CreatableSelect } from '@/components/common/CreatableSelect';
import { RichTextFormField } from '@/components/common/RichTextFormField';
import { useCreateLead, useParseLeadIntake, useCheckDuplicates } from '@/hooks/useLeads';
import { addTagToLead as addTagToLeadApi, uploadLeadAttachment as uploadLeadAttachmentApi, addLeadContact as addLeadContactApi } from '@/api/leads';
import { useTags } from '@/hooks/useTags';
import { isEmailFile, parseEmailFile, emailToRawText } from '@/utils/emailParser';
import type { ParsedEmail } from '@/utils/emailParser';
import { useToast } from '@/contexts/ToastContext';
import { usePeople } from '@/hooks/usePeople';
import { useCreateContactPerson } from '@/hooks/useNewContactPerson';
import { NewContactPersonFields } from '@/components/leads/NewContactPersonFields';
import {
  emptyContactPersonFields,
  type ContactPersonFieldsState,
} from '@/components/leads/contactPersonFields';
import { useInitiatieven, useCreateInitiatief } from '@/hooks/useInitiatieven';
import { useCurrentPerson } from '@/contexts/CurrentPersonContext';
import { useLeadDetail } from '@/contexts/LeadDetailContext';
import { INITIATIEF_COLORS, formatFunctie } from '@/types';
import { useLeadColumns } from '@/hooks/useLeadColumns';
import type { LeadParseResult } from '@/types';
import { buildPersonOptions } from '@/utils/personOptions';
import { leadColumnTagColor } from './stageColors';
import { NlddButton } from '@/components/nldd/NlddButton';

interface LeadIntakeDialogProps {
  open: boolean;
  onClose: () => void;
  defaultInitiatiefId?: string;
  sharedParseResult?: LeadParseResult;
  sharedFiles?: File[];
  initialFiles?: File[];
}

type Step = 'input' | 'parsing' | 'confirm';

const MAX_FILE_SIZE = 20 * 1024 * 1024; // 20 MB, matches backend limit

interface ContactEntry {
  personId: string;
  /** Velden voor wanneer er een nieuwe persoon wordt aangemaakt (personId leeg). */
  fields: ContactPersonFieldsState;
  rol: string;
}

const emptyContact = (): ContactEntry => ({
  personId: '',
  fields: emptyContactPersonFields(),
  rol: 'contactpersoon',
});

export function LeadIntakeDialog({ open, onClose, defaultInitiatiefId, sharedParseResult, sharedFiles, initialFiles }: LeadIntakeDialogProps) {
  const [step, setStep] = useState<Step>('input');
  const [rawText, setRawText] = useState('');
  const [files, setFiles] = useState<File[]>([]);
  const [dragActive, setDragActive] = useState(false);
  const [initiatiefId, setInitiatiefId] = useState('');
  const [parseResult, setParseResult] = useState<LeadParseResult | null>(null);
  const [parsedEmail, setParsedEmail] = useState<ParsedEmail | null>(null);
  const [emailParsing, setEmailParsing] = useState(false);
  const emailParsingRef = useRef(false);

  // Editable fields after parse
  const [title, setTitle] = useState('');
  const [organization, setOrganization] = useState('');
  const [description, setDescription] = useState('');
  const [selectedTags, setSelectedTags] = useState<string[]>([]);
  const [stage, setStage] = useState<string>('inbox');
  const [contacts, setContacts] = useState<ContactEntry[]>([emptyContact()]);
  const updateContact = useCallback((index: number, updates: Partial<ContactEntry>) => {
    setContacts(prev => prev.map((c, i) => i === index ? { ...c, ...updates } : c));
  }, []);
  // Gedeelde lijst zodat een nieuw-toegevoegde expertise zichtbaar is in
  // alle openstaande contact-rijen voordat de server-cache ververst.
  const [extraExpertiseValues, setExtraExpertiseValues] = useState<string[]>([]);
  const addExtraExpertise = useCallback((value: string) => {
    setExtraExpertiseValues((prev) => (prev.includes(value) ? prev : [...prev, value]));
  }, []);
  const [assigneeId, setAssigneeId] = useState<string>('');
  const [broughtById, setBroughtById] = useState<string>('');
  const [leadDate, setLeadDate] = useState(() => new Date().toISOString().split('T')[0]);
  const { columns: stageColumns } = useLeadColumns(initiatiefId || undefined);
  const sortedStageColumns = useMemo(
    () => [...stageColumns].sort((a, b) => a.sort_order - b.sort_order),
    [stageColumns],
  );
  const stageColumnsBySlug = useMemo(() => {
    const map = new Map<string, (typeof sortedStageColumns)[number]>();
    for (const c of sortedStageColumns) map.set(c.slug, c);
    return map;
  }, [sortedStageColumns]);
  // Wanneer het initiatief verandert kan de geselecteerde stage niet langer
  // bestaan in de kolommen van dat initiatief. Val terug op de eerste kolom.
  useEffect(() => {
    if (sortedStageColumns.length === 0) return;
    if (!stageColumnsBySlug.has(stage)) {
      setStage(sortedStageColumns[0].slug);
    }
  }, [sortedStageColumns, stageColumnsBySlug, stage]);

  const fileInputRef = useRef<HTMLInputElement>(null);
  const rawTextFieldRef = useRef<HTMLElement>(null);
  useNlddEvent(rawTextFieldRef, 'input', useCallback((e: Event) => setRawText(eventValue(e)), []));
  const createLead = useCreateLead();
  const parseLead = useParseLeadIntake();
  const { showError } = useToast();
  const { currentPerson } = useCurrentPerson();
  const { data: initiatieven } = useInitiatieven();
  const createInitiatiefMutation = useCreateInitiatief();
  const createContact = useCreateContactPerson();
  const { data: people } = usePeople();
  const { data: allTags } = useTags();
  // Deduplicated: the menu keys its items by name, the value the API takes.
  const tagNames = useMemo(() => [...new Set((allTags ?? []).map((t) => t.name))], [allTags]);
  const { openLeadDetail } = useLeadDetail();
  const { data: duplicates } = useCheckDuplicates(title, organization || undefined);

  // Assignee options: current person first (with "(mij)")
  const assigneeOptions = useMemo(
    () => buildPersonOptions(people ?? [], currentPerson, (p) => ({
      value: p.id,
      label: p.naam,
      description: formatFunctie(p.functie),
    })),
    [people, currentPerson],
  );

  // Contact options: plain alphabetical, no "mij" at top
  const contactOptions = useMemo(
    () => (people ?? [])
      .filter((p) => p.is_active)
      .sort((a, b) => a.naam.localeCompare(b.naam))
      .map((p) => ({
        value: p.id,
        label: p.naam,
        description: formatFunctie(p.functie),
      })),
    [people],
  );

  // Auto-select initiative: prefer defaultInitiatiefId, then single-option auto-select
  useEffect(() => {
    if (initiatiefId) return;
    if (defaultInitiatiefId) {
      setInitiatiefId(defaultInitiatiefId);
    } else if (initiatieven?.length === 1) {
      setInitiatiefId(initiatieven[0].id);
    }
  }, [initiatieven, initiatiefId, defaultInitiatiefId]);

  // Default broughtById and leadDate when dialog opens
  useEffect(() => {
    if (open) {
      if (!broughtById && currentPerson) {
        setBroughtById(currentPerson.id);
      }
      if (!leadDate) {
        setLeadDate(new Date().toISOString().split('T')[0]);
      }
    }
  }, [open, broughtById, currentPerson, leadDate]);

  // Apply a parse result to the form fields
  const applyParseResult = useCallback((result: LeadParseResult) => {
    setParseResult(result);
    setTitle(result.title ?? '');
    setOrganization(result.organization ?? '');
    setDescription(result.description ?? '');
    setSelectedTags(result.suggested_tags ?? []);
    setContacts([{
      personId: '',
      fields: {
        ...emptyContactPersonFields(),
        naam: result.contact_name ?? '',
        email: result.contact_email ?? '',
        phone: result.contact_phone ?? '',
      },
      rol: 'contactpersoon',
    }]);
    const today = new Date().toISOString().split('T')[0];
    const parsedDate = result.original_date && /^\d{4}-\d{2}-\d{2}$/.test(result.original_date)
      ? result.original_date
      : today;
    setLeadDate(parsedDate);
    if (result.addressed_to && people) {
      const addr = result.addressed_to.toLowerCase();
      if (currentPerson && currentPerson.naam.toLowerCase().includes(addr)) {
        setBroughtById(currentPerson.id);
      } else {
        const match = people.find(p => p.naam.toLowerCase().startsWith(addr));
        if (match) setBroughtById(match.id);
      }
    }
  }, [people, currentPerson]);

  // Apply shared parse result (from share target) — skip input step
  useEffect(() => {
    if (open && sharedParseResult && step === 'input') {
      applyParseResult(sharedParseResult);
      if (sharedFiles) setFiles(sharedFiles);
      setStep('confirm');
    }
  }, [open, sharedParseResult]); // eslint-disable-line react-hooks/exhaustive-deps

  // Shared helper: validate file sizes and split email vs regular files.
  // Only the first email file is parsed; additional emails are treated as regular files.
  const processEmailAndFiles = useCallback((incoming: File[], replace: boolean) => {
    if (emailParsingRef.current) return; // guard against concurrent email parses

    const emailFile = incoming.find(isEmailFile);
    const rest = incoming.filter(f => f !== emailFile);

    // Size-check all non-email files (email file itself may be large, but we parse it client-side)
    const valid: File[] = [];
    const rejected: string[] = [];
    for (const f of rest) {
      if (f.size > MAX_FILE_SIZE) rejected.push(f.name);
      else valid.push(f);
    }
    if (rejected.length > 0) {
      showError(`Bestanden te groot (max 20 MB): ${rejected.join(', ')}`);
    }

    if (emailFile) {
      emailParsingRef.current = true;
      setEmailParsing(true);
      parseEmailFile(emailFile)
        .then((email) => {
          setParsedEmail(email);
          setRawText(emailToRawText(email));
          // Size-check extracted attachments too
          const validAtts: File[] = [];
          const rejectedAtts: string[] = [];
          for (const att of email.attachments) {
            if (att.size > MAX_FILE_SIZE) rejectedAtts.push(att.name);
            else validAtts.push(att);
          }
          if (rejectedAtts.length > 0) {
            showError(`Bijlagen te groot (max 20 MB): ${rejectedAtts.join(', ')}`);
          }
          const combined = [...validAtts, ...valid];
          if (replace) setFiles(combined);
          else setFiles((prev) => [...prev, ...combined]);
          if (email.senderName || email.senderEmail) {
            setContacts(prev => {
              const updated = [...prev];
              updated[0] = {
                ...updated[0],
                fields: {
                  ...updated[0].fields,
                  naam: email.senderName || updated[0].fields.naam,
                  email: email.senderEmail || updated[0].fields.email,
                },
              };
              return updated;
            });
          }
        })
        .catch(() => {
          showError(`E-mail kon niet worden gelezen: ${emailFile.name}`);
          // Fall back to treating as regular files
          if (replace) setFiles([emailFile, ...valid]);
          else setFiles((prev) => [...prev, emailFile, ...valid]);
        })
        .finally(() => {
          emailParsingRef.current = false;
          setEmailParsing(false);
        });
    } else if (valid.length > 0) {
      if (replace) setFiles(valid);
      else setFiles((prev) => [...prev, ...valid]);
    }
  }, [showError]);

  // Pre-fill files from global drop (stay on input step so user can add text / click parse)
  const prevInitialFilesRef = useRef<File[] | undefined>(undefined);
  useEffect(() => {
    if (!open) {
      prevInitialFilesRef.current = undefined;
      return;
    }
    if (initialFiles && initialFiles.length > 0 && initialFiles !== prevInitialFilesRef.current && !sharedParseResult && step === 'input') {
      prevInitialFilesRef.current = initialFiles;
      processEmailAndFiles(initialFiles, true);
    }
  }, [open, initialFiles]); // eslint-disable-line react-hooks/exhaustive-deps

  // Try to match VLAM's contact_name against existing people
  const firstContactName = contacts[0]?.fields.naam ?? '';
  useEffect(() => {
    if (firstContactName && people) {
      const match = people.find(
        (p) =>
          p.naam.toLowerCase().includes(firstContactName.toLowerCase()) ||
          firstContactName.toLowerCase().includes(p.naam.toLowerCase()),
      );
      if (match) {
        updateContact(0, { personId: match.id });
      }
    }
  }, [firstContactName, people, updateContact]);

  const reset = useCallback(() => {
    setStep('input');
    setRawText('');
    setFiles([]);
    setParseResult(null);
    setParsedEmail(null);
    emailParsingRef.current = false;
    setEmailParsing(false);
    setTitle('');
    setOrganization('');
    setDescription('');
    setSelectedTags([]);
    setStage('inbox');
    setContacts([emptyContact()]);
    setExtraExpertiseValues([]);
    setAssigneeId('');
    setBroughtById(currentPerson?.id ?? '');
    setLeadDate(new Date().toISOString().split('T')[0]);
    setInitiatiefId('');
  }, [currentPerson]);

  const handleClose = () => {
    reset();
    onClose();
  };

  const addFiles = useCallback((newFiles: File[]) => {
    processEmailAndFiles(newFiles, false);
  }, [processEmailAndFiles]);

  const handlePaste = (e: React.ClipboardEvent) => {
    const items = e.clipboardData.items;
    const pastedFiles: File[] = [];
    for (let i = 0; i < items.length; i++) {
      if (items[i].type.startsWith('image/')) {
        const file = items[i].getAsFile();
        if (file) {
          pastedFiles.push(file);
        }
      }
    }
    if (pastedFiles.length > 0) {
      e.stopPropagation();
      addFiles(pastedFiles);
    }
  };

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    addFiles(Array.from(e.dataTransfer.files));
  };

  const removeFile = (index: number) => {
    setFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const handleParse = async () => {
    if (!rawText.trim() && files.length === 0) return;

    setStep('parsing');
    try {
      const result = await parseLead.mutateAsync({ rawText: rawText.trim() || undefined, files: files.length > 0 ? files : undefined });
      applyParseResult(result);
      setStep('confirm');
    } catch {
      // If parsing fails, go straight to confirm with empty suggestions
      setTitle('');
      setOrganization('');
      setDescription(rawText.slice(0, 200));
      setSelectedTags([]);
      setStep('confirm');
    }
  };

  const handleSkipParse = () => {
    setTitle('');
    setOrganization('');
    setDescription('');
    setSelectedTags([]);
    if (!leadDate) setLeadDate(new Date().toISOString().split('T')[0]);
    setStep('confirm');
  };

  const handleSubmit = async () => {
    if (!title.trim() || !initiatiefId) return;

    const fullDescription = description.trim() || null;

    try {
      const lead = await createLead.mutateAsync({
        title: title.trim(),
        description: fullDescription,
        organization: organization.trim() || null,
        stage,
        raw_intake_text: rawText.trim() || null,
        initiatief_id: initiatiefId,
        assignee_id: assigneeId || null,
        brought_by_id: broughtById || null,
        created_at: leadDate !== new Date().toISOString().split('T')[0]
          ? `${leadDate}T00:00:00Z`
          : null,
      });

      // Add tags via separate endpoint
      for (const tagName of selectedTags) {
        try {
          await addTagToLeadApi(lead.id, { tag_name: tagName });
        } catch {
          // Non-critical, don't block lead creation
        }
      }

      // Upload attached files
      for (const file of files) {
        try {
          await uploadLeadAttachmentApi(lead.id, file);
        } catch {
          // Non-critical, don't block lead creation
        }
      }

      // Add contact persons as LeadContacts
      for (const contact of contacts) {
        if (contact.personId) {
          try {
            await addLeadContactApi(lead.id, contact.personId, contact.rol);
          } catch {
            // Non-critical, don't block lead creation
          }
        } else if (contact.fields.naam.trim()) {
          try {
            let personId: string | null = null;
            // Try to match an existing person by email first to avoid duplicates.
            const email = contact.fields.email.trim();
            if (email && people) {
              const byEmail = people.find(
                (p) => p.email?.toLowerCase() === email.toLowerCase(),
              );
              if (byEmail) personId = byEmail.id;
            }
            if (!personId) {
              const result = await createContact.create({
                naam: contact.fields.naam,
                email: contact.fields.email,
                phone: contact.fields.phone,
                functie: contact.fields.functie,
                expertise: contact.fields.expertise,
                organisatieEenheidId:
                  contact.fields.organisatieEenheidId || undefined,
                samenwerkingsverbandIds: Array.from(
                  contact.fields.samenwerkingsverbandIds,
                ),
              });
              personId = result?.personId ?? null;
              if (!personId) continue;
            }
            await addLeadContactApi(lead.id, personId, contact.rol);
          } catch {
            // Non-critical, don't block lead creation
          }
        }
      }

      handleClose();
    } catch {
      // Error is shown by useMutationWithError
    }
  };

  const canParse = rawText.trim().length > 0 || files.length > 0;
  const canSubmit = title.trim().length > 0 && initiatiefId.length > 0;

  return (
    <Modal
      open={open}
      onClose={handleClose}
      title="Nieuwe lead"
      size="xl"
    >
      {step === 'input' && (
        <nldd-container gap="16">
          {(initiatieven?.length ?? 0) !== 1 && (
            <CreatableSelect
              label="Voor welk initiatief is deze lead?"
              value={initiatiefId}
              onChange={setInitiatiefId}
              options={initiatieven?.map((i) => ({
                value: i.id,
                label: i.naam,
              })) ?? []}
              placeholder="Selecteer initiatief..."
              onCreate={async (name) => {
                const kleur = INITIATIEF_COLORS[Math.floor(Math.random() * INITIATIEF_COLORS.length)];
                const result = await createInitiatiefMutation.mutateAsync({ naam: name, kleur });
                return result.id;
              }}
              createLabel="Nieuw initiatief"
            />
          )}

          {emailParsing && (
            <nldd-card background="tinted">
              <nldd-container layout="row" gap="8" vertical-alignment="center" padding="8" padding-inline="12">
                <LoadingSpinner size="sm" />
                <nldd-text size="sm" color="accent">E-mail wordt gelezen...</nldd-text>
              </nldd-container>
            </nldd-card>
          )}

          {parsedEmail && !emailParsing && (
            <nldd-card background="tinted">
              <nldd-container layout="row" gap="8" vertical-alignment="center" padding="8" padding-inline="12">
                <nldd-icon icon="envelope" size="16" color="accent" aria-hidden="true" />
                <nldd-text size="sm" color="accent">
                  E-mail van {parsedEmail.senderName || parsedEmail.senderEmail}
                  {parsedEmail.subject ? `: ${parsedEmail.subject}` : ''}
                  {parsedEmail.date ? ` (${parsedEmail.date})` : ''}
                </nldd-text>
              </nldd-container>
            </nldd-card>
          )}

          {/* The dashed drop-zone border and its drag-active highlight are
              driven by live drag state, not a fixed variant, and there is no
              nldd-container border/dashed-outline attribute, so this is an
              inline style. */}
          <div
            onPaste={handlePaste}
            onDragOver={(e) => { e.preventDefault(); setDragActive(true); }}
            onDragLeave={() => setDragActive(false)}
            onDrop={handleDrop}
            style={{
              position: 'relative',
              borderRadius: '12px',
              border: `2px dashed ${dragActive ? 'var(--primitives-color-accent-300)' : 'var(--primitives-color-neutral-300)'}`,
              backgroundColor: dragActive ? 'var(--primitives-color-accent-25)' : 'transparent',
              transition: 'colors 150ms',
            }}
          >
            <nldd-multi-line-text-field
              ref={rawTextFieldRef}
              value={rawText}
              placeholder="Plak tekst, screenshot, of sleep een bestand of e-mail hierheen..."
              accessible-label="Ruwe invoer voor lead-analyse"
              rows={6}
              autoFocus
              width="full"
            />
            {dragActive && (
              <div
                style={{
                  position: 'absolute',
                  inset: 0,
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  backgroundColor: 'var(--primitives-color-accent-25)',
                  opacity: 0.9,
                  borderRadius: '12px',
                  pointerEvents: 'none',
                }}
              >
                <nldd-container layout="row" gap="8" vertical-alignment="center">
                  <nldd-icon icon="upload" size="20" aria-hidden="true" />
                  <nldd-text size="sm" weight="medium" color="accent">Sleep bestanden hierheen</nldd-text>
                </nldd-container>
              </div>
            )}
          </div>

          {files.length > 0 && (
            <nldd-container gap="2">
              {files.map((file, i) => (
                <nldd-card key={i} background="tinted">
                  <nldd-container layout="row" gap="8" vertical-alignment="center" padding="6" padding-inline="12">
                    {file.type.startsWith('image/') ? (
                      <nldd-image
                        src={URL.createObjectURL(file)}
                        alt={file.name}
                        width="32"
                        height={32}
                        object-fit="cover"
                        shape="rounded"
                        loading="eager"
                      />
                    ) : (
                      <nldd-icon icon="file-text" size="16" aria-hidden="true" />
                    )}
                    <nldd-text size="sm" color="secondary" className="truncate row-fill">
                      {file.name}
                    </nldd-text>
                    <NlddIconButton
                      icon="close"
                      accessibleLabel="Bestand verwijderen"
                      variant="neutral-transparent"
                      size="sm"
                      onClick={() => removeFile(i)}
                    />
                  </nldd-container>
                </nldd-card>
              ))}
            </nldd-container>
          )}

          <input
            ref={fileInputRef}
            type="file"
            multiple
            hidden
            onChange={(e) => {
              if (e.target.files) {
                addFiles(Array.from(e.target.files));
              }
            }}
          />

          <nldd-container layout="row" gap="8" vertical-alignment="center">
            <NlddButton
              variant="neutral-transparent"
              size="sm"
              onClick={() => fileInputRef.current?.click()}
              startIcon="upload"
              text="Bestand toevoegen"
            />
            {/* fit-content + row-fill, not the container default of full: that
                default takes a hard 100% of the row and squeezes the button
                beside it below its own label, which then wraps into a two-line
                block. */}
            <nldd-container
              layout="row"
              width="fit-content"
              className="row-fill"
              gap="12"
              horizontal-alignment="right"
            >
              <NlddButton
                variant="neutral-transparent"
                onClick={handleSkipParse}
                disabled={!initiatiefId}
                text="Handmatig invullen"
              />
              <NlddButton
                onClick={handleParse}
                disabled={!canParse || !initiatiefId}
                startIcon="sparkles"
                text="Analyseren met VLAM"
              />
            </nldd-container>
          </nldd-container>
        </nldd-container>
      )}

      {step === 'parsing' && (
        <nldd-container gap="12" horizontal-alignment="center" padding="48">
          <LoadingSpinner />
          <nldd-text size="sm" color="secondary" horizontal-alignment="center">VLAM analyseert je invoer...</nldd-text>
        </nldd-container>
      )}

      {step === 'confirm' && (
        <nldd-container gap="16">
          {parseResult && (
            <nldd-card background="tinted">
              <nldd-container padding="8" padding-inline="12">
                <nldd-text size="xs" color="secondary">
                  VLAM heeft de volgende velden voorgesteld. Pas aan waar nodig.
                </nldd-text>
              </nldd-container>
            </nldd-card>
          )}

          {/* Two-column layout */}
          <nldd-container layout="grid" column-count={1} md-column-count={2} gap="16">
            {/* LEFT COLUMN: Lead info */}
            <nldd-container gap="16">
              <nldd-title size={6}>
                <h3>Lead</h3>
              </nldd-title>

              <Input
                label="Titel"
                type="text"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                placeholder="Titel van de lead"
                required
                autoFocus
              />

              {duplicates && duplicates.length > 0 && (
                <nldd-banner variant="warning" size="sm" text="Vergelijkbare leads gevonden:">
                  <nldd-container gap="4">
                    {duplicates.map((d) => (
                      <DuplicateLeadLink
                        key={d.id}
                        title={d.title}
                        detail={`${d.organization ?? 'geen organisatie'} - ${stageColumnsBySlug.get(d.stage)?.name ?? d.stage}`}
                        onOpen={() => { openLeadDetail(d.id); handleClose(); }}
                      />
                    ))}
                  </nldd-container>
                </nldd-banner>
              )}

              <nldd-form-field label="Status">
                <nldd-container layout="wrap" gap="6">
                  {sortedStageColumns.map((c) => (
                    <StagePill
                      key={c.id}
                      name={c.name}
                      color={c.color}
                      active={stage === c.slug}
                      onSelect={() => setStage(c.slug)}
                    />
                  ))}
                </nldd-container>
              </nldd-form-field>

              <nldd-container layout="grid" column-count={2} gap="12">
                <Input
                  label="Datum"
                  type="date"
                  value={leadDate}
                  onChange={(e) => setLeadDate(e.target.value)}
                />
                <Input
                  label="Organisatie"
                  type="text"
                  value={organization}
                  onChange={(e) => setOrganization(e.target.value)}
                  placeholder="Naam van de organisatie"
                  autoComplete="organization"
                />
              </nldd-container>

              <RichTextFormField
                label="Beschrijving"
                value={description}
                onChange={setDescription}
                rows={5}
                placeholder="Korte beschrijving... Gebruik @ voor personen, # voor nodes/taken"
              />

              <nldd-form-field label="Tags">
                <TagTokenField
                  values={selectedTags}
                  tagNames={tagNames}
                  onChange={setSelectedTags}
                />
              </nldd-form-field>
            </nldd-container>

            {/* RIGHT COLUMN: People */}
            <nldd-container gap="16">
              <nldd-title size={6}>
                <h3>Personen</h3>
              </nldd-title>

              <CreatableSelect
                label="Binnengebracht door"
                value={broughtById}
                onChange={setBroughtById}
                options={assigneeOptions}
                placeholder="Zoek een teamlid..."
              />

              <CreatableSelect
                label="Verantwoordelijke"
                value={assigneeId}
                onChange={setAssigneeId}
                options={assigneeOptions}
                placeholder="Zoek een persoon..."
                onClear={() => setAssigneeId('')}
              />

              {contacts.map((contact, index) => (
                <nldd-container key={index} gap="16">
                  {index > 0 && (
                    <>
                      <nldd-divider />
                      <nldd-container layout="row" gap="8" vertical-alignment="center">
                        <nldd-text size="xs" weight="medium" color="secondary">Extra externe contactpersoon</nldd-text>
                        <NlddIconButton
                          icon="close"
                          accessibleLabel="Verwijderen"
                          variant="neutral-transparent"
                          size="sm"
                          onClick={() => setContacts(prev => prev.filter((_, i) => i !== index))}
                        />
                      </nldd-container>
                    </>
                  )}

                  <CreatableSelect
                    label={index === 0 ? "Externe contactpersoon" : "Extra externe contactpersoon"}
                    value={contact.personId}
                    onChange={(val) => {
                      const person = people?.find((p) => p.id === val);
                      updateContact(index, {
                        personId: val,
                        fields: {
                          ...contact.fields,
                          naam: person?.naam ?? contact.fields.naam,
                        },
                      });
                    }}
                    options={contactOptions}
                    placeholder="Zoek of typ een naam..."
                    onCreate={async (name) => {
                      updateContact(index, {
                        personId: '',
                        fields: { ...contact.fields, naam: name },
                      });
                      return null;
                    }}
                    createLabel="Nieuw contact"
                    displayValue={
                      !contact.personId && contact.fields.naam ? contact.fields.naam : undefined
                    }
                    onClear={() => {
                      updateContact(index, emptyContact());
                    }}
                  />

                  {!contact.personId && contact.fields.naam && (
                    <NewContactPersonFields
                      state={contact.fields}
                      onChange={(next) => updateContact(index, { fields: next })}
                      hideNaam
                      extraExpertiseValues={extraExpertiseValues}
                      onAddExtraExpertise={addExtraExpertise}
                    />
                  )}
                </nldd-container>
              ))}

              {contacts.length < 2 && (
                <NlddButton
                  variant="neutral-transparent"
                  size="sm"
                  text="Extra externe contactpersoon toevoegen"
                  startIcon="plus"
                  onClick={() => setContacts(prev => [...prev, emptyContact()])}
                />
              )}
            </nldd-container>
          </nldd-container>

          {/* Files + buttons below both columns */}
          {files.length > 0 && (
            <nldd-text size="xs" color="secondary">
              {files.length} {files.length === 1 ? 'bijlage' : 'bijlagen'} worden meegestuurd
            </nldd-text>
          )}

          <nldd-container layout="row" gap="8" horizontal-alignment="right" padding-top="16">
            <NlddButton variant="neutral-transparent" onClick={() => setStep('input')} text="Terug" />
            <NlddButton
              onClick={handleSubmit}
              disabled={!canSubmit}
              loading={createLead.isPending}
              text="Lead aanmaken"
            />
          </nldd-container>
        </nldd-container>
      )}
    </Modal>
  );
}

interface StagePillProps {
  name: string;
  color: string;
  active: boolean;
  onSelect: () => void;
}

/**
 * A stage's color comes from the same closed set as ColumnsManager's swatch
 * picker; this is a click-to-select choice, not a status label, so it stays
 * a segment (nldd-tag has no click semantics) with an nldd-tag inside for
 * the color and text, same pattern as ColumnsManager's ToggleChip.
 */
function StagePill({ name, color, active, onSelect }: StagePillProps) {
  const ref = useRef<HTMLElement>(null);
  useNlddEvent(ref, 'click', onSelect);

  return (
    // `current` marks which one is chosen, for the element's own ARIA. The
    // check mark is the second signal: color alone means nothing to a
    // colorblind user and nothing at all to a screen reader (WCAG 1.4.1).
    <nldd-list-item-segment ref={ref} button {...(active ? { current: true } : {})}>
      <nldd-tag
        text={name}
        color={active ? leadColumnTagColor(color) : 'neutral'}
        size="sm"
        {...(active ? { icon: 'check-mark' } : {})}
      />
    </nldd-list-item-segment>
  );
}

interface DuplicateLeadLinkProps {
  title: string;
  detail: string;
  onOpen: () => void;
}

function DuplicateLeadLink({ title, detail, onOpen }: DuplicateLeadLinkProps) {
  return (
    <nldd-container layout="row" gap="4" vertical-alignment="center">
      <NlddButton variant="neutral-transparent" size="xs" text={title} onClick={onOpen} />
      <nldd-text size="sm" color="secondary">({detail})</nldd-text>
    </nldd-container>
  );
}

interface TagTokenFieldProps {
  /** Chosen tag names, existing or new. */
  values: string[];
  /** Every known tag name, offered in the menu. */
  tagNames: string[];
  onChange: (values: string[]) => void;
}

/**
 * The lead's tags as an `nldd-token-field`: chosen tags are dismissible tokens,
 * the menu offers every known tag (the field hides those already chosen), and
 * `allow-custom` turns typed text that matches nothing into a new tag. Tags go
 * to the API by name, so a token's value is the name itself.
 *
 * `.values` is a live property, not a reflected attribute, so it is written
 * only when it has diverged from React state (a parse result filling in
 * suggested tags, a reset), never mid-typing.
 */
function TagTokenField({ values, tagNames, onChange }: TagTokenFieldProps) {
  const ref = useRef<HTMLElement & { values?: string[] }>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const current = el.values ?? [];
    if (current.length !== values.length || !values.every((v) => current.includes(v))) {
      el.values = values;
    }
  }, [values]);

  useNlddEvent(
    ref,
    'change',
    useCallback(
      (event: Event) => {
        const next = (event as CustomEvent<{ values?: string[] }>).detail?.values ?? [];
        onChange(next.map((v) => v.trim()).filter(Boolean));
      },
      [onChange],
    ),
  );

  return (
    <nldd-token-field
      ref={ref}
      placeholder="Zoek of typ een tag..."
      allow-custom
      accessible-label="Tags"
    >
      <nldd-menu>
        {tagNames.map((name) => (
          <nldd-menu-item key={name} value={name} text={name} />
        ))}
      </nldd-menu>
    </nldd-token-field>
  );
}
