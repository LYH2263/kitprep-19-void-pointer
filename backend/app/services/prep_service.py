"""备料单编排：生成即预占库存（不动账面结存），作废释放预占。

约束：
- 生成备料单不做领料出库，Ingredient.stock_qty（账面结存）永不被备料单改小；
  被锁住的量记在 Ingredient.reserved_qty（占用列）。
- 最新一张已作废时禁止再生成：不允许把新结果写到作废单上/覆盖作废单。
- 作废只改目标单：释放本单预占、置 void，更早的单一个字都不改；任一步失败整体回滚。
"""
from __future__ import annotations

import json
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.models import BomLine, Ingredient, KitchenOrder, OrderLine, PrepRun
from app.services.bom_engine import explode_and_merge, result_to_dict

STATUS_ACTIVE = "active"
STATUS_VOID = "void"


class PrepError(Exception):
    """业务错误，status_code 供 API 层映射。"""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


def _load_inputs(db: Session, order_id: int) -> tuple[KitchenOrder, list[dict], list[dict], dict[int, Ingredient]]:
    order = db.get(KitchenOrder, order_id)
    if not order:
        raise PrepError(404, "订单不存在")
    ols = [
        {"dish_id": l.dish_id, "portions": l.portions}
        for l in db.scalars(select(OrderLine).where(OrderLine.order_id == order_id)).all()
    ]
    bom = [
        {"dish_id": b.dish_id, "ingredient_id": b.ingredient_id, "qty_per_portion": b.qty_per_portion}
        for b in db.scalars(select(BomLine)).all()
    ]
    ingredients = {i.id: i for i in db.scalars(select(Ingredient)).all()}
    return order, ols, bom, ingredients


def _build_result(db: Session, order_id: int) -> tuple[KitchenOrder, dict, dict[int, float]]:
    order, ols, bom, ing_rows = _load_inputs(db, order_id)
    ings = {i.id: {"code": i.code, "name": i.name, "unit": i.unit, "stock_qty": i.stock_qty}
            for i in ing_rows.values()}
    lines = explode_and_merge(ols, bom, ings)
    result = result_to_dict(lines)
    # 预占量：账面有多少就锁多少（need 与 stock 取小），只动占用列，不动 stock_qty。
    reserved_by_ing: dict[int, float] = {}
    for line in result["prep_lines"]:
        reserved = round(min(line["need_qty"], line["stock_qty"]), 3)
        line["reserved_qty"] = reserved
        reserved_by_ing[line["ingredient_id"]] = reserved
    result["stats"]["reserved_total_qty"] = round(sum(reserved_by_ing.values()), 3)
    result["order"] = {"id": order.id, "code": order.code, "outlet": order.outlet}
    return order, result, reserved_by_ing


def latest_active_run(db: Session, order_id: int) -> PrepRun | None:
    return db.scalars(
        select(PrepRun)
        .where(PrepRun.order_id == order_id, PrepRun.status == STATUS_ACTIVE)
        .order_by(PrepRun.id.desc())
    ).first()


def serialize_run(run: PrepRun) -> dict:
    data = json.loads(run.result_json)
    return {"id": run.id, "status": run.status, **data}


def generate_prep_run(db: Session, order_id: int) -> PrepRun:
    """生成一张新的有效备料单并预占库存。

    永远 INSERT 新单，绝不复用/覆盖任何已有单——尤其不能写进作废单：
    作废单 status/result_json 此后一个字都不改。
    """
    order, result, reserved_by_ing = _build_result(db, order_id)
    run = PrepRun(
        order_id=order_id,
        created_at=datetime.utcnow(),
        status=STATUS_ACTIVE,
        result_json=json.dumps(result, ensure_ascii=False),
    )
    db.add(run)
    db.flush()  # 先落单，再锁原料行加占用
    for iid, qty in sorted(reserved_by_ing.items()):
        if qty <= 0:
            continue
        ing = db.scalars(select(Ingredient).where(Ingredient.id == iid).with_for_update()).first()
        ing.reserved_qty = round((ing.reserved_qty or 0.0) + qty, 3)
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(run)
    return run


def void_prep_run(db: Session, run_id: int) -> PrepRun:
    """作废目标备料单：只释放本单预占、只改本单状态；任何一步失败全部回滚。"""
    run = db.scalars(select(PrepRun).where(PrepRun.id == run_id).with_for_update()).first()
    if not run:
        raise PrepError(404, "备料单不存在")
    if run.status == STATUS_VOID:
        raise PrepError(409, f"备料单 #{run.id} 已作废，不能重复作废或修改")

    data = json.loads(run.result_json)
    releases = sorted(
        ((l["ingredient_id"], float(l.get("reserved_qty", 0.0))) for l in data.get("prep_lines", [])),
        key=lambda x: x[0],
    )
    try:
        for iid, qty in releases:
            if qty <= 0:
                continue
            ing = db.scalars(select(Ingredient).where(Ingredient.id == iid).with_for_update()).first()
            if ing is None or (ing.reserved_qty or 0.0) + 1e-9 < qty:
                # 占用账对不上：宁可整单退回，也不把占用列扣成负数。
                raise PrepError(500, f"原料 #{iid} 占用数与备料单 #{run.id} 记录不符，作废已退回")
            ing.reserved_qty = round((ing.reserved_qty or 0.0) - qty, 3)

        run.status = STATUS_VOID
        run.voided_at = datetime.utcnow()
        db.commit()
    except Exception:
        # 任何一步失败：占用释放、状态翻转全部退回，指针（latest_active_run）自然也指回原单。
        db.rollback()
        raise
    db.refresh(run)
    return run
