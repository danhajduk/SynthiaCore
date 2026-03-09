# Synthia Codex Agent Configuration

This file defines how Codex should use local skills and workflows in this repository.

---

# Skills

A skill is a set of local instructions stored in a `SKILL.md` file.

Below is the list of available skills.

Each entry includes:
- skill name
- description
- file path

Skill bodies live on disk and must be loaded only when needed.

---

## Available Skills

- **synthia-workflow**  
  Implementation workflow for Synthia development tasks.  
  Use for coding tasks, refactors, bug fixes, and feature implementation.  
  File: `/home/dan/.codex/skills/synthia-workflow/SKILL.md`

- **synthia-documentation**  
  Code-verified documentation workflow.  
  Use for writing or updating docs, API documentation, architecture references, or archiving outdated docs.  
  File: `/home/dan/.codex/skills/synthia-documentation/SKILL.md`

- **synthia-architecture-audit**  
  Architecture audit workflow used to detect documentation drift, undocumented subsystems, or code-to-doc mismatches.  
  File: `/home/dan/.codex/skills/synthia-architecture-audit/SKILL.md`

- **commit-safety-check**  
  Verifies pending repository changes do not contain secrets before committing.  
  File: `/home/dan/.codex/skills/commit-safety-check/SKILL.md`

- **skill-creator**  
  Workflow for creating or updating Codex skills.  
  File: `/home/dan/.codex/skills/.system/skill-creator/SKILL.md`

- **skill-installer**  
  Installs Codex skills from curated lists or repositories.  
  File: `/home/dan/.codex/skills/.system/skill-installer/SKILL.md`

---

# Skill Selection Rules

Select the minimal skill set required to complete the task.

### Implementation tasks
Use:

synthia-workflow

Examples:
- feature development
- bug fixes
- refactors
- backend changes
- frontend/UI changes
- scripts or runtime behavior

---

### Documentation tasks
Use:

synthia-documentation

Examples:
- writing documentation
- updating docs/*
- API documentation
- subsystem documentation
- architecture diagrams

---

### Architecture review tasks
Use:

synthia-architecture-audit

Examples:
- detecting documentation drift
- verifying architecture alignment
- identifying undocumented subsystems
- checking API/doc inconsistencies

---

### Commit validation
Use:

commit-safety-check

Examples:
- before any commit
- when verifying commit safety
- when asked to scan repository changes for secrets

---

# Skill Trigger Rules

A skill must be used when:

- the user explicitly names the skill
- the task clearly matches the skill description

If multiple skills apply:

1. select the minimal required set
2. execute them sequentially
3. state the order before beginning

Example sequence:

architecture-audit → documentation → implementation

---

# Skill Loading Rules

When using a skill:

1. Open the corresponding `SKILL.md`
2. Load only the sections required to execute the workflow
3. Avoid loading unrelated reference material

Relative paths inside a skill must be resolved relative to the skill directory first.

Example:
