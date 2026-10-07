from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.services import prep_service as svc

router = APIRouter(prefix="/prep", tags=["prep"])

EMPTY_STATS = {"ingredient_count": 0, "shortage_count": 0, "total_shortage_qty": 0}


@router.post("/run")
def run_prep(order_id: int = 1, db: Session = Depends(get_db)):
    """生成一张新的有效备料单并预占库存。始终新建，不覆盖任何既有单（含作废单）。"""
    try:
        run = svc.create_run(db, order_id)
    except svc.PrepNotFound as e:
        raise HTTPException(404, str(e))
    return svc.serialize(run)


@router.get("/latest")
def latest(order_id: int = 1, db: Session = Depends(get_db)):
    """最新"有效"单指针。作废后若无更早有效单则返回 null（不再隐式新建单据）。"""
    run = svc.get_active_latest(db, order_id)
    return svc.serialize(run) if run else None


@router.get("/shortages")
def shortages(order_id: int = 1, db: Session = Depends(get_db)):
    """缺料贴与统计只跟最新有效单走；没有有效单时三处同时为空。"""
    run = svc.get_active_latest(db, order_id)
    if not run:
        return {"order_id": order_id, "run_id": None, "shortages": [], "stats": dict(EMPTY_STATS)}
    data = svc.serialize(run)
    return {"order_id": order_id, "run_id": run.id,
            "shortages": data.get("shortages", []), "stats": data.get("stats", {})}


@router.post("/{run_id}/void")
def void_run(run_id: int, db: Session = Depends(get_db)):
    """作废指定备料单：只释放本单预占、不动账面结存；成功后指针落到上一张有效单或为空。

    失败（含重复作废）时单据状态、预占与指针全部保持原样。
    """
    try:
        svc.void_run(db, run_id)
    except svc.PrepNotFound as e:
        raise HTTPException(404, str(e))
    except svc.PrepConflict as e:
        raise HTTPException(409, str(e))
    except svc.PrepError as e:
        raise HTTPException(400, str(e))
    next_run = svc.get_active_latest(db, svc.get_run(db, run_id).order_id)
    return {
        "voided_id": run_id,
        "latest": svc.serialize(next_run) if next_run else None,
    }
