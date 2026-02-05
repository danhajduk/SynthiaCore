from fastapi import APIRouter
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

# Import shared addon models from core backend
from app.addons.models import AddonMeta, BackendAddon

router = APIRouter()

@router.get("/status")
def status():
    return {"status": "ok", "addon": "hello_world"}

def _load_jobs_router():
    # Load router.py by path to avoid package import issues under dynamic discovery.
    router_path = Path(__file__).resolve().with_name("router.py")
    spec = spec_from_file_location("hello_world_router", router_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load router spec from {router_path}")
    mod = module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[attr-defined]
    jobs_router = getattr(mod, "router", None)
    if jobs_router is None:
        raise RuntimeError("router.py must export `router`")
    return jobs_router

router.include_router(_load_jobs_router())

addon = BackendAddon(
    meta=AddonMeta(
        id="hello_world",
        name="Hello World",
        version="0.1.0",
        description="Example addon used to validate the addon system.",
    ),
    router=router,
)
