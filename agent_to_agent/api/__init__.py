from fastapi import APIRouter
from agent_to_agent.api.ata import router as auth_router

router = APIRouter()
router.include_router(auth_router, prefix="/ata", tags=["ata"])
