"""备料单领域服务。

关键不变量：
- 账面结存 Ingredient.stock_qty 只有真实入库/领料出库才会变；备料生成与作废都不动它。
- 备料生成只增加预占 reserved_qty（占用列），数量 = min(毛需求, 当前可用)。
- 备料作废不是领料出库：只把本单自己预占的那部分从 reserved_qty 释放，且与单据状态
  status=void 在同一事务提交；任何一步失败整体回滚，单据状态与占用、"最新指针"全部退回。
- "最新指针"不落地存储，由 active 单据实时派生，因此作废后天然落到上一张有效单或为空。
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import BomLine, Ingredient, KitchenOrder, OrderLine, PrepRun
from app.services.bom_engine import merge_needs

STATUS_ACTIVE = "active"
STATUS_VOID = "void"


class PrepError(Exception):
    """备料业务错误基类。"""


class PrepNotFound(PrepError):
    """单据/订单不存在（映射 404）。"""


class PrepConflict(PrepError):
    """状态冲突，例如重复作废（映射 409）。"""


def _load_order(db: Session, order_id: int) -> KitchenOrder:
    order = db.get(KitchenOrder, order_id)
    if not order:
        raise PrepNotFound("订单不存在")
    return order


def _lock_ingredients(db: Session, ingredient_ids: list[int]) -> dict[int, Ingredient]:
    """按 id 加行锁取原料，避免并发备料把同一份库存预占两次。"""
    if not ingredient_ids:
        return {}
    rows = db.scalars(
        select(Ingredient).where(Ingredient.id.in_(ingredient_ids)).order_by(Ingredient.id).with_for_update()
    ).all()
    return {i.id: i for i in rows}


def _build_result(db: Session, order: KitchenOrder) -> tuple[dict, dict[int, float], dict[int, Ingredient]]:
    """爆炸合并需求，按"账面-已预占"的可用量算缺料，并形成本单预占。

    返回 (结果payload, 预占明细, 已加锁原料映射)。
    """
    ols = [{"dish_id": l.dish_id, "portions": l.portions}
           for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order.id)).all()]
    bom = [{"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
           for b in db.scalars(select(BomLine)).all()]
    needs = merge_needs(ols, bom)

    ingredients = _lock_ingredients(db, sorted(needs))
    prep_lines, reservations = [], {}
    for iid, need_qty in sorted(needs.items()):
        ing = ingredients[iid]
        stock = float(ing.stock_qty or 0.0)
        available = stock - float(ing.reserved_qty or 0.0)
        # 本单只预占当前确实还能锁住的部分；缺料是相对"可用量"而言。
        reserve_qty = round(min(need_qty, max(available, 0.0)), 3)
        shortage = round(max(0.0, need_qty - max(available, 0.0)), 3)
        reservations[iid] = reserve_qty
        prep_lines.append({
            "ingredient_id": iid,
            "ingredient_code": ing.code,
            "ingredient_name": ing.name,
            "unit": ing.unit,
            "need_qty": round(need_qty, 3),
            "stock_qty": round(stock, 3),
            "available_qty": round(max(available, 0.0), 3),
            "reserved_qty": reserve_qty,
            "shortage": shortage,
        })

    result = {
        "order": {"id": order.id, "code": order.code, "outlet": order.outlet},
        "prep_lines": prep_lines,
        # 预占明细随单留痕，作废时只释放这里登记的数量，不碰其它单据。
        "reservations": [{"ingredient_id": iid, "qty": qty} for iid, qty in reservations.items()],
        "shortages": [l for l in prep_lines if l["shortage"] > 0],
        "stats": {
            "ingredient_count": len(prep_lines),
            "shortage_count": sum(1 for l in prep_lines if l["shortage"] > 0),
            "total_shortage_qty": round(sum(l["shortage"] for l in prep_lines), 3),
        },
    }
    return result, reservations, ingredients


def create_run(db: Session, order_id: int) -> PrepRun:
    """生成一张新的有效备料单（永远 INSERT，绝不覆盖既有单，含作废单）。"""
    order = _load_order(db, order_id)
    try:
        result, reservations, ingredients = _build_result(db, order)
        for iid, qty in reservations.items():
            ingredients[iid].reserved_qty = (ingredients[iid].reserved_qty or 0.0) + qty
        run = PrepRun(
            order_id=order_id,
            created_at=datetime.utcnow(),
            status=STATUS_ACTIVE,
            result_json=json.dumps(result, ensure_ascii=False),
        )
        db.add(run)
        db.commit()
        db.refresh(run)
        return run
    except PrepNotFound:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        raise


def get_active_latest(db: Session, order_id: int) -> PrepRun | None:
    """最新有效单指针：只认 active，按 id 倒序取第一张；没有就是 None。"""
    return db.scalars(
        select(PrepRun)
        .where(PrepRun.order_id == order_id, PrepRun.status == STATUS_ACTIVE)
        .order_by(PrepRun.id.desc())
    ).first()


def get_run(db: Session, run_id: int) -> PrepRun:
    run = db.get(PrepRun, run_id)
    if not run:
        raise PrepNotFound("备料单不存在")
    return run


def void_run(db: Session, run_id: int) -> PrepRun:
    """作废指定备料单：释放本单预占、置 void，同事务提交；失败整体回滚。

    只处理 run_id 命中的这一张；更早或更晚的其它单据及其 result_json 一律不改。
    """
    run = get_run(db, run_id)
    if run.status == STATUS_VOID:
        raise PrepConflict("备料单已作废，不能重复作废")
    try:
        payload = json.loads(run.result_json or "{}")
        reservations = {r["ingredient_id"]: float(r.get("qty", 0.0))
                        for r in payload.get("reservations", [])}
        ingredients = _lock_ingredients(db, sorted(reservations))
        for iid, qty in reservations.items():
            ing = ingredients.get(iid) or db.get(Ingredient, iid)
            if ing is None:
                raise PrepError(f"预占原料 {iid} 已不存在，无法安全释放")
            # 只释放本单登记的份额；钳制到 0 防止历史脏数据把占用减成负数。
            ing.reserved_qty = max(0.0, (ing.reserved_qty or 0.0) - qty)
        run.status = STATUS_VOID
        db.commit()
        db.refresh(run)
        return run
    except PrepConflict:
        db.rollback()
        raise
    except Exception:
        # 状态与预占同事务，任一失败全部退回，指针随之仍指向这张 active 单。
        db.rollback()
        raise


def serialize(run: PrepRun) -> dict:
    data = json.loads(run.result_json or "{}")
    return {"id": run.id, "status": run.status, "created_at": run.created_at.isoformat() if run.created_at else None, **data}
