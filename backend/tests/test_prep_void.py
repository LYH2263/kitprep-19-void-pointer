import json

import pytest
from sqlalchemy import select

from app.models.models import Ingredient, PrepRun
from app.services import prep_service as svc


def _stock(db, ingredient_id=1):
    return db.get(Ingredient, ingredient_id)


def test_create_reserves_without_touching_book_stock(db_session):
    run = svc.create_run(db_session, 1)
    ing = _stock(db_session)
    # 需求 40*0.25 = 10，库存恰为 10 → 全额预占。
    assert ing.stock_qty == 10.0          # 账面结存不被改小
    assert ing.reserved_qty == 10.0       # 占用列被预占
    assert ing.available_qty == 0.0
    assert run.status == "active"
    payload = json.loads(run.result_json)
    assert payload["prep_lines"][0]["reserved_qty"] == 10.0
    assert payload["shortages"] == []


def test_shortage_uses_available_after_reservation(db_session):
    svc.create_run(db_session, 1)          # 第一张预占走 10
    second = svc.create_run(db_session, 1) # 再生成：可用已为 0
    ing = _stock(db_session)
    payload = json.loads(second.result_json)
    # 账面仍是 10；第二张在可用 0 时只预占 0，故累计占用仍为 10，新单需求 10 全部缺料。
    assert ing.stock_qty == 10.0
    assert ing.reserved_qty == 10.0
    assert payload["prep_lines"][0]["reserved_qty"] == 0.0
    assert payload["shortages"][0]["shortage"] == 10.0


def test_void_releases_only_own_reservation_and_book_untouched(db_session):
    # 库存 15、需求 10：第一张预占 10（剩可用 5），第二张预占 5（缺 5），累计占用 15。
    _stock(db_session).stock_qty = 15.0
    db_session.commit()
    first = svc.create_run(db_session, 1)
    second = svc.create_run(db_session, 1)
    ing = _stock(db_session)
    assert ing.reserved_qty == 15.0

    svc.void_run(db_session, first.id)     # 只作废第一张
    db_session.expire_all()
    ing = _stock(db_session)
    assert ing.stock_qty == 15.0           # 账面结存绝不因作废改小
    # 只释放第一张自己的 10；第二张仍 active，其预占 5 原样保留。
    assert ing.reserved_qty == 5.0
    assert db_session.get(PrepRun, first.id).status == "void"
    assert db_session.get(PrepRun, second.id).status == "active"
    assert svc.get_active_latest(db_session, 1).id == second.id


def test_latest_pointer_falls_back_then_empties(db_session):
    first = svc.create_run(db_session, 1)
    second = svc.create_run(db_session, 1)
    assert svc.get_active_latest(db_session, 1).id == second.id

    svc.void_run(db_session, second.id)    # 作废最新 → 回退到上一张有效单
    assert svc.get_active_latest(db_session, 1).id == first.id

    svc.void_run(db_session, first.id)     # 再作废 → 指针为空
    assert svc.get_active_latest(db_session, 1) is None
    # 作废单记录仍在，只是不再是指针。
    assert db_session.get(PrepRun, second.id).status == "void"


def test_double_void_conflicts_and_changes_nothing(db_session):
    run = svc.create_run(db_session, 1)
    svc.void_run(db_session, run.id)
    reserved_after_first = _stock(db_session).reserved_qty

    with pytest.raises(svc.PrepConflict):
        svc.void_run(db_session, run.id)   # 重复作废 → 409
    assert _stock(db_session).reserved_qty == reserved_after_first
    assert db_session.get(PrepRun, run.id).status == "void"


def test_void_failure_rolls_back_status_and_reservation(db_session, monkeypatch):
    run = svc.create_run(db_session, 1)
    original_commit = db_session.commit

    def failing_commit():
        # 模拟提交瞬间失败（如约束/连接错误）。
        raise RuntimeError("commit boom")

    monkeypatch.setattr(db_session, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        svc.void_run(db_session, run.id)

    monkeypatch.setattr(db_session, "commit", original_commit)
    db_session.rollback()
    # 状态与占用全部退回：仍是 active，预占仍在。
    db_session.expire_all()
    assert db_session.get(PrepRun, run.id).status == "active"
    assert _stock(db_session).reserved_qty == 10.0
    # 指针依旧指向这张未作废的单。
    assert svc.get_active_latest(db_session, 1).id == run.id


def test_void_missing_run_is_404(db_session):
    with pytest.raises(svc.PrepNotFound):
        svc.void_run(db_session, 999)


def test_earlier_run_result_not_rewritten_on_void(db_session):
    first = svc.create_run(db_session, 1)
    second = svc.create_run(db_session, 1)
    first_json_before = db_session.get(PrepRun, first.id).result_json

    svc.void_run(db_session, second.id)
    # 不是当前这张的更早单，其内容一字不改。
    assert db_session.get(PrepRun, first.id).result_json == first_json_before
    assert db_session.get(PrepRun, first.id).status == "active"
