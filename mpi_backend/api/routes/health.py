from fastapi import APIRouter
import logging

router = APIRouter(prefix="/health")
logger = logging.getLogger(__name__)


@router.get("")
async def get_health():
    logger.info("Health check endpoint called")
    return {"res": True}
