from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.services import prep_service
from app.services.prep_service import PrepError, latest_active_run, serialize_run
router = APIRouter(prefix="/prep", tags=["prep"])


@router.post("/run")
def run_prep(order_id: int = 1, db: Session = Depends(get_db)):
    """生成新备料单（预占库存，不做出库）。永远插新单，不覆盖任何已有单。"""
    try:
        run = prep_service.generate_prep_run(db, order_id)
    except PrepError as e:
        raise HTTPException(e.status_code, e.detail)
    return serialize_run(run)


@router.get("/latest")
def latest(order_id: int = 1, db: Session = Depends(get_db)):
    """只返回最新一张有效单；没有有效单则返回空，绝不自动生成、绝不返回作废单。"""
    run = latest_active_run(db, order_id)
    if not run:
        return None
    return serialize_run(run)


@router.post("/{run_id}/void")
def void_run(run_id: int, db: Session = Depends(get_db)):
    """作废备料单：释放本单预占（不动账面结存）。失败则指针与单状态整体退回。"""
    try:
        run = prep_service.void_prep_run(db, run_id)
    except PrepError as e:
        raise HTTPException(e.status_code, e.detail)
    fallback = latest_active_run(db, run.order_id)
    return {"voided_id": run.id, "latest": serialize_run(fallback) if fallback else None}


@router.get("/shortages")
def shortages(order_id: int = 1, db: Session = Depends(get_db)):
    """缺料贴/统计一律跟随最新有效单；无有效单时为空。"""
    run = latest_active_run(db, order_id)
    if not run:
        return {"order_id": order_id, "run_id": None, "shortages": [], "stats": {}}
    data = serialize_run(run)
    return {"order_id": order_id, "run_id": run.id, "shortages": data.get("shortages", []),
            "stats": data.get("stats", {})}
