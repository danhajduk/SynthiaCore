You are working in the Synthia Core repository.

Your task is to create two documentation files:

- `docs/architecture.md`
- `docs/index.md`

These files must align with the documentation direction already established for Synthia Core:

- `README.md` is the repository entry point
- `docs/overview.md` is the platform-level overview
- `docs/architecture.md` must explain the internal architecture of Synthia Core
- `docs/index.md` must act as the documentation navigation page for this repository

## Objectives

Create documentation that is:

- technically accurate to the current repository
- organized for future growth
- clear about ownership boundaries
- written as canonical docs for this repo
- consistent with the current Synthia documentation strategy

Do not invent features that do not exist in the repository.
Do not describe aspirational behavior as implemented behavior.
If a subsystem exists only partially, describe it carefully and truthfully.

---

## File 1: `docs/architecture.md`

### Purpose

This file must explain the **internal architecture of Synthia Core**.

It is not a marketing page.
It is not an install guide.
It is not a repo tree dump.

It should explain:

- what Synthia Core is responsible for internally
- how the major subsystems relate to each other
- where authority lives
- how requests, events, scheduling, addons, and nodes flow through the system
- how the frontend, backend, MQTT, scheduler, workers, supervisor, addons, and nodes fit together

### Required structure

Create `docs/architecture.md` with these major sections:

1. `# Synthia Core Architecture`
2. `## Scope`
3. `## Architectural Responsibilities`
4. `## Major Subsystems`
5. `## Control Flow`
6. `## Runtime Boundaries`
7. `## Extension Models`
8. `## Source Layout`
9. `## Related Documentation`

### Content requirements by section

#### 1. `# Synthia Core Architecture`
Open with a concise explanation that this file describes the architecture of the Core repository specifically, not the full ecosystem.

#### 2. `## Scope`
Explain what this document covers and what it does not cover.

Must clearly distinguish:
- this file = Core internal architecture
- `docs/overview.md` = platform-wide overview
- subsystem docs = deeper contracts and references

#### 3. `## Architectural Responsibilities`
Describe the responsibilities of Core as the platform control-plane.

Must include:
- API hosting
- frontend serving/integration
- runtime state coordination
- addon lifecycle authority
- scheduler/worker orchestration
- MQTT platform authority
- trusted node integration
- telemetry / health aggregation

#### 4. `## Major Subsystems`
Create subsections for each of the following:

- Core backend
- Frontend
- MQTT platform services
- Scheduler
- Workers
- Supervisor
- Addon platform
- Node integration

For each subsystem, explain:
- what it owns
- what it depends on
- how it interacts with other parts of Core

Keep each subsection focused and factual.

#### 5. `## Control Flow`
Explain the major architectural flows at a high level.

Include short subsections for:

- API/UI flow
- scheduler/job flow
- addon lifecycle flow
- standalone runtime/supervisor flow
- node onboarding/governance flow
- MQTT event/notification flow

Do not go too deep into payload schemas or endpoint-by-endpoint API detail.
Keep this conceptual but concrete.

#### 6. `## Runtime Boundaries`
Explain the main runtime boundaries in Synthia Core.

Must distinguish:
- in-process Core services
- embedded addons
- supervised standalone services
- external trusted nodes
- frontend vs backend boundary
- API vs MQTT communication boundary where relevant

#### 7. `## Extension Models`
Explain the three extension models clearly:

- embedded addons
- standalone addons
- external nodes

This section should help readers understand how the platform scales beyond a single process.

#### 8. `## Source Layout`
Provide a high-level source mapping of where architecture-relevant code lives.

Use a concise structure such as:

- `backend/app/`
- `backend/app/system/`
- `backend/synthia_supervisor/`
- `frontend/`
- `scripts/`
- `systemd/user/`

Do not turn this into a full file listing.
Only include meaningful architectural paths.

#### 9. `## Related Documentation`
Link readers to the next most relevant docs, such as:

- `docs/index.md`
- `docs/overview.md`
- `docs/core-platform.md`
- `docs/mqtt-platform.md`
- `docs/runtime-and-supervision.md`
- `docs/addon-platform.md`
- `docs/api-reference.md`

Use repository-relative markdown links.

---

## Additional requirements for `docs/architecture.md`

### Tone
Write in a professional technical documentation tone.

### Formatting
Use clean markdown headings.
Use short paragraphs.
Use bullet lists only where they improve clarity.

### Accuracy
Read the repository before writing.
Ground the document in the actual code layout and current implementation.

### Architecture diagram
Include one simple ASCII architecture diagram showing the high-level relationship between:

- frontend
- core backend
- scheduler/workers
- MQTT
- addon platform
- supervisor
- standalone addons
- external nodes

Do not make it overly decorative.
Keep it readable in plain markdown.

### Important exclusions
Do not duplicate:
- detailed install steps from `README.md`
- full platform explanation from `docs/overview.md`
- full API reference
- payload schemas that belong in subsystem docs

---

## File 2: `docs/index.md`

### Purpose

This file must be the **documentation entry point** for the Synthia Core repository.

It should help readers quickly find the correct documentation page.

This is a navigation document, not a deep technical spec.

### Required structure

Create `docs/index.md` with these major sections:

1. `# Synthia Core Documentation`
2. `## Start Here`
3. `## Core Platform`
4. `## Runtime and Messaging`
5. `## Addons and Nodes`
6. `## Operations and Development`
7. `## Reference`

### Content requirements by section

#### 1. `# Synthia Core Documentation`
One short intro explaining that this page is the navigation hub for the repository docs.

#### 2. `## Start Here`
Must include links to:
- `../README.md`
- `overview.md`
- `architecture.md`

Each link should have a one-line explanation.

#### 3. `## Core Platform`
List the most important core platform docs, such as:
- `core-platform.md`
- `api-reference.md`

Include short descriptions for each.

#### 4. `## Runtime and Messaging`
List docs related to:
- MQTT
- notifications
- runtime/supervision
- scheduling if already documented elsewhere

Use short descriptions.

#### 5. `## Addons and Nodes`
List docs related to:
- addon platform
- node integration
- future lifecycle/contract docs if they already exist
Only link files that currently exist in the repo.
If a likely future doc does not exist yet, do not link it as if it exists.

#### 6. `## Operations and Development`
List docs such as:
- `operators-guide.md`
- `development-guide.md`

Add short descriptions.

#### 7. `## Reference`
If relevant files exist, include:
- configuration
- notifications
- API references
- environment/reference docs

Again: link only real files.

---

## Additional requirements for `docs/index.md`

### Navigation behavior
This page should help three kinds of readers:

- someone new to the repo
- an operator trying to find runtime docs
- a developer trying to find implementation docs

### Link rules
Use relative markdown links only.
Verify file names from the actual repository before linking.

### Descriptions
Every listed document should have:
- linked title
- one-sentence description

### Avoid
Do not write long prose.
Do not repeat whole contents of the linked docs.
Do not invent sections for non-existent files.

---

## Repository inspection requirements

Before writing either file:

1. inspect the existing `docs/` directory
2. inspect the current `README.md`
3. inspect the relevant backend/frontend paths so the architecture description matches reality
4. verify all linked docs actually exist

If an existing file name differs from the suggested names above, use the real file name.

---

## Implementation instructions

1. Read the current repository structure.
2. Create or update `docs/architecture.md`.
3. Create or update `docs/index.md`.
4. Keep both files concise but complete.
5. Ensure both files use consistent terminology:
   - Core
   - Supervisor
   - Scheduler
   - Workers
   - Addons
   - Nodes
   - MQTT platform
   - Frontend
6. Do not rename existing docs unless explicitly necessary.
7. Do not modify unrelated files.

---

## Completion criteria

This task is complete only when:

- `docs/architecture.md` exists and explains the Core internal architecture clearly
- `docs/index.md` exists and works as a useful doc navigation page
- all links point to real files
- content is grounded in the current repository state
- the two files are consistent with `README.md` and `docs/overview.md`