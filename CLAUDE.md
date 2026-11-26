# Bouwmeester

Policy corpus management tool for the Dutch government (BZK). Manages organisational structure, people, policy dossiers, tasks, and their relationships.

## Quick start

```bash
just reset-db    # Nuke DB, migrate, seed, start all services
just up          # Start services (if DB already exists)
just dev         # Start with rebuild (foreground, shows logs)
```

App runs at http://localhost:5173, API at http://localhost:8000.

## Just commands

Run `just` to see all available commands. Key ones:

| Command | What it does |
|---------|-------------|
| `just up` | Start all services in background |
| `just down` | Stop services (keeps data) |
| `just nuke` | Stop + delete all data |
| `just reset-db` | Full reset: nuke, migrate, seed, start |
| `just migrate` | Run Alembic migrations |
| `just seed` | Seed test data |
| `just restart-backend` | Restart backend after code changes |
| `just typecheck` | Frontend TypeScript check |
| `just lint` | Backend lint (ruff) |
| `just logs` | Follow all service logs |
| `zad logs` | Follow Zad deployment logs (production) |
| `just db-shell` | Open psql shell |
| `just worker-logs` | Follow worker service logs |
| `just import-parlementair` | Manually trigger parlementair import via API |
| `just decrypt-seed` | Decrypt seed person data (.age → .json) |
| `just encrypt-seed` | Encrypt seed person data (.json → .age) |

## Architecture

- **Backend**: FastAPI + SQLAlchemy 2.0 async + Alembic + PostgreSQL (asyncpg)
- **Frontend**: React + TypeScript + React Query + @nldd/design-system + Vite
- **Infra**: Docker Compose (dev)
- **Python**: Use `uv` for ALL python operations (never pip/poetry)

## Project structure

```
backend/
  bouwmeester/
    api/routes/       # FastAPI routers (one file per domain)
    models/           # SQLAlchemy 2.0 models
    schema/           # Pydantic v2 schemas
    repositories/     # Database access (no service layer for simple CRUD)
    services/         # Business logic (only where needed)
    migrations/       # Alembic migrations
  scripts/seed.py     # Test data seed script
frontend/
  src/
    api/              # API client functions (apiGet/apiPost/apiPut/apiDelete)
    components/       # React components by domain
    hooks/            # React Query hooks
    pages/            # Page components (route targets)
    types/            # TypeScript types and constants
```

## Backend patterns

- **Models**: `Mapped[type]`, `mapped_column()`, UUID PKs with `server_default=text("gen_random_uuid()")`
- **Schemas**: Pydantic v2, `ConfigDict(from_attributes=True)`, pattern: Base/Create/Update/Response
- **Routes**: Direct repo usage with `Depends(get_db)`, no service layer for simple CRUD
- **Registries**: New models → `models/__init__.py`, new schemas → `schema/__init__.py`, new routers → `api/routes/__init__.py`

### Adding a new model

1. Create model in `models/new_thing.py`
2. Import in `models/__init__.py`
3. Create schemas in `schema/new_thing.py` (Base, Create, Update, Response)
4. Import in `schema/__init__.py`
5. Create repository in `repositories/new_thing.py`
6. Create router in `api/routes/new_thing.py`
7. Register router in `api/routes/__init__.py`
8. Generate migration: `just migration "add new thing"`

## Frontend patterns

- **Path alias**: `@/` maps to `src/`
- **API helpers**: `apiGet`, `apiPost`, `apiPut`, `apiDelete` in `api/client.ts`
- **Hooks**: React Query `useQuery`/`useMutation` with `queryKey` invalidation
- **Dropdowns**: `CreatableSelect` when the user may add an option inline, otherwise `Select` (`nldd-dropdown` around a native `<select>`, with `size` and `width`)
- **Rich text**: ALL description/beschrijving fields MUST use `RichTextFormField` (edit) and `RichTextDisplay` (view) — never use plain `<textarea>` for descriptions
- **Layout**: `Header.tsx` renders page title from `pageTitles` map — pages should NOT have their own `<h1>`
- **Sidebar**: Nav items defined in `components/layout/Sidebar.tsx`
- **Route definitions**: `App.tsx`

