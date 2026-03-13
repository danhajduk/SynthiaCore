# AI Node Documentation Gap Report

Status: Planned
Last updated: 2026-03-11
Source comparison:
- Main AI Node repo: `/home/dan/Projects/SynthiaAiNode/docs`
- Golden docs: `/home/dan/Projects/Synthia/docs`

## Purpose

This report defines the remaining documentation gaps required to align the AI Node documentation set with golden documentation standards used in main Synthia docs.

## Baseline Observations

- AI Node repo currently contains architecture-planning documentation only.
- AI Node docs correctly mark implementation as not developed.
- Golden docs define canonical structure, index-first navigation, and per-section status conventions.

## Gap 1: Missing AI Node Entry In Golden Canonical Index

Current state:
- Golden index (`document-index.md`) does not include an AI Node architecture track.

Required fulfillment:
- Add an AI Node section/link in golden index that points to canonical AI Node documents.
- Clarify whether AI Node docs are canonical in golden repo or mirrored from node repo.

Acceptance criteria:
- AI Node docs are discoverable from golden `document-index.md`.
- Ownership/canonical source is explicit.

## Gap 2: Missing Canonical Mapping Between Main And Golden Docs

Current state:
- No explicit mapping document describes which AI Node files in the node repo correspond to golden docs.

Required fulfillment:
- Create a short mapping table:
  - `ai-node-architecture.md`
  - `node-capability-declaration.md`
  - `phase1-overview.md`
- Define sync direction (golden-first, node-first, or bidirectional with owner).

Acceptance criteria:
- Mapping exists in golden docs and is referenced by index or migration docs.
- Sync direction is unambiguous.

## Gap 3: Incomplete Phase 1 Overview Artifact In Main Repo

Current state:
- `phase1-overview.md` ends with `# Phase 1 System Diagram` and no diagram/body.

Required fulfillment:
- Complete Phase 1 system diagram section.
- Include minimal data flow:
  - bootstrap discovery
  - registration API call
  - Core UI approval
  - trust activation response
  - local state persistence

Acceptance criteria:
- Section is complete and readable.
- Flow matches architecture constraints (no telemetry/control over anonymous bootstrap).

## Gap 4: Status Taxonomy Misalignment

Current state:
- AI Node docs use document-level labels (`Draft architecture target`, `Not developed`).
- Golden docs typically use section-level status labels (`Implemented`, `Partial`, `Planned`, `Archived Legacy`).

Required fulfillment:
- Add section-level status markers in AI Node docs (likely `Planned` for architecture sections).
- Preserve explicit `Not developed` statements where behavior is not implemented.

Acceptance criteria:
- Status vocabulary is consistent with golden conventions.
- No section implies implementation that is absent in code.

## Gap 5: Cross-Link Density Is Too Low

Current state:
- AI Node docs contain minimal internal and upstream cross-links.

Required fulfillment:
- Add links between:
  - `phase1-overview.md`
  - `ai-node-architecture.md`
  - `node-capability-declaration.md`
- Add upstream references to relevant golden docs where applicable:
  - `platform-architecture.md`
  - `mqtt-platform.md`
  - `api-reference.md`

Acceptance criteria:
- Each AI Node doc has a short "See also" section.
- Navigation between node docs and golden subsystem docs is direct.

## Gap 6: Task File Hygiene Drift In Main Repo

Current state:
- `docs/New-Tasks.txt` contains workflow prose and directives above the task area.

Required fulfillment:
- Keep active task queue as task entries only.
- Move reusable directives to a stable skill/workflow document, not the active queue file.

Acceptance criteria:
- Active queue stays parseable and minimal.
- No ambiguity about task list start.

## Recommended Fulfillment Order

1. Complete `phase1-overview.md` diagram/content.
2. Normalize AI Node status taxonomy and cross-links.
3. Publish mapping and ownership model in golden docs.
4. Add AI Node entry in golden index.
5. Clean main task queue file format.

## Verification Checklist

- AI Node docs remain explicit about non-implemented behavior.
- Golden index references AI Node documentation path.
- Main and golden docs have consistent naming and links.
- No contradictions between bootstrap/trust boundaries across docs.
