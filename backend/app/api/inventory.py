from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Ingredient
router = APIRouter(prefix="/inventory", tags=["inventory"])

@router.get("")
def list_inventory(db: Session = Depends(get_db)):
    # stock_qty=账面结存（不被备料/作废改小）；reserved_qty=有效备料单的预占；可用=二者之差。
    return [{"id": r.id, "code": r.code, "name": r.name, "unit": r.unit,
             "stock_qty": r.stock_qty, "reserved_qty": r.reserved_qty or 0.0,
             "available_qty": round((r.stock_qty or 0.0) - (r.reserved_qty or 0.0), 3)}
            for r in db.scalars(select(Ingredient).order_by(Ingredient.id)).all()]