### Design system (`@nldd/design-system`)

- **Elements**: use `nldd-*` elements directly; every one the app renders is imported in `components/nldd/register.ts` (`register.test.ts` fails otherwise). After a package upgrade run `node scripts/generate-nldd-types.mjs` to regenerate `nldd-elements.d.ts`.
- **Events**: never `onClick`/`onChange` on an `nldd-*` element; bridge with `useNlddEvent` from `components/nldd/events.ts`, or use a wrapper below.
- **Buttons**: `NlddButton` (label in `text`, not children; `compactBelowSm` shows only the icon on phones) and `NlddIconButton`. A raw `<button>` only for operable text, with `className="plain-button"`.
- **Clickable list rows**: `NlddListItemButton` (action) or `NlddListItemLink` (route), both in `components/nldd/NlddLink.tsx`.
- **Icons**: `Icon` takes nldd icon names only; `scripts/validate-nldd-markup.mjs` rejects unknown names.
- **Colors**: `Badge color=` and the color maps use `EntityColor`, Rijkshuisstijl names (`lintblauw`, `mosgroen`, ...), never hex values or hand-picked palette steps.
- **Labels**: no uppercase or letter-spaced labels. A section label is `nldd-title size={6}`, a small caption `nldd-text size="xs" weight="medium" color="secondary"`.
- **Loading**: `LoadingSpinner` for a page or panel; a raw `nldd-activity-indicator` only inline in a button or row.
- **CSS**: layout goes through `nldd-container` attributes. `utilities.css` holds the few classes nothing in the design system covers; `scripts/validate-css-classes.mjs` checks every class used has a rule.
- **Checks**: `npx tsc -b && npx eslint src && node scripts/validate-nldd-markup.mjs && node scripts/validate-nldd-tokens.mjs && node scripts/validate-css-classes.mjs && npx vitest run` (in `frontend/`).

### Adding a new page

1. Create page component in `pages/NewPage.tsx` (no `<h1>`, Header handles it)
2. Add route in `App.tsx`
3. Add nav item in `Sidebar.tsx`
4. Add title in `Header.tsx` `pageTitles` map

## UI conventions

- Dutch labels throughout (Bewerken, Toevoegen, Verwijderen, etc.)
- Organisatie types: Ministerie, Directoraat-Generaal, Directie, Afdeling, Team
- Role labels defined in `ROL_LABELS` (`types/index.ts`) for display
- Node types: Dossier, Doel, Instrument, Beleidskader, Maatregel, Politieke Input
- Color maps (`NODE_TYPE_COLORS`, `ORGANISATIE_TYPE_BADGE_COLORS`, `TASK_PRIORITY_COLORS`, ...) in `types/index.ts`, all `EntityColor`

## Key data relationships

