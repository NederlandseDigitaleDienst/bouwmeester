// Node Types
export enum NodeType {
  DOSSIER = 'dossier',
  DOEL = 'doel',
  INSTRUMENT = 'instrument',
  BELEIDSKADER = 'beleidskader',
  MAATREGEL = 'maatregel',
  POLITIEKE_INPUT = 'politieke_input',
  PROBLEEM = 'probleem',
  EFFECT = 'effect',
  BELEIDSOPTIE = 'beleidsoptie',
  BRON = 'bron',
  NOTITIE = 'notitie',
  OVERIG = 'overig',
}

export const NODE_TYPE_LABELS: Record<NodeType, string> = {
  [NodeType.DOSSIER]: 'Dossier',
  [NodeType.DOEL]: 'Doel',
  [NodeType.INSTRUMENT]: 'Instrument',
  [NodeType.BELEIDSKADER]: 'Beleidskader',
  [NodeType.MAATREGEL]: 'Maatregel',
  [NodeType.POLITIEKE_INPUT]: 'Politieke Input',
  [NodeType.PROBLEEM]: 'Probleem',
  [NodeType.EFFECT]: 'Effect',
  [NodeType.BELEIDSOPTIE]: 'Beleidsoptie',
  [NodeType.BRON]: 'Bron',
  [NodeType.NOTITIE]: 'Notitie',
  [NodeType.OVERIG]: 'Overig',
};

/** Dutch plural forms for node type labels. */
export const NODE_TYPE_LABELS_PLURAL: Partial<Record<NodeType, string>> = {
  [NodeType.PROBLEEM]: 'problemen',
  [NodeType.DOEL]: 'doelen',
  [NodeType.BELEIDSOPTIE]: 'beleidsopties',
  [NodeType.BELEIDSKADER]: 'beleidskaders',
  [NodeType.INSTRUMENT]: 'instrumenten',
  [NodeType.MAATREGEL]: 'maatregelen',
  [NodeType.EFFECT]: 'effecten',
};

export const NODE_TYPE_COLORS: Record<NodeType, EntityColor> = {
  [NodeType.DOSSIER]: 'lintblauw',
  [NodeType.DOEL]: 'groen',
  [NodeType.INSTRUMENT]: 'paars',
  [NodeType.BELEIDSKADER]: 'geel',
  [NodeType.MAATREGEL]: 'hemelblauw',
  [NodeType.POLITIEKE_INPUT]: 'roze',
  [NodeType.PROBLEEM]: 'rood',
  [NodeType.EFFECT]: 'mosgroen',
  [NodeType.BELEIDSOPTIE]: 'violet',
  [NodeType.BRON]: 'oranje',
  [NodeType.NOTITIE]: 'donkerblauw',
  [NodeType.OVERIG]: 'coolgray',
};

/**
 * A node type's color as a CSS value: step 500 is the full tone (accent bars,
 * edges, dots), step 50 the pale tint behind a label in that tone. The graph
 * views paint from this instead of keeping a second table next to
 * NODE_TYPE_COLORS, so a node looks the same in a badge, a modal and a graph.
 */
export function nodeTypeColor(type: NodeType, step: EntityColorStep = 500): string {
  return entityColorVar(NODE_TYPE_COLORS[type] ?? 'coolgray', step);
}

export const BRON_TYPE_LABELS: Record<string, string> = {
  rapport: 'Rapport',
  onderzoek: 'Onderzoek',
  wetgeving: 'Wetgeving',
  advies: 'Advies',
  opinie: 'Opinie',
  beleidsnota: 'Beleidsnota',
  evaluatie: 'Evaluatie',
  overig: 'Overig',
};

export const INSTRUMENT_TYPE_LABELS: Record<string, string> = {
  wetgeving: 'Wetgeving',
  subsidie: 'Subsidie',
  voorlichting: 'Voorlichting',
  handhaving: 'Handhaving',
  overig: 'Overig',
};

// Node Status
export enum NodeStatus {
  CONCEPT = 'concept',
  ACTIEF = 'actief',
  GEPAUZEERD = 'gepauzeerd',
  AFGEROND = 'afgerond',
  GEKOZEN = 'gekozen',
  AFGEWEZEN = 'afgewezen',
}

export const NODE_STATUS_LABELS: Record<NodeStatus, string> = {
  [NodeStatus.CONCEPT]: 'Concept',
  [NodeStatus.ACTIEF]: 'Actief',
  [NodeStatus.GEPAUZEERD]: 'Gepauzeerd',
  [NodeStatus.AFGEROND]: 'Afgerond',
  [NodeStatus.GEKOZEN]: 'Gekozen',
  [NodeStatus.AFGEWEZEN]: 'Afgewezen',
};

// Beleidskompas progress (returned for dossier nodes)
export interface BeleidskompasProgress {
  completed_steps: number;
  total_steps: number;
}

// Financial summary (returned for instrument nodes)
export interface FinancieelSummary {
  totaal_budget: number;
  totaal_gerealiseerd: number;
}

// Corpus Node
export interface CorpusNode {
  id: string;
  title: string;
  node_type: NodeType;
  description?: string;
  status?: string;
  metadata?: Record<string, unknown>;
  geldig_van?: string | null;
  geldig_tot?: string | null;
  created_at: string;
  updated_at: string;
  edge_count?: number;
  beleidskompas_progress?: BeleidskompasProgress | null;
  financieel_summary?: FinancieelSummary | null;
}

export interface CorpusNodeCreate {
  title: string;
  node_type: NodeType;
  description?: string;
  status?: string;
  metadata?: Record<string, unknown>;
  geldig_van?: string | null;
  /** Only used when node_type is 'instrument'; sets Instrument.type. */
  instrument_type?: string;
}

export interface CorpusNodeUpdate {
  title?: string;
  description?: string;
  status?: string;
  metadata?: Record<string, unknown>;
  geldig_tot?: string | null;
  wijzig_datum?: string | null;
}

export interface NodeTitleRecord {
  id: string;
  title: string;
  geldig_van: string;
  geldig_tot?: string | null;
}

export interface NodeStatusRecord {
  id: string;
  status: string;
  geldig_van: string;
  geldig_tot?: string | null;
}

// Edges
export interface Edge {
  id: string;
  from_node_id: string;
  to_node_id: string;
  edge_type_id: string;
  weight?: number;
  description?: string;
  created_at: string;
  from_node?: CorpusNode;
  to_node?: CorpusNode;
}

export interface EdgeCreate {
  from_node_id: string;
  to_node_id: string;
  edge_type_id: string;
  description?: string;
}

// Tasks
export enum TaskStatus {
  OPEN = 'open',
  IN_PROGRESS = 'in_progress',
  DONE = 'done',
  CANCELLED = 'cancelled',
}

export enum TaskPriority {
  KRITIEK = 'kritiek',
  HOOG = 'hoog',
  NORMAAL = 'normaal',
  LAAG = 'laag',
}

export const TASK_STATUS_LABELS: Record<TaskStatus, string> = {
  [TaskStatus.OPEN]: 'Open',
  [TaskStatus.IN_PROGRESS]: 'In uitvoering',
  [TaskStatus.DONE]: 'Afgerond',
  [TaskStatus.CANCELLED]: 'Geannuleerd',
};

export const TASK_PRIORITY_LABELS: Record<TaskPriority, string> = {
  [TaskPriority.KRITIEK]: 'Kritiek',
  [TaskPriority.HOOG]: 'Hoog',
  [TaskPriority.NORMAAL]: 'Normaal',
  [TaskPriority.LAAG]: 'Laag',
};

export const TASK_PRIORITY_COLORS: Record<TaskPriority, EntityColor> = {
  [TaskPriority.KRITIEK]: 'rood',
  [TaskPriority.HOOG]: 'oranje',
  [TaskPriority.NORMAAL]: 'lintblauw',
  [TaskPriority.LAAG]: 'coolgray',
};

export const TASK_STATUS_COLORS: Record<TaskStatus, EntityColor> = {
  [TaskStatus.OPEN]: 'lintblauw',
  [TaskStatus.IN_PROGRESS]: 'geel',
  [TaskStatus.DONE]: 'groen',
  [TaskStatus.CANCELLED]: 'coolgray',
};

export interface TaskOrgEenheidSummary {
  id: string;
  naam: string;
  type: string;
}

export interface TaskSubtask {
  id: string;
  title: string;
  status: TaskStatus;
  priority: TaskPriority;
  assignee?: { id: string; naam: string; is_agent: boolean };
  due_date?: string;
  order?: number;
  work_type?: string;
}

export interface TaskOpdrachtSummary {
  id: string;
  titel: string;
  type: string;
  status: string;
}

