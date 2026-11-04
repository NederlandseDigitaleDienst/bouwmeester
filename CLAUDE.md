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
├── Task (node_id, nullable: een taak hangt aan een node of aan een casus, zie ck_task_anchor)
├── ResourcePermission (resource_type=corpus_node, resource_id=node_id)
└── NodeTag (node_id → Tag, hierarchical tagging)

Tag (hierarchical, parent_id self-ref)
└── NodeTag (many-to-many with CorpusNode)

ParlementairItem (tracks imported parliamentary items: moties, kamervragen, toezeggingen, etc.)
├── SuggestedEdge (proposed edges to corpus nodes, pending review)
├── CorpusNode (corpus_node_id, the created politieke_input node)
└── type discriminator (motie, kamervraag, toezegging, amendement, ...)

Lead ── 1:1 ──> Casus (start vanuit de kolom in_the_pocket; de lead is daarna alleen-lezen, 409 op mutaties)
├── Casus (lead_id RESTRICT, initiatief_id, fase (dummy), startvoorwaarden JSON (dummy), nooit publiek)
│   ├── Issue (casus_id; title, toelichting, is_onderzoeksvraag, assignee_id SET NULL (eigenaar, lid van het initiatief), status open/in_progress/done, sort_order, dod_checked JSON). Er is geen story-laag: issue > taak > subtaken. De status volgt de hoofdtaken eronder via `IssueRepository.sync_status` na elke taakwijziging (iets loopt of is af, ook alles af: in_progress; alles open: open als het done was, anders blijft hij staan). Afgerond wordt een issue alleen met de hand, via de Definition of Done (`DodModal.tsx`, ook vanuit het bewerkvenster); een afgerond issue blijft afgerond zolang alle taken af zijn. Subtaken en geannuleerde taken tellen niet mee.
│   │   └── Task (issue_id SET NULL; casus_id wordt uit het issue gevuld)
│   │       └── Task (parent_id: subtaak, staat als opsomming onder de hoofdtaak, nooit als eigen taak of kaartje)
│   ├── Task (casus_id, losse taak op de casus, zonder issue)
│   │   ├── TaskComment (task_id CASCADE, author_id SET NULL; content; @-vermeldingen via mention_helper)
│   │   └── TaskAttachment (task_id CASCADE; bestand via core.storage onder taken/)
│   └── ResourcePermission (resource_type=casus; rol trekker/teamlid, alleen wie het initiatief kan zien)

Backlog: `GET /casussen/backlog?initiatief_id=` geeft `{issues, losse_taken}`: alle issues van alle casussen van een initiatief met hun casus en hoofdtaken (subtaken op het kaartje), plus de taken zonder issue (tab Backlog, met een mini-kanban per issue; een kaartje opent het taakdetail met opmerkingen en bijlagen via `/tasks/{id}/comments` en `/tasks/{id}/attachments` in `api/routes/task_comments.py`). Zichtbaarheid loopt via de casus, net als `GET /tasks?casus_id=`: buiten een zichtbaar initiatief 404 (`require_initiatief_visible` in `core/initiatief_context.py`).

Toegang tot casuswerk (vaste regel, bewaakt door `tests/test_casus_toegang.py`): issues en taken van een casus zijn alleen zichtbaar voor wie het initiatief kan zien (direct lid of via een gekoppelde eenheid, `GET /initiatieven/{id}/personen` geeft die lijst met `rol` en `via_eenheden`). Een casustaak is daarbuiten overal 404 en ontbreekt in elke takenlijst, ook `/tasks/my`, de inbox en de chat-tools (`apply_casus_filter` in `repositories/task.py`). Wie een casustaak doet, trekker of teamlid is, moet lid zijn van het initiatief (`require_initiatief_member`, anders 400). De UI biedt alleen leden aan (`hooks/useInitiatiefPersonOptions.ts`); de backend is de bewaker. Elke nieuwe route of lijst die casuswerk teruggeeft, volgt deze regel en krijgt een test in dat bestand.
└── ResourcePermission (resource_type=lead; rol contactpersoon/opdrachtgever/betrokken = extern)

Initiatief
├── Lead (initiatief_id) — funnel-stage tracking
├── ResourcePermission (eigenaar/contributor/viewer per persoon of eenheid)
├── InitiatiefUpdatePost (publication posts; published_at IS NULL = concept)
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

Publieke endpoint `GET /api/public/initiatieven/by-slug/{slug}`:
- Zit in `_PUBLIC_PREFIXES` van `auth_required.py` — geen auth nodig
- Returnt 404 als slug niet bestaat OF `public_page_enabled=false` (geen 403 om bestaan niet te lekken)
- Two-step query (lookup zonder relations, daarna eager-load) om timing-side-channel te beperken
- Toont alleen naam/beschrijving/kleur + gepubliceerde `InitiatiefUpdatePost` records (`published_at IS NOT NULL`)
- Frontend route `/c/:slug` in `App.tsx` zit buiten `AuthGate`; `<meta name="robots" content="noindex">` op de pagina, plus blanket `Disallow: /` in `frontend/public/robots.txt`

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