```
Person
├── Task (assignee_id)
├── ResourcePermission (eigenaar/betrokken/adviseur on any resource)
├── PersonRole (role assignments, system or scoped to eenheid)
├── OrganisatieEenheid (member via organisatie_eenheid_id)
├── OrganisatieEenheid (manager via manager_id)
├── Activity (actor_id)
├── Notification (person_id)
└── Absence (person_id / substitute_id)

CorpusNode (dossier/doel/instrument/beleidskader/maatregel/politieke_input/probleem/effect/beleidsoptie)
├── Edge (from_node_id / to_node_id, typed via EdgeType)
├── Task (node_id, nullable: een taak hangt aan een node, aan een casus of aan een vraag zonder casus, zie ck_task_anchor)
├── ResourcePermission (resource_type=corpus_node, resource_id=node_id)
└── NodeTag (node_id → Tag, hierarchical tagging)

Tag (hierarchical, parent_id self-ref)
└── NodeTag (many-to-many with CorpusNode)

ParlementairItem (tracks imported parliamentary items: moties, kamervragen, toezeggingen, etc.)
├── SuggestedEdge (proposed edges to corpus nodes, pending review)
├── CorpusNode (corpus_node_id, the created politieke_input node)
└── type discriminator (motie, kamervraag, toezegging, amendement, ...)

Lead ── 1:1 ──> Casus (start vanuit de kolom in_the_pocket; de lead is daarna alleen-lezen, 409 op mutaties)
├── Casus (lead_id RESTRICT, initiatief_id, fase (dummy), startvoorwaarden JSON (dummy), lessen (intern); de casus zelf gaat nooit naar buiten, alleen public_title/public_resultaat/public_lessen na vrijgeven (published_at), zolang hij in de laatste fase staat, zie "Naar buiten")
│   ├── Issue (casus_id, leeg bij een vraag van het initiatief zelf (`/initiatieven/{id}/vragen`, `core/werkplek.py`); initiatief_id (kan leeg zijn bij een vraag in een casus; het initiatief van een vraag komt altijd uit de casus, anders uit dit veld); antwoord (intern); title, toelichting, is_onderzoeksvraag, assignee_id SET NULL (eigenaar, lid van het initiatief), status open/in_progress/done, sort_order, dod_checked JSON). Er is geen story-laag: issue > taak > subtaken. De status volgt de hoofdtaken eronder via `IssueRepository.sync_status` na elke taakwijziging (iets loopt of is af, ook alles af: in_progress; alles open: open als het done was, anders blijft hij staan). Afgerond wordt een issue alleen met de hand, via de Definition of Done (`DodModal.tsx`, ook vanuit het bewerkvenster); een afgerond issue blijft afgerond zolang alle taken af zijn. Subtaken en geannuleerde taken tellen niet mee.
│   │   ├── Onderzoeksverslag (issue_id CASCADE, uniek; bestand via core.storage onder verslagen/; openbaar_op = akkoord om naar buiten te gaan, vervalt bij een nieuw bestand en bij intrekken of heropenen van de vraag). Een onderzoeksvraag heeft ook public_title/public_answer/published_at: alleen die tekst gaat naar buiten, zolang de vraag af is.
│   │   └── Task (issue_id SET NULL; casus_id wordt uit het issue gevuld)
│   │       └── Task (parent_id: subtaak, staat als opsomming onder de hoofdtaak, nooit als eigen taak of kaartje; alleen uit oude gegevens, en bij het verhuizen van de vraag krijgt ze het issue_id van de vraag)
│   ├── Task (casus_id, losse taak op de casus, zonder issue)
│   │   ├── TaskComment (task_id CASCADE, author_id SET NULL; content; @-vermeldingen via mention_helper)
│   │   └── TaskAttachment (task_id CASCADE; bestand via core.storage onder taken/)
│   ├── ResourcePermission (resource_type=casus; rol trekker/teamlid, alleen wie het initiatief kan zien)
│   ├── MattermostChannelLink (scope_type=casus, scope_id zonder DB-FK; alleen een privékanaal met de bot erin; `casus_updates_enabled` zet de voortgang aan, `van_de_lead` als het kanaal bij de start van de lead meekwam en bij het weghalen van de casus teruggaat). Koppelen, wijzigen en ontkoppelen volgt `require_can_change_casus`; de rollenmatrix staat in `tests/test_casus_kanaal.py`, niet in `test_casus_toegang.py`.
│   └── CasusKanaalbericht (casus_id CASCADE; elk voortgangsbericht met status geen_kanaal/wacht/verstuurd/mislukt/uit, ook zonder kanaal; `services/casus_kanaal_service.py` maakt en verstuurt ze na de commit, de worker pakt op wat bleef hangen, `POST …/kanaalberichten/{id}/opnieuw` doet het met de hand)

Backlog: `GET /casussen/backlog?initiatief_id=` geeft `{issues, losse_taken}`: alle issues van alle casussen van een initiatief met hun casus en hoofdtaken (subtaken op het kaartje), plus de taken zonder issue (tab Backlog, met een mini-kanban per issue; een kaartje opent het taakdetail met opmerkingen en bijlagen via `/tasks/{id}/comments` en `/tasks/{id}/attachments` in `api/routes/task_comments.py`). Zichtbaarheid loopt via de casus, net als `GET /tasks?casus_id=`: buiten een zichtbaar initiatief 404 (`require_initiatief_visible` in `core/initiatief_context.py`).

Toegang tot casuswerk (vaste regel, bewaakt door `tests/test_casus_toegang.py`): issues en taken van een casus zijn alleen zichtbaar voor wie het initiatief kan zien (direct lid of via een gekoppelde eenheid, `GET /initiatieven/{id}/personen` geeft die lijst met `rol` en `via_eenheden`). Een casustaak is daarbuiten overal 404 en ontbreekt in elke takenlijst, ook `/tasks/my`, de inbox en de chat-tools (`apply_casus_filter` in `repositories/task.py`). Wie een casustaak doet, trekker of teamlid is, moet lid zijn van het initiatief (`require_initiatief_member`, anders 400). De UI biedt alleen leden aan (`hooks/useInitiatiefPersonOptions.ts`); de backend is de bewaker. Elke nieuwe route of lijst die casuswerk teruggeeft, volgt deze regel en krijgt een test in dat bestand.
└── ResourcePermission (resource_type=lead; rol contactpersoon/opdrachtgever/betrokken = extern)

Initiatief
├── Lead (initiatief_id) — funnel-stage tracking
├── ResourcePermission (eigenaar/contributor/viewer per persoon of eenheid)
├── InitiatiefUpdatePost (publication posts; published_at IS NULL = concept)
│   ├── InitiatiefUpdateVraag (vrijgegeven onderzoeksvragen die de update meeneemt)
│   └── InitiatiefUpdateCasus (vrijgegeven afgeronde casussen die de update meeneemt)
└── slug (unique URL-segment, eenmalig instelbaar via /settings)

StakeholderAssessment (belang/houding/invloed per persoon op een scope)
├── scope_type=corpus_node OR initiatief
├── scope_id (polymorphic FK; access-check in route, geen DB-FK)
└── unique (person_id, scope_type, scope_id)
```

## Initiatief settings & publieke pagina

Per-initiatief feature-toggles (eigenaar-only via `PUT /api/initiatieven/{id}/settings`):

- `funnel_enabled` — toont engagement_type + drie 1-5 scores op leads van dit initiatief
- `public_page_enabled` — opt-in publieke pagina op `/c/:slug`
- `score_strategisch_label` / `score_politiek_label` / `score_positie_label` — eigen labels die de defaults overschrijven
- `dod_items` — Definition of Done (lijst eisen) bij het afronden van een issue, voor alle casussen van het initiatief; leeg = `DEFAULT_DOD` in `schema/casus.py`

Slug-rules in `backend/bouwmeester/core/slug.py`: lowercase, `[a-z0-9-]`, niet leeg, niet in `RESERVED_SLUGS`. Eenmalig instelbaar via UI (immutable na save in v1).

Publieke endpoints (`api/routes/public_initiatief.py`):
- `GET /api/public/initiatieven/by-slug/{slug}` en `GET /api/public/initiatieven/by-slug/{slug}/verslagen/{verslag_id}` (download, altijd als bijlage)
- Zitten in `_PUBLIC_PREFIXES` van `auth_required.py` — geen auth nodig
- Returnen 404 als slug niet bestaat OF `public_page_enabled=false` (geen 403 om bestaan niet te lekken); de download ook als het verslag niet buiten mag, zonder onderscheid
- Two-step query (lookup zonder relations, daarna eager-load) om timing-side-channel te beperken
- Toont naam/beschrijving/kleur, gepubliceerde `InitiatiefUpdatePost` records (`published_at IS NOT NULL`) met de vragen en casussen die ze meenemen, lopende casussen van leads die daarvoor zijn opengezet, en de beantwoorde vragen en afgeronde casussen die nu buiten mogen
- Elke tekst gaat door `verwijzingen_als_tekst` (`schema/publieke_tekst.py`): een @- of #-verwijzing wordt gewone tekst, zonder id
- Frontend route `/c/:slug` in `App.tsx` zit buiten `AuthGate`; `<meta name="robots" content="noindex">` op de pagina, plus blanket `Disallow: /` in `frontend/public/robots.txt`

