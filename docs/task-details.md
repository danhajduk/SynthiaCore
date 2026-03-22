## Task 320-332
Original task details preserved from the oversized node service-resolution planning block formerly embedded in `docs/New_tasks.txt`.

Alignment notes after code audit:

- Already implemented and should be reused:
  - generic service discovery route: `GET /api/services/resolve`
    - source: `backend/app/system/services/router.py`
  - persisted service catalog store and registration path
    - source: `backend/app/system/services/store.py`
    - source: `POST /api/services/register`
  - Core-issued service tokens
    - source: `POST /api/auth/service-token`
  - node budget policy, derived grants, and budget-bearing governance bundle
    - source: `backend/app/system/onboarding/node_budgeting.py`
    - source: `backend/app/system/onboarding/governance.py`
  - trusted-node budget policy read/refresh endpoints
    - source: `GET /api/system/nodes/budgets/policy/current`
    - source: `POST /api/system/nodes/budgets/policy/refresh`
  - trusted-node periodic usage summaries
    - source: `POST /api/system/nodes/budgets/usage-summary`
  - retained grant/revocation distribution
    - source: `backend/app/system/policy/router.py`
    - source: node-budget retained topics in `backend/app/api/system.py`

- Not yet implemented and still needed:
  - node-aware service resolution endpoint using node trust, governance, allowed providers/models, and effective grants
  - node-aware authorization endpoint that issues a short-lived service token after resolution and policy checks
  - service-catalog extension for richer provider/model/service metadata where needed by node resolution
  - filtered effective-budget selection for task-family/provider/model decisions
  - end-to-end tests and docs for the above flow

- Explicit normalization rules retained from the original task notes:
  - keep task family ids semantic and stable
  - do not encode provider or context inside canonical task-family ids
  - keep task family, provider access, and model policy as separate concepts
  - keep governance as the canonical Core-to-node policy carrier
  - keep Core out of the execution hot path

- Removed from the queue as already covered by current code/contracts:
  - creating a second standalone node grant protocol from scratch
  - creating a second budget usage reporting protocol from scratch
  - creating a second governance carrier for budget policy
  - recreating service catalog storage from scratch
  - recreating retained grant/revocation topic structure from scratch

## Task 753-762
Original task details preserved from the proxied UI contract planning block formerly embedded in `docs/New_tasks.txt`.

Active normalized queue entries:

- Task 753: Define frontend path-prefix behavior requirements
- Task 754: Define frontend API base-path requirements
- Task 755: Define websocket proxy compatibility requirements
- Task 756: Define forwarded-header contract from Core to proxied targets
- Task 757: Define runtime config injection contract for proxied UIs
- Task 758: Define redirect and link-generation behavior for proxied targets
- Task 759: Define compatibility requirements for SPA-based UIs
- Task 760: Define compatibility requirements for server-rendered UIs
- Task 761: Add compatibility validation checks in Core for proxied UI targets
- Task 762: Add proxied UI author documentation and examples

Preserved details:

- Task 753 covers frontend routing, static assets, internal navigation, redirects, and deep-link reload behavior for proxied UIs mounted under `/nodes/{node_id}/ui/` and `/addons/{addon_id}/`, with rules against hardcoded root paths and expectations for SPA basename or server root-path support.
- Task 754 covers browser API traffic staying on `/api/nodes/{node_id}/...` and `/api/addons/{addon_id}/...`, runtime config guidance for `public_ui_base_path`, `public_api_base_path`, `websocket_base_path`, and avoiding direct browser use of `ui_base_url` or LAN addresses.
- Task 755 covers websocket URL derivation from the Core public origin, path-prefix preservation, secure `wss` upgrades under HTTPS, and avoiding hardcoded internal websocket hosts.
- Task 756 covers the forwarded-header contract for `X-Forwarded-Host`, `X-Forwarded-Proto`, `X-Forwarded-Prefix`, plus contextual headers like `X-Hexe-Node-Id`, `X-Hexe-Addon-Id`, and `X-Request-Id`.
- Task 757 covers runtime config injection for proxied UIs, including public origin, UI/API base paths, websocket base path, mount kind, and mount id, delivered via inline JSON, dedicated config endpoint, or server-rendered template injection without leaking internal URLs.
- Task 758 covers redirect and link-generation behavior so upstreams preserve the Core public prefix, avoid redirecting to internal `ui_base_url`, and allow Core to rewrite unsafe `Location` headers when needed.
- Task 759 covers SPA-specific compatibility guidance for React/Vite-style apps, including configurable router basename, asset base path, runtime API base injection, nested-route reload support, and avoiding embedded direct hostnames.
- Task 760 covers server-rendered UI compatibility guidance for FastAPI, Flask, Django, and similar frameworks, including configurable root path, forwarded prefix support, relative links/redirects, and prefix-aware asset serving.
- Task 761 covers compatibility validation checks for proxied UI targets, including `ui_enabled`, valid/reachable `ui_base_url`, optional health checks, `ui_supports_prefix`, required metadata presence, fail-closed behavior, and operator-facing error reasons.
- Task 762 covers the author-facing documentation bundle: route model, path-prefix rules, API base rules, websocket behavior, forwarded headers, runtime config, redirect behavior, common failure cases, checklist, and examples.

## Task 763-776
Original task details preserved from the "FastAPI Implementation Skeleton for Proxied UIs" block formerly embedded in `docs/New_tasks.txt`.

Queue cleanup disposition:

- Removed from the active queue as superseded by completed Task 738-750 implementation work already landed in the repository.

Superseded mapping:

- Task 763 superseded by completed shared HTTP proxy service work (Tasks 739 and 743-744 alignment).
- Task 764 superseded by completed websocket proxy support work (Task 740).
- Task 765 remains active because unified target resolution is still a distinct follow-up concern.
- Task 766 superseded by completed node UI proxy route work (Task 741).
- Task 767 superseded by completed node API proxy route work (Task 742).
- Task 768 superseded by completed addon UI proxy route work (Task 743).
- Task 769 superseded by completed addon API proxy route work (Task 744).
- Task 770 superseded by completed websocket route support work (Task 740).
- Task 771 superseded by completed redirect/prefix-safe proxy response handling work already reflected in the current proxy stack.
- Task 772 superseded by completed timeout/failure configuration work (Task 746).
- Task 773 superseded by completed structured logging work (Task 749).
- Task 774 superseded by completed availability/fallback handling work (Tasks 746 and 748).
- Task 775 superseded by completed HTTP proxy validation coverage (Task 750).
- Task 776 superseded by completed websocket proxy validation coverage (Task 750).

Preserved implementation skeleton notes:

- The removed block described reusable HTTP and websocket proxy modules, target resolution, node/addon UI and API routes, redirect-safe handling, timeout and size limits, structured logging, availability/error handling, and integration tests.
- Those concepts remain represented in the current codebase and completion log; they were removed from `docs/New_tasks.txt` only because they duplicate already completed queue items.

## Task 777
Original task detail preserved from the trailing line formerly embedded in `docs/New_tasks.txt`.

- Task 777: update or create JSON schemas in `docs/json_schema/`

## Task 752.1
Original task detail preserved from the queue update added after queue normalization.

- Rework Edge Gateway to enforce single-origin Core routing.
- Target public architecture:
  - `/` -> Core UI on port 80
  - `/api/*` -> Core API on port 9001
  - `/nodes/*` -> node UI proxy on port 9001
  - `/addons/*` -> addon UI proxy on port 9001

Implementation note:

- Completed by switching Edge Gateway and Cloudflare rendering to a single canonical public hostname with reserved Core-owned path roots and path-based ingress routing.
