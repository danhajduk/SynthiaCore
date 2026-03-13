# Synthia Skill Graph

This file defines how Codex should sequence and combine skills in this repository.

It complements `Agents.md` by describing:

- skill precedence
- allowed execution chains
- required safety gates
- disallowed combinations
- fallback behavior

Codex must follow this graph when more than one skill could apply.

---

# Core Rule

Always use the **smallest valid execution chain**.

Do not load multiple skills unless the task actually requires them.

Do not invent new chains outside this file.

---

# Skill Nodes

## synthia-workflow

Purpose:
Primary implementation workflow for code changes.

Use for:
- backend development
- frontend/UI work
- scripts
- runtime behavior
- bug fixes
- feature implementation

May call next:
- synthia-documentation
- commit-safety-check

Must not replace:
- synthia-documentation
- synthia-documentation-audit
- synthia-architecture-audit

---

## synthia-documentation

Purpose:
Write or update documentation.

Use for:
- docs/*
- README updates
- API docs
- subsystem docs
- architecture references
- archive work

May call next:
- commit-safety-check

Must not be used for:
- implementation
- audit-only tasks

---

## synthia-documentation-audit

Purpose:
Detect and correct routine documentation drift.

Use for:
- periodic doc cleanup
- verifying docs against code
- pre-release doc checks
- stale doc detection

May call next:
- synthia-documentation
- commit-safety-check

Must not replace:
- synthia-architecture-audit for deep structural review
- synthia-workflow for implementation

---

## synthia-architecture-audit

Purpose:
Deep structural architecture and source-of-truth audit.

Use for:
- architecture drift
- undocumented subsystems
- contract mismatches
- ownership boundary review
- contributor-readiness review

May call next:
- synthia-documentation
- synthia-documentation-audit
- commit-safety-check

Must not be used for:
- implementation
- routine doc touchups unless explicitly part of an audit result

---

## commit-safety-check

Purpose:
Pre-commit safety gate.

Use for:
- scanning staged changes
- scanning unstaged changes
- scanning untracked files
- secret detection before commit

This is a terminal safety gate before commit.

It does not perform implementation or documentation work.

---

## skill-creator

Purpose:
Create or revise skills.

Use for:
- new `SKILL.md` files
- skill refactors
- workflow changes
- skill wording updates

May call next:
- commit-safety-check

Must not be used for:
- implementation tasks
- repository documentation tasks unrelated to skills

---

## skill-installer

Purpose:
Install skills from curated sources.

Use for:
- bootstrapping local skills
- importing known skill packages

Must not be used for:
- implementation
- documentation
- audits

---

# Preferred Execution Chains

Use these chains when applicable.

## Implementation only

synthia-workflow

---

## Implementation with doc updates

synthia-workflow
→ synthia-documentation
→ commit-safety-check

Use when implementation changed user-facing behavior, API usage, setup flow, or architecture-facing docs.

---

## Documentation update only

synthia-documentation
→ commit-safety-check

Use when only docs are being edited.

---

## Routine documentation drift audit

synthia-documentation-audit
→ synthia-documentation
→ commit-safety-check

Use when docs may have drifted after recent work.

---

## Deep architecture audit with remediation docs

synthia-architecture-audit
→ synthia-documentation
→ commit-safety-check

Use when architecture/source-of-truth issues were found and documentation is being corrected.

---

## Deep architecture audit followed by routine cleanup

synthia-architecture-audit
→ synthia-documentation-audit
→ synthia-documentation
→ commit-safety-check

Use only when a broad structural review reveals both architecture-level and routine doc drift.

---

## Skill maintenance

skill-creator
→ commit-safety-check

Use for creating or updating skills.

---

# Mandatory Safety Gates

## Commit safety

Before any commit operation:

commit-safety-check must run.

If high-severity or critical findings exist:

- stop
- remediate
- rerun the scan
- only commit when clean

Never bypass this gate.

---

# Conflict Resolution

If more than one skill appears applicable, resolve in this order:

1. explicit user instruction
2. safety gate requirement
3. more specific skill
4. smaller valid execution chain
5. broader fallback skill

Examples:

- doc drift check beats generic documentation writing
- architecture audit beats documentation audit when subsystem truth is in question
- documentation skill beats implementation skill for doc-only edits
- commit-safety-check always runs before commit

---

# Disallowed Substitutions

Do not substitute one of these for another:

- do not use `synthia-workflow` for doc-only tasks
- do not use `synthia-documentation` for implementation
- do not use `synthia-documentation-audit` for deep architecture review
- do not use `synthia-architecture-audit` for normal feature work
- do not use `commit-safety-check` as a code review tool

---

# Stop Conditions

Stop and report if:

- no listed skill chain fits the task
- the task requires changing locked skill files without explicit instruction
- a required safety gate cannot run
- task intent conflicts with `Agents.lock`

Do not invent a replacement workflow.

---

# Locked Configuration Rule

If `Agents.lock` is present:

- do not modify `Agents.md`
- do not modify `SkillGraph.md`
- do not modify protected `SKILL.md` files

unless the user explicitly requests those changes.

---

# Repository Authority Order

When skill behavior conflicts with repository content, resolve in this order:

1. repository code
2. locked agent configuration (`Agents.lock`)
3. `Agents.md`
4. `SkillGraph.md`
5. skill file contents
6. repository docs
7. task files

Code always wins for implementation truth.
Locked agent configuration wins for workflow protection.