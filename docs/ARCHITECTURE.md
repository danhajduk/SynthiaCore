# Synthia Core + Addon Architecture (Clean Spec)

> Single-source-of-truth documentation intended for both humans and AI code generators.

## 1) Core vs Addon: Mental Model

### Core is the “operating system”
Core is responsible for:
- Running the FastAPI server
- Serving a stable API surface for the UI
- Hosting the React app (or being reverse-proxied in production)
- Discovering and registering addons
- Providing shared primitives:
  - config
  - logging
  - common UI layout (sidebar/header/router)
  - base types/models that addons can import
  - a canonical `/api/addons` list endpoint

Core should be small and boring. **Core does not implement feature pages** unless they are truly “system” pages (Settings, Health, Addons).

### Addons are feature packs
Each addon is responsible for:
- Its own backend routes (FastAPI router)
- Its own frontend routes/pages/components
- Its own metadata (id/name/version/description)
- Optional settings schema, permissions, assets

Addons should be self-contained and disposable: delete the folder → the feature disappears.

---

## 2) Repo Layout (Clean, Rebuild-From-Zero Version)

```
Synthia/
├─ backend/
│  ├─ app/
│  │  ├─ main.py
│  │  ├─ core/
│  │  │  ├─ __init__.py
│  │  │  ├─ config.py
│  │  │  ├─ logging.py
│  │  │  └─ health.py
│  │  ├─ addons/
│  │  │  ├─ __init__.py
│  │  │  ├─ discovery.py
│  │  │  ├─ registry.py
│  │  │  └─ models.py
│  │  └─ api/
│  │     ├─ __init__.py
│  │     └─ system.py
│  ├─ pyproject.toml (or requirements.txt)
│  └─ README.md
│
├─ frontend/
│  ├─ index.html
│  ├─ package.json
│  ├─ vite.config.ts
│  ├─ tsconfig.json
│  ├─ src/
│  │  ├─ main.tsx
│  │  ├─ App.tsx
│  │  ├─ core/
│  │  │  ├─ layout/
│  │  │  │  ├─ Shell.tsx
│  │  │  │  ├─ Sidebar.tsx
│  │  │  │  └─ Header.tsx
│  │  │  ├─ router/
│  │  │  │  ├─ routes.tsx
│  │  │  │  └─ loadAddons.ts
│  │  │  ├─ api/
│  │  │  │  └─ client.ts
│  │  │  └─ pages/
│  │  │     ├─ Home.tsx
│  │  │     ├─ Addons.tsx
│  │  │     └─ Settings.tsx
│  │  ├─ addons/                 <-- SYNC TARGET (generated/symlinked)
│  │  │  └─ (addon folders appear here)
│  │  └─ types/
│  │     └─ addon.ts
│  └─ README.md
│
├─ addons/
│  └─ hello_world/
│     ├─ manifest.json
│     ├─ backend/
│     │  ├─ __init__.py
│     │  └─ addon.py
│     └─ frontend/
│        ├─ index.ts
│        ├─ routes.tsx
│        ├─ HelloWorldPage.tsx
│        └─ components/
│           └─ HelloCard.tsx
│
├─ scripts/
│  ├─ sync-addons-frontend.sh
│  └─ dev.sh
│
├─ docs/
│  └─ ARCHITECTURE.md
├─ .gitignore
└─ README.md
```

Key rule: **Core never edits addon code.** Core only loads addons.

---

## 3) Backend Core: Required Interfaces and Behavior

### 3.1 Backend addon contract (the one true rule)
Every backend addon MUST export a variable named `addon` from:

`addons/<addon_id>/backend/addon.py`

That `addon` object MUST include:
- `meta` (Pydantic model)
- `router` (FastAPI APIRouter)

Backend addon object shape:
- `AddonMeta`: `{ id, name, version, description? }`
- `BackendAddon`: `{ meta, router }`

### 3.2 Backend discovery/registry
Recommended approach: **file-system auto-discovery**  
Core scans `Synthia/addons/*/backend/addon.py`, imports them dynamically, validates the contract, and registers routers.

Rules:
- If an addon import fails, core logs the error and continues booting.
- Only valid addons appear in `/api/addons`.
- Registered routes are mounted at:

`/api/addons/<addon_id>/...`

### 3.3 Backend endpoints Core must expose
Core must expose at minimum:
- `GET /api/health` → `{ "status": "ok" }`
- `GET /api/addons` → list of addon metadata (id, name, version, description)

---

## 4) Frontend Core: Required Interfaces and Behavior

### 4.1 Frontend addon contract
Every frontend addon MUST export from:

`addons/<addon_id>/frontend/index.ts`

Exports:
- `meta` object
- `routes` array (React Router route objects)
- `navItem` object (sidebar entry)

### 4.2 How frontend “sees” addons
Frontend should not import from `../../addons/...` directly.  
Instead, core has a sync target:

`frontend/src/addons/<addon_id>/...`

This folder is populated by a script that symlinks or copies addon frontends into the app.

### 4.3 Frontend route aggregation
Core aggregates addon routes + nav items via Vite glob import:

`import.meta.glob("../addons/*/index.ts", { eager: true })`

If an addon’s frontend is missing or broken, it is skipped with a warning.

---

## 5) Addon Folder: Exact Required Contents

Required:
```
addons/<addon_id>/
├─ manifest.json
├─ backend/
│  └─ addon.py
└─ frontend/
   └─ index.ts
```

### 5.1 manifest.json
Minimal:
```json
{
  "id": "hello_world",
  "name": "Hello World",
  "version": "0.1.0",
  "description": "Example addon",
  "backend": "./backend",
  "frontend": "./frontend"
}
```

Rules:
- `id` MUST match `<addon_id>` folder name.
- `version` is a semver string.

---

## 6) Minimal “Start Over Clean” Plan

Phase 1: Backend boots without addons  
- `/api/health` ok
- `/api/addons` returns `[]`

Phase 2: Frontend boots without addons  
- Home/Settings/Addons pages render
- Addons page shows zero

Phase 3: Backend addon discovery works  
- add `hello_world` backend
- appears in `/api/addons`
- routes mounted under `/api/addons/hello_world`

Phase 4: Frontend addon sync + auto routing/nav  
- run sync script
- sidebar shows “Hello World”
- `/addons/hello_world` renders addon page

---

## 7) Guardrails

1. Folder name == addon id.  
2. Backend entrypoint always `backend/addon.py` exporting `addon`.  
3. Frontend entrypoint always `frontend/index.ts` exporting `meta/routes/navItem`.  
4. Backend mounts under `/api/addons/<id>`.  
5. Frontend routes under `/addons/<id>`.  
6. Frontend imports only from `src/addons/*` (synced boundary).  
7. Core never manually imports addon code; discovery does it.
