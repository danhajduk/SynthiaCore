from fastapi import APIRouter
from pydantic import BaseModel

# Import shared addon models from core backend
from app.addons.models import AddonMeta, BackendAddon

router = APIRouter()

@router.get("/status")
def status():
    return {"status": "ok", "addon": "hello_world"}

addon = BackendAddon(
    meta=AddonMeta(
        id="hello_world",
        name="Hello World",
        version="0.1.0",
        description="Example addon used to validate the addon system.",
    ),
    router=router,
)
