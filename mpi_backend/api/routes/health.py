from fastapi import APIRouter

router = APIRouter(prefix="/health")


@router.get("")
async def get_health():
    return {"res": True}