### Naar buiten

Wat van binnen naar buiten mag, bepalen alleen `services/publieke_vragen.py` (onderzoeksvragen en hun verslag) en `services/publieke_casussen.py` (afgeronde casussen). De tab Updates, de publieke pagina en de mailbrief lezen daar.

- Naar buiten gaat alleen tekst die iemand daarvoor schreef: `public_title`/`public_answer` van een afgeronde onderzoeksvraag, `public_title`/`public_resultaat`/`public_lessen` van een casus in de laatste fase van de funnel. Titel, toelichting, intern antwoord, team en lessen blijven binnen.
- Vrijgeven (`PUT …/publiek`) is een eigen handeling van een bijdrager of eigenaar van het initiatief (`require_can_publish_issue`); intrekken (`DELETE …/publiek`) mag iedereen die de casus wijzigt. Een statuswijziging publiceert niets.
- Niet meer af is niet meer buiten: een vraag die heropend wordt of geen onderzoeksvraag meer is, en een casus die niet meer in de laatste fase staat (ook als de funnel verandert, bv. een fase erachter), krijgt `published_at` leeg. De tekst blijft bewaard; opnieuw vrijgeven is weer een eigen handeling.
- Het onderzoeksverslag gaat pas mee na een expliciet akkoord (`openbaar_op`) en als de vraag buiten is. Het akkoord vervalt bij een nieuw bestand en bij intrekken of heropenen. Buiten heet het bestand naar de publieke vraag (`publieke_verslagnaam`), en een upload moet beginnen met de signatuur van zijn type (`validate_upload(..., signatuur_verplicht=True)`).
- Publieke tekst (vraag, casus, titel en tekst van een update) weigert een @- of #-verwijzing (`geen_verwijzingen`) en wordt gestript; een concept van daarvoor publiceert pas als de verwijzing eruit is.
- Een gepubliceerde update is als mailbrief te downloaden (`GET …/updates/{id}/eml`): een concept voor Outlook zonder ontvangers, alleen met wat ook op de publieke pagina staat.
- Tests: `test_beantwoorde_vragen.py`, `test_afgeronde_casussen.py`, `test_onderzoeksverslag.py`; de 404's voor de publieke routes en voor buitenstaanders in `test_casus_toegang.py`.

## Seed data and PII

Person data in the seed script is **not** stored in git as plaintext. Instead:

- `backend/scripts/seed_persons.json` — plaintext person data, **gitignored**
- `backend/scripts/seed_persons.json.age` — age-encrypted version, **committed**
- The seed script (`backend/scripts/seed.py`) loads from the JSON file. If missing, it generates placeholder persons with a warning.

### Working with seed person data

```bash
just decrypt-seed    # Decrypt .age → .json (needs ~/.age/key.txt)
just encrypt-seed    # Encrypt .json → .age (uses public keys from justfile)
```

To edit person data: decrypt, edit the JSON, re-encrypt, commit the `.age` file.

### New developer setup