export interface Task {
  id: string;
  title: string;
  description?: string;
  status: TaskStatus;
  priority: TaskPriority;
  due_date?: string;
  assignee_id?: string;
  assignee?: Person;
  organisatie_eenheid_id?: string;
  organisatie_eenheid?: TaskOrgEenheidSummary;
  parent_id?: string;
  parlementair_item_id?: string;
  opdracht_id?: string;
  opdracht?: TaskOpdrachtSummary;
  subtasks?: TaskSubtask[];
  node_id?: string;
  node?: CorpusNode;
  order?: number;
  work_type?: string;
  created_at: string;
  updated_at: string;
}

export interface TaskCreate {
  title: string;
  description?: string;
  status?: TaskStatus;
  priority?: TaskPriority;
  due_date?: string;
  assignee_id?: string;
  organisatie_eenheid_id?: string;
  parent_id?: string;
  parlementair_item_id?: string;
  opdracht_id?: string;
  node_id: string;
  work_type?: string;
}

export interface TaskUpdate {
  title?: string;
  description?: string | null;
  status?: TaskStatus;
  priority?: TaskPriority;
  due_date?: string | null;
  assignee_id?: string | null;
  organisatie_eenheid_id?: string | null;
  parent_id?: string | null;
  opdracht_id?: string | null;
  work_type?: string | null;
}

export interface EenheidPersonTaskStats {
  person_id: string;
  person_naam: string;
  open_count: number;
  in_progress_count: number;
  done_count: number;
  overdue_count: number;
}

export interface EenheidSubeenheidStats {
  eenheid_id: string;
  eenheid_naam: string;
  eenheid_type: string;
  open_count: number;
  in_progress_count: number;
  done_count: number;
  overdue_count: number;
}

export interface EenheidOverviewResponse {
  unassigned_count: number;
  unassigned_no_unit: Task[];
  unassigned_no_unit_count: number;
  unassigned_no_person: Task[];
  unassigned_no_person_count: number;
  by_person: EenheidPersonTaskStats[];
  by_subeenheid: EenheidSubeenheidStats[];
  eenheid_type: string;
}

// Organisatie Eenheid
export interface OrganisatieEenheid {
  id: string;
  naam: string;
  type: string;
  parent_id?: string | null;
  manager_id?: string | null;
  manager?: Person | null;
  beschrijving?: string | null;
  afkorting?: string | null;
  website?: string | null;
  kvk_nummer?: string | null;
  tooi_uri?: string | null;
  tooi_organisatiesoort?: string | null;
  oin?: string | null;
  fte_aantal?: number | null;
  bron?: 'handmatig' | 'tooi' | 'synthetisch' | 'organogram_scrape' | 'fcc_import';
  geldig_van?: string | null;
  geldig_tot?: string | null;
  created_at: string;
}

export interface OrganisatieEenheidTreeNode extends OrganisatieEenheid {
  children: OrganisatieEenheidTreeNode[];
  personen_count: number;
  children_count?: number;
  has_children?: boolean;
}

export interface OrganisatieEenheidCreate {
  naam: string;
  type: string;
  parent_id?: string | null;
  manager_id?: string | null;
  beschrijving?: string | null;
  afkorting?: string | null;
  website?: string | null;
  kvk_nummer?: string | null;
  geldig_van?: string | null;
}

export interface OrganisatieEenheidUpdate {
  naam?: string;
  type?: string;
  parent_id?: string | null;
  manager_id?: string | null;
  beschrijving?: string | null;
  afkorting?: string | null;
  website?: string | null;
  kvk_nummer?: string | null;
  geldig_tot?: string | null;
  wijzig_datum?: string | null;
}

export interface OrgNaamRecord {
  id: string;
  naam: string;
  geldig_van: string;
  geldig_tot?: string | null;
}

export interface OrgParentRecord {
  id: string;
  parent_id: string;
  geldig_van: string;
  geldig_tot?: string | null;
}

export interface OrgManagerRecord {
  id: string;
  manager_id?: string | null;
  manager?: Person | null;
  geldig_van: string;
  geldig_tot?: string | null;
}

export interface OrganisatieEenheidPersonenGroup {
  eenheid: OrganisatieEenheid;
  personen: Person[];
  children: OrganisatieEenheidPersonenGroup[];
}

const ORGANISATIE_TYPE_LABELS: Record<string, string> = {
  ministerie: 'Ministerie',
  directoraat_generaal: 'Directoraat-Generaal',
  directie: 'Directie',
  dienst: 'Dienst',
  bureau: 'Bureau',
  afdeling: 'Afdeling',
  cluster: 'Cluster',
  team: 'Team',
  zbo: 'ZBO / agentschap',
  gemeente: 'Gemeente',
  provincie: 'Provincie',
  waterschap: 'Waterschap',
  samenwerkingsorganisatie: 'Samenwerkingsorganisatie',
  caribisch_openbaar_lichaam: 'Caribisch openbaar lichaam',
  hoge_college_van_staat: 'Hoge College van Staat',
  rechtspraak: 'Rechtspraak',
  openbaar_ministerie: 'Openbaar Ministerie',
  synthetische_groep: 'Categorie',
  overig: 'Overig',
  uitvoeringsorganisatie: 'Uitvoeringsorganisatie',
  koepelorganisatie: 'Koepelorganisatie',
  stichting: 'Stichting',
  marktpartij: 'Marktpartij',
  onderwijsinstelling: 'Onderwijsinstelling',
  universiteit: 'Universiteit',
  hogeschool: 'Hogeschool',
};

/**
 * The color an entity type is known by: its badge, its modal accent, its graph
 * node. Each value is a Rijkshuisstijl primitive name, so it names a design
 * system color scale as is (see entityColorVar). Badge translates the ones that
 * carry meaning to a semantic tag role (see common/Badge.tsx).
 */
export type EntityColor = 'lintblauw' | 'groen' | 'paars' | 'geel' | 'hemelblauw' | 'roze' | 'donkerblauw' | 'coolgray' | 'rood' | 'oranje' | 'mosgroen' | 'violet';

/** The steps of the Rijkshuisstijl scale this app paints entity colors at. */
export type EntityColorStep = 50 | 400 | 500;

/**
 * An entity color as a CSS value. The primitive is `light-dark()` underneath,
 * so the tint follows the color scheme without a second table.
 */
export function entityColorVar(color: EntityColor, step: EntityColorStep = 500): string {
  return `var(--primitives-color-${color}-${step})`;
}

export const ORGANISATIE_TYPE_BADGE_COLORS: Record<string, EntityColor> = {
  ministerie: 'lintblauw',
  directoraat_generaal: 'paars',
  directie: 'geel',
  dienst: 'coolgray',
  bureau: 'coolgray',
  cluster: 'coolgray',
  afdeling: 'hemelblauw',
  team: 'groen',
  zbo: 'violet',
  gemeente: 'mosgroen',
  provincie: 'roze',
  waterschap: 'hemelblauw',
  samenwerkingsorganisatie: 'donkerblauw',
  caribisch_openbaar_lichaam: 'oranje',
  hoge_college_van_staat: 'rood',
  rechtspraak: 'rood',
  openbaar_ministerie: 'rood',
  synthetische_groep: 'donkerblauw',
  overig: 'coolgray',
  uitvoeringsorganisatie: 'violet',
  koepelorganisatie: 'donkerblauw',
  stichting: 'coolgray',
  marktpartij: 'oranje',
  onderwijsinstelling: 'paars',
  universiteit: 'paars',
  hogeschool: 'paars',
};

