from __future__ import annotations

from fastapi import APIRouter


def build_architecture_router() -> APIRouter:
    router = APIRouter(tags=["architecture"])

    @router.get("/architecture")
    def get_architecture() -> dict[str, object]:
        return {
            "target_architecture": "core-supervisor-nodes",
            "status": "foundation",
            "workload_boundary": {
                "scheduler": {
                    "owner_domain": "core",
                    "role": "admission_and_orchestration",
                    "docs_path": "docs/core/scheduler",
                    "notes": [
                        "Core admits work, manages queue state, and coordinates lease/orchestration decisions.",
                        "The scheduler does not define host-local runtime ownership for execution.",
                    ],
                },
                "execution_surfaces": [
                    {
                        "id": "workers",
                        "owner_domain": "supervisor",
                        "status": "compatibility_runtime_helper",
                        "docs_path": "docs/supervisor",
                        "current_module_paths": ["backend/app/system/worker", "backend/app/system/runtime"],
                        "notes": [
                            "Current worker runners execute leased work outside the Core scheduler admission loop.",
                            "Host-local worker/process execution management is being moved behind Supervisor ownership.",
                        ],
                    },
                    {
                        "id": "supervisor",
                        "status": "host_runtime_authority",
                        "docs_path": "docs/supervisor",
                        "notes": [
                            "Supervisor is the target boundary for host-local runtime authority.",
                        ],
                    },
                    {
                        "id": "nodes",
                        "status": "canonical_external_execution_layer",
                        "docs_path": "docs/nodes",
                        "notes": [
                            "Nodes are the canonical external execution model in the migration structure.",
                        ],
                    },
                ],
            },
            "extension_boundaries": {
                "embedded_addons": {
                    "owner_domain": "core",
                    "execution_model": "in_process",
                    "docs_path": "docs/addons/embedded",
                    "notes": [
                        "Embedded addons stay inside the Core runtime and are part of the local Core extension surface.",
                        "MQTT policy and coordination for embedded addons remain Core-owned.",
                    ],
                },
                "host_local_runtime": {
                    "owner_domain": "supervisor",
                    "execution_model": "host_local_realization",
                    "docs_path": "docs/supervisor",
                    "notes": [
                        "Supervisor realizes host-local runtime intent written by Core.",
                        "Standalone addon runtime artifacts remain compatibility-era material, not the canonical external extension model.",
                    ],
                },
                "external_functionality": {
                    "canonical_domain": "nodes",
                    "execution_model": "trusted_external_systems",
                    "docs_path": "docs/nodes",
                    "notes": [
                        "New external functionality should be modeled as Nodes rather than standalone addons.",
                        "Core remains the MQTT authority and trust/governance authority for node connectivity.",
                    ],
                },
            },
            "domains": [
                {
                    "id": "core",
                    "name": "Core",
                    "role": "control_plane",
                    "module_paths": ["backend/app/core", "backend/app/api", "backend/app/system"],
                    "docs_path": "docs/core",
                    "routes": ["/api/architecture"],
                },
                {
                    "id": "supervisor",
                    "name": "Supervisor",
                    "role": "host_runtime_authority",
                    "module_paths": ["backend/app/supervisor", "backend/synthia_supervisor"],
                    "docs_path": "docs/supervisor",
                    "routes": ["/api/supervisor/health", "/api/supervisor/info", "/api/supervisor/admission"],
                },
                {
                    "id": "nodes",
                    "name": "Nodes",
                    "role": "external_execution_layer",
                    "module_paths": ["backend/app/nodes", "backend/app/system/onboarding"],
                    "docs_path": "docs/nodes",
                    "routes": ["/api/nodes", "/api/nodes/{node_id}"],
                },
            ],
        }

    return router