1. `brew install age`
2. `age-keygen -o ~/.age/key.txt` — send the public key to a team member
3. Team member adds your public key to `encrypt-seed` in `justfile` and re-encrypts
4. `just decrypt-seed` to get the person data
5. `just reset-db` works without decryption too (uses placeholder persons)

## Access whitelist

Production access is restricted to whitelisted email addresses stored in the `whitelist_email` database table, managed via the admin UI (Beheer > Toegangslijst).

- Backend module: `bouwmeester/core/whitelist.py` — cache refreshed at startup and on whitelist changes, enforced in `AuthRequiredMiddleware` (all API routes) and `auth_status()` (friendly frontend response)
- When the whitelist table is empty, all emails are allowed (backwards compatible for local dev)
- Non-whitelisted users can request access via the AccessDeniedPage; admins approve/deny from Beheer > Verzoeken

## Authorization patterns

`AuthRequiredMiddleware` enforces authentication on `/api/*`. **Authorization** (which records a user may see/mutate) is per-route, using these helpers:

- **List endpoints** filter on `org_ctx`: pass `org_ctx: OrgContext = Depends(get_org_context)` to the route and `apply_org_filter(stmt, Model.organisatie_eenheid_id, org_ctx)` in the repo.
- **Detail endpoints** check scope: `await check_resource_org_scope(db, "<resource_type>", id, org_ctx)`.
- **Mutations** also need a permission gate: `_perm=Depends(require_permission("<perm>"))` plus `check_org_scope(eenheid_id, org_ctx)` on any incoming `organisatie_eenheid_id`.
- **Tenant-wide-by-design** endpoints (`tags`, `organisatie`-chart, `edge-types`, `roles`) are intentionally readable by every authenticated user. Whitelist them in `backend/tests/test_route_authorization_inventory.py`.

The inventory test fails CI on any new GET `/api/*` route that lacks an authz dependency, so adding a list-endpoint without `apply_org_filter` is impossible without an explicit whitelist or known-debt entry.

### Authority over grants (`core/authority.py`)

Anything that changes *who has access to what* goes through a `require_can_*` guard in `core/authority.py`, never through `require_permission` + `check_org_scope`: placements, naming a manager, moving or dissolving an eenheid, assigning or revoking roles, deciding placement requests, editing a person (emails are identity), granting resource roles. REST routes and chat tools call the same guards.

- A role on an eenheid applies to everything below it (`rights_on_eenheid`). Seeing an eenheid never implies authority over it.
- Nobody grants themselves a role; nobody decides their own placement request.
- Tenant-wide actions (syncs, merges) use `require_system_permission`, not `require_permission`.
- Tree walks for access (`repositories/org_tree.py`) read `OrganisatieEenheid.parent_id`; internal org types live in `INTERNAL_EENHEID_TYPES`.
- Tests: `tests/test_grant_authority.py`, built on `tests/factories.py`.

### Testing rights locally

Local dev has no identity provider. Without a pick in the header's person picker every request is allowed; after picking someone, the backend (dev mode only, via the `bm_dev_person` cookie) runs every request with that person's real roles and memberships. `just seed` gives managers, `ministry_admin`s, editors and viewers across a real tree to pick from.

## Pull requests

- Always branch from the latest remote main: `git fetch origin && git checkout -b <branch> origin/main`
- Do **not** merge PRs automatically, even when CI is green. After CI passes, critically review your own diff (correctness, edge cases, missing tests, style) and present your findings to the user. The user may request changes — expect one or more review rounds.
- Only merge when the user explicitly says so (e.g. "merge it", "looks good, merge").
- Use squash merge with `--delete-branch` by default.

## Database

- PostgreSQL 16, connection via Docker Compose on `localhost:5432`
- Credentials: `bouwmeester` / `bouwmeester` / `bouwmeester` (user/password/db)
- Migrations run locally via `uv` (not inside Docker), connecting to localhost
- DB may not always be running — use `just up` or `docker compose up -d db` first