export function formatOrganisatieType(type: string): string {
  return ORGANISATIE_TYPE_LABELS[type] ?? type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

// Types die een gebruiker handmatig kan aanmaken via OrganisatieForm.
// TOOI-types (gemeente, provincie, zbo, ...) en synthetische groepen
// zitten hier expres niet bij — die komen alleen uit syncs en zouden
// anders botsen met TOOI-rijen via reconciliation.
const HANDMATIG_AANMAAKBARE_TYPES = [
  'ministerie',
  'directoraat_generaal',
  'directie',
  'dienst',
  'bureau',
  'afdeling',
  'cluster',
  'team',
  'stichting',
  'marktpartij',
  'koepelorganisatie',
  'overig',
] as const;

export const ORGANISATIE_TYPE_OPTIONS: { value: string; label: string }[] =
  HANDMATIG_AANMAAKBARE_TYPES.map((value) => ({
    value,
    label: ORGANISATIE_TYPE_LABELS[value] ?? value,
  }));

export const FUNCTIE_LABELS: Record<string, string> = {
  minister: 'Minister',
  staatssecretaris: 'Staatssecretaris',
  secretaris_generaal: 'Secretaris-Generaal',
  plaatsvervangend_secretaris_generaal: 'Plaatsvervangend Secretaris-Generaal',
  directeur_generaal: 'Directeur-Generaal',
  plaatsvervangend_directeur_generaal: 'Plaatsvervangend Directeur-Generaal',
  directeur: 'Directeur',
  afdelingshoofd: 'Afdelingshoofd',
  coordinator: 'Coördinator',
  beleidsmedewerker: 'Beleidsmedewerker',
  senior_beleidsmedewerker: 'Senior Beleidsmedewerker',
  adviseur: 'Adviseur',
  projectleider: 'Projectleider',
  programmamanager: 'Programmamanager',
  jurist: 'Jurist',
  'coördinerend_beleidsmedewerker': 'Coördinerend Beleidsmedewerker',
  communicatieadviseur: 'Communicatieadviseur',
  staff_engineer: 'Staff Engineer',
};

/**
 * Unicode-safe title case: capitalize the first letter of each space-separated word.
 * Unlike \b\w which treats non-ASCII (ö, é, …) as word boundaries, this splits
 * on whitespace so "coördinerend beleidsmedewerker" → "Coördinerend Beleidsmedewerker".
 */
export function titleCase(str: string): string {
  return str
    .split(' ')
    .map(w => (w.length > 0 ? w.charAt(0).toUpperCase() + w.slice(1) : w))
    .join(' ');
}

export function formatFunctie(functie?: string | null): string | undefined {
  if (!functie) return undefined;
  return FUNCTIE_LABELS[functie] ?? titleCase(functie.replace(/_/g, ' '));
}

// People
export interface PersonEmail {
  id: string;
  email: string;
  is_default: boolean;
  created_at: string;
}

export interface PersonPhone {
  id: string;
  phone_number: string;
  label: string;
  is_default: boolean;
  created_at: string;
}

export const PHONE_LABELS: Record<string, string> = {
  werk: 'Werk',
  mobiel: 'Mobiel',
  prive: 'Priv\u00e9',
};

export interface Person {
  id: string;
  naam: string;
  email?: string;
  functie?: string;
  expertise?: string | null;
  description?: string;
  is_agent: boolean;
  is_admin: boolean;
  has_api_key?: boolean;
  is_active: boolean;
  created_at: string;
  last_seen_at?: string | null;
  emails: PersonEmail[];
  phones: PersonPhone[];
  default_email?: string | null;
  default_phone?: string | null;
  tk_persoon_id?: string | null;
  wikidata_qid?: string | null;
  bron?: 'handmatig' | 'tk_odata' | 'kabinet_yaml' | 'roo_leidinggevende' | 'abd_scrape';
}

/** Extended response from POST /api/people — includes one-time api_key for agents. */
export interface PersonCreateResult extends Person {
  api_key?: string | null;
}

export interface PersonCreate {
  naam: string;
  email?: string;
  functie?: string;
  expertise?: string;
  description?: string;
  is_agent?: boolean;
}

export interface ApiKeyResponse {
  api_key: string;
  person_id: string;
}

// PersonEditForm submit discriminated union
/** Create a new person (optionally link to org) */
interface PersonFormCreate {
  kind: 'create';
  data: PersonCreate;
  orgEenheidId?: string;
  dienstverband?: string;
}

/** Link an existing person to an org */
interface PersonFormLink {
  kind: 'link';
  existingPersonId: string;
  orgEenheidId?: string;
  dienstverband?: string;
}

/** Edit an existing person's fields */
interface PersonFormEdit {
  kind: 'edit';
  personId: string;
  data: PersonCreate;
}

export type PersonFormSubmitParams = PersonFormCreate | PersonFormLink | PersonFormEdit;

// Person ↔ OrganisatieEenheid placements
export interface PersonOrganisatie {
  id: string;
  person_id: string;
  organisatie_eenheid_id: string;
  organisatie_eenheid_naam: string;
  dienstverband: string;
  functietitel?: string | null;
  bron?: string;
  start_datum: string;
  eind_datum?: string | null;
}

export const DIENSTVERBAND_LABELS: Record<string, string> = {
  in_dienst: 'In dienst',
  ingehuurd: 'Ingehuurd',
  extern: 'Extern',
};

// Person Summary (expanded card)
export interface PersonTaskSummary {
  id: string;
  title: string;
  status: TaskStatus;
  priority: TaskPriority;
  due_date?: string;
}

export interface PersonStakeholderNode {
  node_id: string;
  node_title: string;
  node_type: NodeType;
  stakeholder_rol: string;
}

export interface PersonSummaryResponse {
  open_task_count: number;
  done_task_count: number;
  open_tasks: PersonTaskSummary[];
  stakeholder_nodes: PersonStakeholderNode[];
}

export interface NodeStakeholder {
  id: string;
  person: Person;
  rol: string;
}

export const STAKEHOLDER_ROL_LABELS: Record<string, string> = {
  eigenaar: 'Eigenaar',
  betrokken: 'Betrokken',
  adviseur: 'Adviseur',
  indiener: 'Indiener',
};

export const LEAD_CONTACT_ROL_LABELS: Record<string, string> = {
  contactpersoon: 'Externe contactpersoon',
  opdrachtgever: 'Opdrachtgever',
  betrokken: 'Betrokken',
};

export const INITIATIEF_ROL_LABELS: Record<string, string> = {
  eigenaar: 'Eigenaar',
  contributor: 'Bijdrager',
  viewer: 'Lezer',
};

// Notification type labels and colors
export const NOTIFICATION_TYPE_LABELS: Record<string, string> = {
  task_assigned: 'taak toegewezen',
  task_overdue: 'taak verlopen',
  task_completed: 'taak afgerond',
  task_reassigned: 'taak overgedragen',
  node_updated: 'node bijgewerkt',
  edge_created: 'relatie aangemaakt',
  coverage_needed: 'vervanging nodig',
  stakeholder_added: 'betrokkene toegevoegd',
  stakeholder_role_changed: 'rol gewijzigd',
  direct_message: 'bericht',
  agent_prompt: 'agent prompt',
  mention: 'vermelding',
  politieke_input_imported: 'parlementair item',
  access_request: 'toegangsverzoek',
  placement_request: 'teamverzoek',
  placement_approved: 'toegevoegd aan team',
  placement_denied: 'verzoek afgewezen',
  emoji_reaction: 'reactie',
};

/**
 * Notification type → `nldd-tag` color.
 *
 * Same rule as TAG_COLOR in common/Badge.tsx: a type that carries meaning
 * gets the semantic role, which keeps it right in dark mode and for colorblind
 * users, and the rest get the nearest Rijkshuisstijl color. node_updated,
 * direct_message and placement_approved deliberately share `success`: all
 * three read as "something went well".
 *
 * The label beside the color says which type it is, so the color never carries
 * the meaning on its own (WCAG 1.4.1).
 */
export const NOTIFICATION_TYPE_COLORS: Record<string, string> = {
  // Semantic roles.
  task_overdue: 'critical',
  placement_denied: 'critical',
  task_completed: 'success',
  node_updated: 'success',
  direct_message: 'success',
  placement_approved: 'success',
  task_reassigned: 'warning',
  coverage_needed: 'warning',
  access_request: 'warning',
  task_assigned: 'accent',
  // Decorative: nearest Rijkshuisstijl color.
  edge_created: 'paars',
  stakeholder_added: 'mintgroen',
  stakeholder_role_changed: 'mintgroen',
  agent_prompt: 'violet',
  mention: 'hemelblauw',
  politieke_input_imported: 'roze',
  placement_request: 'donkerblauw',
  emoji_reaction: 'roze',
};

// Activity
export interface Activity {
  id: string;
  event_type: string;
  actor_id?: string;
  actor_naam?: string;
  node_id?: string;
  task_id?: string;
  edge_id?: string;
  details?: Record<string, unknown>;
  created_at: string;
}

export interface ActivityFeedResponse {
  items: Activity[];
  total: number;
}

export const EVENT_TYPE_LABELS: Record<string, string> = {
  'node.created': 'Node aangemaakt',
  'node.updated': 'Node bewerkt',
  'node.deleted': 'Node verwijderd',
  'stakeholder.added': 'Betrokkene toegevoegd',
  'stakeholder.updated': 'Betrokkene rol gewijzigd',
  'stakeholder.removed': 'Betrokkene verwijderd',
  'node_tag.added': 'Tag toegevoegd aan node',
  'node_tag.removed': 'Tag verwijderd van node',
  'tag.created': 'Tag aangemaakt',
  'tag.updated': 'Tag bewerkt',
  'tag.deleted': 'Tag verwijderd',
  'task.created': 'Taak aangemaakt',
  'task.updated': 'Taak bewerkt',
  'task.deleted': 'Taak verwijderd',
  'edge.created': 'Relatie aangemaakt',
  'edge.updated': 'Relatie bewerkt',
  'edge.deleted': 'Relatie verwijderd',
  'person.created': 'Persoon aangemaakt',
  'person.updated': 'Persoon bewerkt',
  'person.deleted': 'Persoon verwijderd',
  'person.organisatie_added': 'Toegevoegd aan eenheid',
  'person.organisatie_updated': 'Eenheid-indeling bewerkt',
  'person.organisatie_removed': 'Verwijderd uit eenheid',
  'organisatie.created': 'Organisatie aangemaakt',
  'organisatie.updated': 'Organisatie bewerkt',
  'organisatie.deleted': 'Organisatie verwijderd',
  'parlementair.rejected': 'Parlementair item afgewezen',
  'parlementair.reviewed': 'Parlementair item beoordeeld',
  'parlementair.edge_approved': 'Parlementaire relatie goedgekeurd',
  'parlementair.edge_rejected': 'Parlementaire relatie afgewezen',
  'parlementair.edge_reset': 'Parlementaire relatie gereset',
  'parlementair.import_triggered': 'Parlementaire import gestart',
  'lead.created': 'Lead aangemaakt',
  'lead.updated': 'Lead bewerkt',
  'lead.deleted': 'Lead verwijderd',
  'lead.moved': 'Lead verplaatst',
  'lead.merged': 'Leads samengevoegd',
  'lead_contact.added': 'Externe contactpersoon toegevoegd aan lead',
  'lead_contact.removed': 'Externe contactpersoon verwijderd van lead',
  'lead_node.added': 'Node gekoppeld aan lead',
  'lead_node.removed': 'Node ontkoppeld van lead',
  'lead_tag.added': 'Tag toegevoegd aan lead',
  'lead_tag.removed': 'Tag verwijderd van lead',
  'lead_activity.added': 'Notitie toegevoegd aan lead',
  'lead_attachment.uploaded': 'Bijlage geüpload bij lead',
  'lead_attachment.deleted': 'Bijlage verwijderd bij lead',
  'initiatief.created': 'Initiatief aangemaakt',
  'initiatief.updated': 'Initiatief bewerkt',
  'initiatief.deleted': 'Initiatief verwijderd',
  'initiatief_member.added': 'Lid toegevoegd aan initiatief',
  'initiatief_member.removed': 'Lid verwijderd van initiatief',
  'initiatief_member.updated': 'Lidrol gewijzigd in initiatief',
  'initiatief_eenheid.added': 'Eenheid toegevoegd aan initiatief',
  'initiatief_eenheid.removed': 'Eenheid verwijderd van initiatief',
  'externe_organisatie.created': 'Externe organisatie aangemaakt',
  'externe_organisatie.updated': 'Externe organisatie bewerkt',
  'externe_organisatie.deleted': 'Externe organisatie verwijderd',
  'bijlage.uploaded': 'Bijlage geüpload',
  'bijlage.deleted': 'Bijlage verwijderd',
  'import.politieke_inputs': 'Politieke inputs geïmporteerd',
  'import.nodes': 'Nodes geïmporteerd',
  'import.edges': 'Relaties geïmporteerd',
  'opdracht.created': 'Opdracht aangemaakt',
  'opdracht.updated': 'Opdracht bewerkt',
  'opdracht.deleted': 'Opdracht verwijderd',
};

export const EVENT_TYPE_CATEGORY_LABELS: Record<string, string> = {
  node: 'Nodes',
  task: 'Taken',
  edge: 'Relaties',
  person: 'Personen',
  organisatie: 'Organisatie',
  tag: 'Tags',
  node_tag: 'Node-tags',
  stakeholder: 'Betrokkenen',
  parlementair: 'Parlementair',
  lead: 'Leads',
  lead_contact: 'Lead-contacten',
  lead_node: 'Lead-nodes',
  lead_tag: 'Lead-tags',
  lead_activity: 'Lead-activiteiten',
  lead_attachment: 'Lead-bijlagen',
  initiatief: 'Initiatieven',
  initiatief_member: 'Initiatief-leden',
  initiatief_eenheid: 'Initiatief-eenheden',
  externe_organisatie: 'Externe organisaties',
  bijlage: 'Bijlagen',
  import: 'Imports',
  opdracht: 'Opdrachten',
};

// Inbox
export interface InboxItem {
  id: string;
  type: string;
  /** Original notification type (e.g. "stakeholder_added") for display label */
  notification_type?: string;
  title: string;
  description?: string;
  source?: string;
  node_id?: string;
  task_id?: string;
  lead_id?: string;
  sender_name?: string;
  reply_count?: number;
  created_at: string;
  read: boolean;
}

export interface InboxResponse {
  items: InboxItem[];
  total: number;
  unread_count: number;
}

// Search
export type SearchResultType =
  | 'corpus_node'
  | 'task'
  | 'person'
  | 'organisatie_eenheid'
  | 'parlementair_item'
  | 'tag'
  | 'lead';

export const SEARCH_TYPE_PERMISSIONS: Record<SearchResultType, string> = {
  corpus_node: 'node:read',
  task: 'task:read',
  person: 'people:read',
  organisatie_eenheid: 'org:read',
  parlementair_item: 'node:read',
  tag: 'node:read',
  lead: 'lead:read',
};

export const SEARCH_RESULT_TYPE_LABELS: Record<SearchResultType, string> = {
  corpus_node: 'Beleidscorpus',
  task: 'Taak',
  person: 'Persoon',
  organisatie_eenheid: 'Organisatie',
  parlementair_item: 'Parlementair',
  tag: 'Tag',
  lead: 'Lead',
};

export const SEARCH_RESULT_TYPE_COLORS: Record<SearchResultType, EntityColor> = {
  corpus_node: 'lintblauw',
  task: 'geel',
  person: 'groen',
  organisatie_eenheid: 'paars',
  parlementair_item: 'roze',
  tag: 'hemelblauw',
  lead: 'oranje',
};

export interface SearchResult {
  id: string;
  result_type: SearchResultType;
  title: string;
  subtitle?: string;
  description?: string;
  score: number;
  highlights?: string[];
  url: string;
}

export interface SearchResponse {
  results: SearchResult[];
  total: number;
  query: string;
}

// Graph View
export interface GraphViewResponse {
  nodes: CorpusNode[];
  edges: Edge[];
}

// Tags
export interface Tag {
  id: string;
  name: string;
  parent_id?: string | null;
  description?: string | null;
  created_at: string;
  children?: Tag[];
}

export interface NodeTagResponse {
  id: string;
  tag: Tag;
  created_at: string;
}

// Parlementair Item
export type ParlementairItemType = 'motie' | 'kamervraag' | 'toezegging' | 'amendement' | 'commissiedebat' | 'schriftelijk_overleg' | 'interpellatie';
export type ParlementairItemStatus = 'pending' | 'imported' | 'reviewed' | 'rejected' | 'out_of_scope';
export type SuggestedEdgeStatus = 'pending' | 'approved' | 'rejected';

export const PARLEMENTAIR_TYPE_LABELS: Record<string, string> = {
  motie: 'Motie',
  kamervraag: 'Kamervraag',
  toezegging: 'Toezegging',
  amendement: 'Amendement',
  commissiedebat: 'Commissiedebat',
  schriftelijk_overleg: 'Schriftelijk Overleg',
  interpellatie: 'Interpellatie',
};

export const PARLEMENTAIR_TYPE_COLORS: Record<string, EntityColor> = {
  motie: 'roze',
  kamervraag: 'lintblauw',
  toezegging: 'geel',
  amendement: 'paars',
  commissiedebat: 'hemelblauw',
  schriftelijk_overleg: 'donkerblauw',
  interpellatie: 'rood',
};

export const ALL_PARLEMENTAIR_TYPES: ParlementairItemType[] = Object.keys(
  PARLEMENTAIR_TYPE_LABELS,
) as ParlementairItemType[];

export interface ParlementairItem {
  id: string;
  type: ParlementairItemType;
  zaak_id: string;
  zaak_nummer: string;
  titel: string;
  onderwerp: string;
  bron: string;
  datum?: string;
  status: ParlementairItemStatus;
  corpus_node_id?: string;
  indieners?: string[];
  document_tekst?: string;
  document_url?: string;
  llm_samenvatting?: string;
  matched_tags?: string[];
  deadline?: string;
  ministerie?: string;
  extra_data?: Record<string, unknown>;
  imported_at?: string;
  reviewed_at?: string;
  created_at: string;
  suggested_edges?: SuggestedEdge[];
}

export interface SuggestedEdge {
  id: string;
  parlementair_item_id: string;
  target_node_id: string;
  target_node?: CorpusNode;
  edge_type_id: string;
  confidence: number;
  reason?: string;
  status: SuggestedEdgeStatus;
  edge_id?: string;
  reviewed_at?: string;
  created_at: string;
}

export const PARLEMENTAIR_ITEM_STATUS_LABELS: Record<ParlementairItemStatus, string> = {
  pending: 'In wachtrij',
  imported: 'Geïmporteerd',
  reviewed: 'Beoordeeld',
  rejected: 'Afgewezen',
  out_of_scope: 'Buiten scope',
};

export const PARLEMENTAIR_ITEM_STATUS_COLORS: Record<ParlementairItemStatus, EntityColor> = {
  pending: 'geel',
  imported: 'lintblauw',
  reviewed: 'groen',
  rejected: 'coolgray',
  out_of_scope: 'coolgray',
};

// Access Requests
export type AccessRequestStatus = 'pending' | 'approved' | 'denied';

export interface AccessRequest {
  id: string;
  email: string;
  naam: string;
  status: AccessRequestStatus;
  requested_at: string;
  reviewed_at?: string | null;
  reviewed_by_id?: string | null;
  deny_reason?: string | null;
}

// Node sub-detail types (parlementair item, bron, bijlage)
export interface NodeParlementairItem {
  type: string;
  indieners: string[];
  document_url: string | null;
  zaak_nummer: string;
  bron: string;
  datum: string | null;
  deadline: string | null;
  ministerie: string | null;
}

export interface NodeBronDetail {
  type: string;
  auteur: string | null;
  publicatie_datum: string | null;
  url: string | null;
}

export interface BijlageInfo {
  id: string;
  bestandsnaam: string;
  content_type: string;
  bestandsgrootte: number;
  bestand_beschikbaar: boolean;
  created_at: string;
}

// LLM suggestion types
export interface TagSuggestionRequest {
  title: string;
  description?: string | null;
  node_type?: string;
}

export interface TagSuggestionResponse {
  matched_tags: string[];
  suggested_new_tags: string[];
  available: boolean;
}

export interface EdgeSuggestionItem {
  target_node_id: string;
  target_node_title: string;
  target_node_type: string;
  confidence: number;
  suggested_edge_type: string;
  reason: string;
}

// Gap detection (B3)
export interface GapItem {
  step_number: number;
  step_question: string;
  missing_types: string[];
  present_types: string[];
  has_stakeholders: boolean;
}

export interface GapAnalysisResponse {
  gaps: GapItem[];
  completed_count: number;
  total_steps: number;
  narrative: string;
  recommendations: string[];
  available: boolean;
}

export interface CorpusGapSummaryItem {
  dossier_id: string;
  dossier_title: string;
  completed_count: number;
  total_steps: number;
  has_stakeholders: boolean;
}

// Kompas guidance (A5)
export interface KompasGuidanceResponse {
  suggestions: EdgeSuggestionItem[];
  available: boolean;
}

// Similar nodes (A3)
export interface SimilarNodeItem {
  id: string;
  title: string;
  node_type: string;
  similarity: number;
}

export interface SimilarNodesResponse {
  items: SimilarNodeItem[];
}

// Mention types
export interface MentionReference {
  source_type: string;
  source_id: string;
  source_title: string;
}

// Edge Schema Rules
export interface EdgeSchemaRule {
  id: string;
  from_node_type: string;
  to_node_type: string;
  edge_type_id: string;
}

export interface EdgeSchemaRuleCreate {
  from_node_type: string;
  to_node_type: string;
  edge_type_id: string;
}

export interface ValidEdgeTypesResponse {
  edge_type_ids: string[];
  schema_active: boolean;
}

// Filter types
export interface EdgeFilters {
  from_node_id?: string;
  to_node_id?: string;
  edge_type_id?: string;
  node_id?: string;
}

export interface TaskFilters {
  status?: TaskStatus;
  priority?: TaskPriority;
  assignee_id?: string;
  node_id?: string;
  organisatie_eenheid_id?: string;
  opdracht_id?: string;
  include_children?: boolean;
}

export interface ActivityFeedParams {
  [key: string]: string | number | boolean | undefined;
  skip?: number;
  limit?: number;
  event_type?: string;
  actor_id?: string;
}

export interface ParlementairItemFilters {
  status?: string;
  bron?: string;
  type?: string;
  search?: string;
}

// Parlementair review types
export interface ReprocessResult {
  total: number;
  matched: number;
  out_of_scope: number;
  skipped: number;
  error?: string;
}

export interface CompleteReviewData {
  eigenaar_id: string;
  tasks?: { title: string; description?: string; assignee_id?: string; deadline?: string }[];
}

// Notification types
export interface ReactionSummary {
  emoji: string;
  count: number;
  sender_names: string[];
  reacted_by_me: boolean;
}

export interface Notification {
  id: string;
  person_id: string;
  sender_id?: string;
  sender_name?: string;
  type: string;
  title: string;
  message?: string;
  is_read: boolean;
  related_node_id?: string;
  related_task_id?: string;
  related_lead_id?: string;
  parent_id?: string;
  thread_id?: string;
  reply_count: number;
  created_at: string;
  last_activity_at?: string;
  last_message?: string;
  reactions: ReactionSummary[];
}

export interface UnreadCountResponse {
  count: number;
}

export interface DashboardStats {
  corpus_node_count: number;
  open_task_count: number;
  overdue_task_count: number;
  active_opdracht_budget: number;
}

// Import/Export types
export interface DatabaseBackupInfo {
  exported_at: string;
  alembic_revision: string;
  format_version: number;
  encrypted: boolean;
}

export interface DatabaseRestoreResult {
  success: boolean;
  tables_restored: number;
  alembic_revision_from: string;
  alembic_revision_to: string;
  migrations_applied: number;
  message: string;
}

export interface DatabaseResetResult {
  success: boolean;
  tables_cleared: number;
  admin_persons_created: number;
  message: string;
}

// WebAuthn types
export interface WebAuthnCredential {
  id: string;
  label: string;
  created_at: string;
  last_used_at: string | null;
}

// Opdracht
export enum OpdrachtType {
  OPDRACHT = 'opdracht',
  SUBSIDIE = 'subsidie',
}

export const OPDRACHT_TYPE_LABELS: Record<OpdrachtType, string> = {
  [OpdrachtType.OPDRACHT]: 'Opdracht',
  [OpdrachtType.SUBSIDIE]: 'Subsidie',
};

export const OPDRACHT_TYPE_COLORS: Record<OpdrachtType, EntityColor> = {
  [OpdrachtType.OPDRACHT]: 'lintblauw',
  [OpdrachtType.SUBSIDIE]: 'groen',
};

export enum OpdrachtStatus {
  CONCEPT = 'concept',
  ACTIEF = 'actief',
  AFGEROND = 'afgerond',
  VERANTWOORD = 'verantwoord',
  GEANNULEERD = 'geannuleerd',
}

export const OPDRACHT_STATUS_LABELS: Record<OpdrachtStatus, string> = {
  [OpdrachtStatus.CONCEPT]: 'Concept',
  [OpdrachtStatus.ACTIEF]: 'Actief',
  [OpdrachtStatus.AFGEROND]: 'Afgerond',
  [OpdrachtStatus.VERANTWOORD]: 'Verantwoord',
  [OpdrachtStatus.GEANNULEERD]: 'Geannuleerd',
};

export const OPDRACHT_STATUS_COLORS: Record<OpdrachtStatus, EntityColor> = {
  [OpdrachtStatus.CONCEPT]: 'donkerblauw',
  [OpdrachtStatus.ACTIEF]: 'lintblauw',
  [OpdrachtStatus.AFGEROND]: 'groen',
  [OpdrachtStatus.VERANTWOORD]: 'mosgroen',
  [OpdrachtStatus.GEANNULEERD]: 'coolgray',
};

export enum Kostensoort {
  INVESTERING = 'investering',
  EXPLOITATIE = 'exploitatie',
  GEMENGD = 'gemengd',
}

export const KOSTENSOORT_LABELS: Record<Kostensoort, string> = {
  [Kostensoort.INVESTERING]: 'Investering',
  [Kostensoort.EXPLOITATIE]: 'Exploitatie',
  [Kostensoort.GEMENGD]: 'Gemengd',
};

export interface OpdrachtNodeResponse {
  id: string;
  opdracht_id: string;
  node_id: string;
  relatie_type: string;
  node_title?: string | null;
  node_type?: string | null;
}

export interface OpdrachtNodeCreate {
  node_id: string;
  relatie_type?: string;
}

export type SyncStatus = 'synced' | 'pending_push' | 'pending_pull' | 'conflict' | 'error';

export const SYNC_STATUS_LABELS: Record<SyncStatus, string> = {
  synced: 'Gesynchroniseerd',
  pending_push: 'Wacht op push',
  pending_pull: 'Wacht op pull',
  conflict: 'Conflict',
  error: 'Fout',
};

export type FccTrafficLight = 'green' | 'orange' | 'red';

/**
 * A traffic light is semantic, so these are design-system color tokens rather
 * than class names. The dot paints from the value directly, so anything that is
 * not a real custom property renders as no color at all.
 */
export const FCC_TRAFFIC_LIGHT_COLORS: Record<FccTrafficLight, string> = {
  green: 'var(--primitives-color-groen-500)',
  orange: 'var(--primitives-color-oranje-500)',
  red: 'var(--primitives-color-rood-500)',
};

export const FCC_TRAFFIC_LIGHT_FIELDS: { key: string; label: string }[] = [
  { key: 'Status_Planning_2', label: 'Planning' },
  { key: 'Status_Budget', label: 'Budget' },
  { key: 'Status_Risico_s', label: "Risico's" },
  { key: 'Status_Doelrealisatie', label: 'Doelrealisatie' },
];

export interface OpdrachtMember {
  opdracht_id: string;
  person_id: string;
  person_naam: string;
  rol: string;
  source: 'manual' | 'ai';
  ai_confidence: number | null;
  ai_reason: string | null;
  created_at: string;
}

export interface OpdrachtEenheid {
  opdracht_id: string;
  eenheid_id: string;
  eenheid_naam: string;
  rol: string;
  source: 'manual' | 'ai';
  ai_confidence: number | null;
  ai_reason: string | null;
  created_at: string;
}

export const OPDRACHT_CONTACT_ROL_LABELS: Record<string, string> = {
  betrokken: 'Betrokken',
  contactpersoon: 'Contactpersoon',
  eigenaar: 'Eigenaar',
};

export interface Opdracht {
  id: string;
  type: string;
  titel: string;
  beschrijving?: string | null;
  begrotingsjaar: number;
  budget?: number | null;
  gerealiseerd?: number | null;
  kostensoort?: string | null;
  volgend_jaar_benodigd?: number | null;
  volgend_jaar_aangevraagd?: number | null;
  instrument_id?: string | null;
  instrument?: { id: string; title: string; node_type: string } | null;
  opdrachtnemer_eenheid_id?: string | null;
  opdrachtnemer?: OrganisatieEenheidSummary | null;
  opdrachtgever_id?: string | null;
  opdrachtgever?: { id: string; naam: string } | null;
  verantwoordelijke_id?: string | null;
  verantwoordelijke?: { id: string; naam: string } | null;
  subsidieregeling?: string | null;
  beschikking_nummer?: string | null;
  status: string;
  referentie?: string | null;
  startdatum?: string | null;
  einddatum?: string | null;
  // FCC sync fields
  fcc_id?: string | null;
  sync_status?: SyncStatus | null;
  sync_direction?: string | null;
  last_synced_at?: string | null;
  fcc_funnelfase?: string | null;
  fcc_afdeling?: string | null;
  fcc_portfolio?: string | null;
  fcc_labels?: string | null;
  fcc_raw_data?: Record<string, unknown> | null;
  node_koppelingen?: OpdrachtNodeResponse[];
  members?: OpdrachtMember[];
  eenheden?: OpdrachtEenheid[];
  created_at: string;
  updated_at?: string | null;
}

export interface FccSyncTriggerResponse {
  pulled: number;
  pushed: number;
}

export interface FccSchemaResponse {
  entity_sets: Record<string, string[]>;
}

export interface OpdrachtCreate {
  type: OpdrachtType;
  titel: string;
  beschrijving?: string | null;
  begrotingsjaar: number;
  budget?: number | null;
  gerealiseerd?: number | null;
  kostensoort?: Kostensoort | null;
  volgend_jaar_benodigd?: number | null;
  volgend_jaar_aangevraagd?: number | null;
  instrument_id: string;
  opdrachtnemer_eenheid_id?: string | null;
  opdrachtgever_id?: string | null;
  verantwoordelijke_id?: string | null;
  subsidieregeling?: string | null;
  beschikking_nummer?: string | null;
  status?: OpdrachtStatus;
  referentie?: string | null;
  startdatum?: string | null;
  einddatum?: string | null;
  node_koppelingen?: OpdrachtNodeCreate[];
}

export interface OpdrachtUpdate {
  type?: OpdrachtType;
  titel?: string;
  beschrijving?: string | null;
  begrotingsjaar?: number;
  budget?: number | null;
  gerealiseerd?: number | null;
  kostensoort?: Kostensoort | null;
  volgend_jaar_benodigd?: number | null;
  volgend_jaar_aangevraagd?: number | null;
  instrument_id?: string;
  opdrachtnemer_eenheid_id?: string | null;
  opdrachtgever_id?: string | null;
  verantwoordelijke_id?: string | null;
  subsidieregeling?: string | null;
  beschikking_nummer?: string | null;
  status?: OpdrachtStatus;
  referentie?: string | null;
  startdatum?: string | null;
  einddatum?: string | null;
}

export interface OpdrachtFilters {
  begrotingsjaar?: number;
  type?: string;
  status?: string;
  instrument_id?: string;
  opdrachtnemer_eenheid_id?: string;
  opdrachtgever_id?: string;
  verantwoordelijke_id?: string;
}

// Financieel Overzicht
export interface FinancieelJaar {
  begrotingsjaar: number;
  budget: number;
  gerealiseerd: number;
  volgend_jaar_benodigd: number;
  volgend_jaar_aangevraagd: number;
  opdracht_count: number;
}

export interface OpdrachtenSummary {
  count: number;
  totaal_budget: number;
  totaal_gerealiseerd: number;
  uitnutting_percentage?: number | null;
}

export interface FinancieelOverzicht {
  node_id: string;
  node_title: string;
  node_type: string;
  totaal_budget: number;
  totaal_gerealiseerd: number;
  uitnutting_percentage?: number | null;
  per_jaar: FinancieelJaar[];
}

// Lead Stage enum and labels.
// De stage-waarde van een lead is sinds de per-initiatief-kolommen-feature
// geen vaste enum meer; eigenaren kunnen kolommen toevoegen/verwijderen via
// `LeadColumn`. Deze enum + de DEFAULT_LEAD_COLUMNS hieronder dienen als
// fallback voor orphan-leads (geen initiatief) en als loading-placeholder.
export enum LeadStage {
  INBOX = 'inbox',
  VERKENNEN = 'verkennen',
  EERSTE_GESPREK = 'eerste_gesprek',
  INTERNE_CHECK = 'interne_check',
  FOLLOW_UP = 'follow_up',
  IN_THE_POCKET = 'in_the_pocket',
  KOELKAST = 'koelkast',
}

export interface LeadColumn {
  id: string;
  initiatief_id: string;
  name: string;
  slug: string;
  sort_order: number;
  color: string;
  is_active_stage: boolean;
  is_public_visible: boolean;
  lead_count: number;
  created_at: string;
  updated_at: string | null;
}

// Record<string, ...> ipv Record<LeadStage, ...> zodat call-sites die met
// een willekeurige slug-string indexeren (per-initiatief custom kolommen)
// geen TS-fout krijgen. Onbekende slugs returnen `undefined` — gebruik
// `?? slug` als fallback om de raw slug te tonen.
export const LEAD_STAGE_LABELS: Record<string, string> = {
  [LeadStage.INBOX]: 'Inbox',
  [LeadStage.VERKENNEN]: 'Verkennen',
  [LeadStage.EERSTE_GESPREK]: 'Eerste gesprek',
  [LeadStage.INTERNE_CHECK]: 'Interne check',
  [LeadStage.FOLLOW_UP]: 'Follow-up',
  [LeadStage.IN_THE_POCKET]: 'In the pocket',
  [LeadStage.KOELKAST]: 'Koelkast',
};

/**
 * Default column color per lead stage, as an nldd-tag color name.
 *
 * Mirrors the defaults in `backend/bouwmeester/schema/lead_column.py`, which
 * validates `LeadColumn.color` against the same closed set.
 * `leadColumnTagColor()` rejects anything outside the set, so a column with an
 * unknown color name renders grey.
 */
const LEAD_STAGE_COLORS: Record<string, string> = {
  [LeadStage.INBOX]: 'lintblauw',
  [LeadStage.VERKENNEN]: 'hemelblauw',
  [LeadStage.EERSTE_GESPREK]: 'geel',
  [LeadStage.INTERNE_CHECK]: 'oranje',
  [LeadStage.FOLLOW_UP]: 'paars',
  [LeadStage.IN_THE_POCKET]: 'success',
  [LeadStage.KOELKAST]: 'neutral',
};

export const LEAD_STAGE_ORDER: LeadStage[] = [
  LeadStage.INBOX,
  LeadStage.VERKENNEN,
  LeadStage.EERSTE_GESPREK,
  LeadStage.INTERNE_CHECK,
  LeadStage.FOLLOW_UP,
  LeadStage.IN_THE_POCKET,
  LeadStage.KOELKAST,
];

// Fallback-kolommen voor leads zonder initiatief en voor de loading-flow van
// `useLeadColumns`. Spiegelt de defaults uit `backend/schema/lead_column.py`.
export const DEFAULT_LEAD_COLUMNS: LeadColumn[] = LEAD_STAGE_ORDER.map(
  (slug, idx) => ({
    id: `default-${slug}`,
    initiatief_id: '',
    name: LEAD_STAGE_LABELS[slug],
    slug,
    sort_order: idx,
    color: LEAD_STAGE_COLORS[slug],
    is_active_stage: ![
      LeadStage.INBOX,
      LeadStage.IN_THE_POCKET,
      LeadStage.KOELKAST,
    ].includes(slug),
    is_public_visible: [
      LeadStage.EERSTE_GESPREK,
      LeadStage.INTERNE_CHECK,
      LeadStage.FOLLOW_UP,
      LeadStage.IN_THE_POCKET,
    ].includes(slug),
    lead_count: 0,
    created_at: new Date(0).toISOString(),
    updated_at: null,
  }),
);

export enum LeadActivityType {
  NOTE = 'note',
  STAGE_CHANGE = 'stage_change',
  MEETING = 'meeting',
  CALL = 'call',
  EMAIL = 'email',
  EVALUATIE = 'evaluatie',
}

export const LEAD_ACTIVITY_TYPE_LABELS: Record<LeadActivityType, string> = {
  [LeadActivityType.NOTE]: 'Notitie',
  [LeadActivityType.STAGE_CHANGE]: 'Stage wijziging',
  [LeadActivityType.MEETING]: 'Meeting',
  [LeadActivityType.CALL]: 'Telefoongesprek',
  [LeadActivityType.EMAIL]: 'E-mail',
  [LeadActivityType.EVALUATIE]: 'Evaluatie',
};

export interface LeadAssigneeSummary {
  id: string;
  naam: string;
}

export interface LeadInitiatiefSummary {
  id: string;
  naam: string;
  kleur: string | null;
}

export interface OrganisatieEenheidSummary {
  id: string;
  naam: string;
  type: string | null;
  afkorting?: string | null;
}

export interface LeadAttachment {
  id: string;
  lead_id: string;
  soort: 'file' | 'link';
  bestandsnaam: string | null;
  content_type: string | null;
  bestandsgrootte: number | null;
  url: string | null;
  source: 'upload' | 'mattermost';
  source_ref: string | null;
  bestand_beschikbaar: boolean;
  created_at: string;
}

export interface LeadContact {
  id: string;
  person_id: string;
  person_naam: string;
  person_functie?: string | null;
  person_expertise?: string | null;
  rol: string;
  created_at: string;
}

export interface LeadNode {
  id: string;
  node_id: string;
  node_title: string;
  node_type: string;
  created_at: string;
}

export interface LeadActivity {
  id: string;
  lead_id: string;
  author_id: string | null;
  author_naam: string | null;
  content: string;
  activity_type: LeadActivityType;
  metadata_: Record<string, unknown>;
  uitkomst: string | null;
  vervolgacties: string | null;
  created_at: string;
}

export interface Lead {
  id: string;
  title: string;
  description: string | null;
  organization: string | null;
  organisatie_eenheid_id: string | null;
  organisatie_eenheid: OrganisatieEenheidSummary | null;
  stage: string;
  assignee_id: string | null;
  assignee: LeadAssigneeSummary | null;
  brought_by_id: string | null;
  brought_by: LeadAssigneeSummary | null;
  initiatief_id: string | null;
  initiatief: LeadInitiatiefSummary | null;
  next_action: string | null;
  next_action_date: string | null;
  tags: string[];
  sort_order: number;
  raw_intake_text: string | null;
  engagement_type: EngagementType | null;
  score_strategisch: number | null;
  score_politiek: number | null;
  score_positie: number | null;
  public_visible: boolean;
  public_title: string | null;
  public_summary: string | null;
  attachment_count: number;
  contact_names: string[];
  created_at: string;
  updated_at: string | null;
}

export type GitHubLinkType =
  | "branch"
  | "pull_request"
  | "issue"
  | "repo"
  | "workflow_run"
  | "other";

export interface LeadGitHubLink {
  id: string;
  scope_type: string;
  scope_id: string;
  url: string;
  link_type: GitHubLinkType;
  owner: string;
  repo: string;
  ref: string | null;
  title: string | null;
  created_by_id: string | null;
  created_at: string;
}

export interface LeadDetail extends Lead {
  activities: LeadActivity[];
  attachments: LeadAttachment[];
  contacts: LeadContact[];
  linked_nodes: LeadNode[];
  github_links: LeadGitHubLink[];
}

export interface LeadCreate {
  title: string;
  description?: string | null;
  organization?: string | null;
  organisatie_eenheid_id?: string | null;
  stage?: string;
  assignee_id?: string | null;
  brought_by_id?: string | null;
  next_action?: string | null;
  next_action_date?: string | null;
  raw_intake_text?: string | null;
  initiatief_id?: string | null;
  engagement_type?: EngagementType | null;
  score_strategisch?: number | null;
  score_politiek?: number | null;
  score_positie?: number | null;
  public_visible?: boolean | null;
  public_title?: string | null;
  public_summary?: string | null;
  created_at?: string | null;
}

export interface LeadUpdate {
  title?: string;
  description?: string | null;
  organization?: string | null;
  organisatie_eenheid_id?: string | null;
  stage?: string;
  assignee_id?: string | null;
  brought_by_id?: string | null;
  next_action?: string | null;
  next_action_date?: string | null;
  raw_intake_text?: string | null;
  initiatief_id?: string | null;
  engagement_type?: EngagementType | null;
  score_strategisch?: number | null;
  score_politiek?: number | null;
  score_positie?: number | null;
  public_visible?: boolean | null;
  public_title?: string | null;
  public_summary?: string | null;
}

export interface LeadActivityCreate {
  content: string;
  activity_type?: LeadActivityType;
  uitkomst?: string | null;
  vervolgacties?: string | null;
}

export interface LeadMetrics {
  total: number;
  by_stage: Record<string, number>;
  stale_count: number;
}

export interface LeadFilters {
  stage?: string;
  tag?: string;
  assignee_id?: string;
  date_from?: string;
  date_to?: string;
  next_action_filter?: string;  // "overdue" | "today" | "this_week"
  sort_by?: string;  // "created_at" | "updated_at" | "next_action_date" | "stage"
  initiatief_id?: string;
}

export interface LeadTimelineEvent {
  id: string;
  lead_id: string;
  lead_title: string;
  event_type: 'created' | 'stage_change' | 'note' | 'meeting' | 'call' | 'email';
  timestamp: string;
  actor_naam: string | null;
  content: string | null;
  from_stage: string | null;
  to_stage: string | null;
  organization: string | null;
  stage: string;
  assignee_naam: string | null;
}

export interface LeadTimelineResponse {
  events: LeadTimelineEvent[];
  total: number;
  earliest: string | null;
  latest: string | null;
}

// ---------------------------------------------------------------------------
// Initiatief
// ---------------------------------------------------------------------------

export interface Initiatief {
  id: string;
  naam: string;
  slug: string | null;
  beschrijving: string | null;
  kleur: string | null;
  funnel_enabled: boolean;
  public_page_enabled: boolean;
  score_strategisch_label: string | null;
  score_politiek_label: string | null;
  score_positie_label: string | null;
  created_by_id: string | null;
  created_at: string;
  updated_at: string | null;
}

/** An initiatief as the overview lists it, with what is in it. */
export interface InitiatiefListItem extends Initiatief {
  lead_count: number;
  /** Leads in a column marked as an active stage. */
  active_lead_count: number;
  member_count: number;
  last_published_at: string | null;
}

export interface InitiatiefCreate {
  naam: string;
  beschrijving?: string | null;
  kleur?: string | null;
}

export interface InitiatiefUpdate {
  naam?: string;
  beschrijving?: string | null;
  kleur?: string | null;
}

export interface InitiatiefSettingsUpdate {
  slug?: string | null;
  funnel_enabled?: boolean;
  public_page_enabled?: boolean;
  score_strategisch_label?: string | null;
  score_politiek_label?: string | null;
  score_positie_label?: string | null;
}

export interface InitiatiefUpdatePost {
  id: string;
  initiatief_id: string;
  titel: string;
  body: string | null;
  published_at: string | null;
  published_by_id: string | null;
  published_by_naam: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface InitiatiefUpdatePostCreate {
  titel: string;
  body?: string | null;
  publish?: boolean;
}

export interface InitiatiefUpdatePostEdit {
  titel?: string;
  body?: string | null;
}

export interface PublicInitiatiefUpdate {
  titel: string;
  body: string | null;
  published_at: string;
  published_by_naam: string | null;
}

export interface LeadUpdatePost {
  id: string;
  lead_id: string;
  titel: string;
  body_internal: string | null;
  body_public: string | null;
  mail_subject: string | null;
  mail_to: string[] | null;
  mail_cc: string[] | null;
  published_at: string | null;
  published_by_id: string | null;
  published_by_naam: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface LeadUpdatePostCreate {
  titel: string;
  body_internal?: string | null;
  body_public?: string | null;
  mail_subject?: string | null;
  mail_to?: string[] | null;
  mail_cc?: string[] | null;
  source_raw_text?: string | null;
  publish?: boolean;
}

export interface LeadUpdatePostEdit {
  titel?: string;
  body_internal?: string | null;
  body_public?: string | null;
  mail_subject?: string | null;
  mail_to?: string[] | null;
  mail_cc?: string[] | null;
}

export interface LeadUpdateExtractResult {
  titel: string | null;
  body_internal: string | null;
  body_public: string | null;
  mail_subject: string | null;
  suggested_to: string[];
  suggested_cc: string[];
}

export interface PublicLeadUpdate {
  titel: string;
  body_public: string | null;
  published_at: string;
  published_by_naam: string | null;
}

export interface PublicCasus {
  titel: string;
  samenvatting: string | null;
  updates: PublicLeadUpdate[];
}

export interface PublicInitiatief {
  naam: string;
  slug: string;
  beschrijving: string | null;
  kleur: string | null;
  updates: PublicInitiatiefUpdate[];
  casussen: PublicCasus[];
}

export type EngagementType =
  | 'intern_oppakken'
  | 'voorbereiden_eigen_team'
  | 'betrokken_houden'
  | 'verkenning'
  | 'nog_te_bepalen';

export const ENGAGEMENT_TYPE_LABELS: Record<EngagementType, string> = {
  intern_oppakken: 'Intern oppakken',
  voorbereiden_eigen_team: 'Voorbereiden eigen team',
  betrokken_houden: 'Betrokken houden',
  verkenning: 'Verkenning (spike)',
  nog_te_bepalen: 'Nog te bepalen',
};

export type StakeholderHouding =
  | 'tegen'
  | 'kritisch'
  | 'neutraal'
  | 'welwillend'
  | 'voorstander';

export const STAKEHOLDER_HOUDING_LABELS: Record<StakeholderHouding, string> = {
  tegen: 'Tegen',
  kritisch: 'Kritisch',
  neutraal: 'Neutraal',
  welwillend: 'Welwillend',
  voorstander: 'Voorstander',
};

export type StakeholderScopeType = 'corpus_node' | 'initiatief';

export interface StakeholderAssessment {
  id: string;
  person_id: string;
  person_naam: string;
  scope_type: StakeholderScopeType;
  scope_id: string;
  belang: number | null;
  houding: StakeholderHouding | null;
  invloed: number | null;
  notitie: string | null;
  assessed_by_id: string | null;
  assessed_by_naam: string | null;
  assessed_at: string | null;
  created_at: string;
  updated_at: string | null;
}

export interface StakeholderAssessmentCreate {
  person_id: string;
  scope_type: StakeholderScopeType;
  scope_id: string;
  belang?: number | null;
  houding?: StakeholderHouding | null;
  invloed?: number | null;
  notitie?: string | null;
}

export interface StakeholderAssessmentUpdate {
  belang?: number | null;
  houding?: StakeholderHouding | null;
  invloed?: number | null;
  notitie?: string | null;
}

export interface InitiatiefMember {
  initiatief_id: string;
  person_id: string;
  person_naam: string;
  rol: string;
  created_at: string;
}

export interface InitiatiefEenheid {
  initiatief_id: string;
  eenheid_id: string;
  eenheid_naam: string;
  rol: string;
  created_at: string;
}

export interface InitiatiefDetail extends Initiatief {
  members: InitiatiefMember[];
  eenheden: InitiatiefEenheid[];
  access_level: 'eigenaar' | 'contributor' | 'viewer' | null;
}

/**
 * The closed set `Initiatief.kleur` may hold, mirrored by hand from backend
 * `schema.initiatief.INITIATIEF_COLORS`. These are nldd color names, not CSS:
 * `nldd-tag` and `nldd-icon` paint their own accessible fill and content color
 * per name. A subset of the 23 the backend accepts, so the picker stays a
 * choice rather than a catalogue; a stored value outside it still renders,
 * since the helpers in `components/initiatieven/initiatiefColors.ts` validate
 * against the full backend set.
 */
export const INITIATIEF_COLORS = [
  'lintblauw',
  'hemelblauw',
  'groen',
  'mosgroen',
  'geel',
  'oranje',
  'rood',
  'robijnrood',
  'paars',
  'violet',
  'roze',
  'bruin',
] as const;

export interface LeadParseResult {
  title: string | null;
  organization: string | null;
  description: string | null;
  contact_name: string | null;
  contact_email: string | null;
  contact_phone: string | null;
  original_date: string | null;
  suggested_tags: string[];
  addressed_to: string | null;
}

// Community Graph types (used by LeadGraphView / CommunityGraph)
export interface CommunityGraphNode {
  // prefixed: "lead-xxx", "person-xxx", "oe-xxx", "node-xxx", "swv-xxx"
  id: string;
  node_type:
    | 'lead'
    | 'person'
    | 'organisation'
    | 'corpus_node'
    | 'samenwerkingsverband';
  label: string;
  stage?: string | null;
  initiatief_id?: string | null;
  functie?: string | null;
  expertise?: string | null;
  person_role?: 'intern' | 'extern' | null;
  org_type?: string | null;
  org_role?: 'intern' | 'extern' | null;
  samenwerkingsverband_type?: string | null;
  corpus_node_type?: string | null;
}

export interface CommunityGraphEdge {
  id: string;
  source: string;
  target: string;
  edge_type: string;
  label?: string | null;
}

export interface CommunityGraphResponse {
  nodes: CommunityGraphNode[];
  edges: CommunityGraphEdge[];
}

// ---------------------------------------------------------------------------
// Samenwerkingsverband (programma | werkgroep | stuurgroep | taskforce | ...)
// ---------------------------------------------------------------------------

export type SamenwerkingsverbandType =
  | 'programma'
  | 'werkgroep'
  | 'opschalingsticket'
  | 'ketenproject'
  | 'stuurgroep'
  | 'taskforce'
  | 'innovatiebudget'
  | 'community_of_practice'
  | 'pilot'
  | 'convenant'
  | 'commissie'
  | 'raad';

export const SAMENWERKINGSVERBAND_TYPE_LABELS: Record<string, string> = {
  programma: 'Programma',
  werkgroep: 'Werkgroep',
  opschalingsticket: 'Opschalingsticket',
  ketenproject: 'Ketenproject',
  stuurgroep: 'Stuurgroep',
  taskforce: 'Taskforce',
  innovatiebudget: 'Innovatiebudget',
  community_of_practice: 'Community of Practice',
  pilot: 'Pilot',
  convenant: 'Convenant',
  commissie: 'Commissie',
  raad: 'Raad',
};

export const SAMENWERKINGSVERBAND_TYPE_BADGE_COLORS: Record<string, EntityColor> = {
  programma: 'paars',
  werkgroep: 'hemelblauw',
  opschalingsticket: 'geel',
  ketenproject: 'mosgroen',
  stuurgroep: 'violet',
  taskforce: 'rood',
  innovatiebudget: 'groen',
  community_of_practice: 'lintblauw',
  pilot: 'oranje',
  convenant: 'donkerblauw',
  commissie: 'roze',
  raad: 'coolgray',
};

export const SAMENWERKINGSVERBAND_TYPE_OPTIONS: { value: string; label: string }[] =
  Object.entries(SAMENWERKINGSVERBAND_TYPE_LABELS).map(([value, label]) => ({
    value,
    label,
  }));

export interface Samenwerkingsverband {
  id: string;
  naam: string;
  type: string;
  beschrijving?: string | null;
  start_datum?: string | null;
  eind_datum?: string | null;
  created_by_id?: string | null;
  created_at: string;
  updated_at?: string | null;
  aantal_leden: number;
}

export interface SamenwerkingsverbandCreate {
  naam: string;
  type: string;
  beschrijving?: string;
  start_datum?: string | null;
  eind_datum?: string | null;
}

export interface SamenwerkingsverbandUpdate {
  naam?: string;
  type?: string;
  beschrijving?: string | null;
  start_datum?: string | null;
  eind_datum?: string | null;
}

export interface SamenwerkingsverbandLid {
  id: string;
  samenwerkingsverband_id: string;
  person_id: string;
  person_naam: string;
  person_functie?: string | null;
  person_expertise?: string | null;
  rol?: string | null;
  start_datum: string;
  eind_datum?: string | null;
  created_at: string;
}

export interface SamenwerkingsverbandLidCreate {
  person_id: string;
  rol?: string | null;
  start_datum: string;
}

export interface SamenwerkingsverbandLidUpdate {
  rol?: string | null;
  start_datum?: string | null;
  eind_datum?: string | null;
}

export interface SamenwerkingsverbandDetail extends Samenwerkingsverband {
  leden: SamenwerkingsverbandLid[];
}

export interface PersoonLidmaatschap {
  id: string;
  samenwerkingsverband_id: string;
  samenwerkingsverband_naam: string;
  samenwerkingsverband_type: string;
  rol?: string | null;
  start_datum: string;
  eind_datum?: string | null;
}
