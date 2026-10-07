"""备料单作废语义测试（SQLite 内存库，不依赖 Postgres）。"""
import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models.models import BomLine, Dish, Ingredient, KitchenOrder, OrderLine, PrepRun
from app.services import prep_service
from app.services.prep_service import PrepError


@pytest.fixture()
def db_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = factory()
    dish = Dish(code="D1", name="套餐")
    db.add(dish); db.flush()
    # 肉库存 10kg；BOM 每份 1kg，订单 40 份 → 需求 40，预占 10，缺料 30。
    meat = Ingredient(code="M", name="肉", unit="kg", stock_qty=10.0, reserved_qty=0.0)
    db.add(meat); db.flush()
    db.add(BomLine(dish_id=dish.id, ingredient_id=meat.id, qty_per_portion=1.0))
    order = KitchenOrder(code="KO-1", outlet="城西门店", status="open")
    db.add(order); db.flush()
    db.add(OrderLine(order_id=order.id, dish_id=dish.id, portions=40))
    db.commit()
    yield factory, meat.id, order.id
    db.close()
    engine.dispose()


@pytest.fixture()
def db(db_factory):
    factory, _iid, _oid = db_factory
    session = factory()
    yield session
    session.close()


def _reserved(db, ing_id):
    return db.get(Ingredient, ing_id).reserved_qty


def _stock(db, ing_id):
    return db.get(Ingredient, ing_id).stock_qty


def test_generate_reserves_without_touching_stock(db, db_factory):
    _f, ing_id, order_id = db_factory
    run = prep_service.generate_prep_run(db, order_id)
    data = json.loads(run.result_json)
    line = data["prep_lines"][0]
    assert line["need_qty"] == 40
    assert line["reserved_qty"] == 10          # 预占 min(need, stock)
    assert _stock(db, ing_id) == 10.0          # 账面结存没被改小
    assert _reserved(db, ing_id) == 10.0
    assert run.status == "active"


def test_void_releases_reservation_but_keeps_stock(db, db_factory):
    _f, ing_id, order_id = db_factory
    run = prep_service.generate_prep_run(db, order_id)
    prep_service.void_prep_run(db, run.id)
    assert _stock(db, ing_id) == 10.0          # 作废不是出库：结存不变
    assert _reserved(db, ing_id) == 0.0        # 预占在作废成功后才释放
    assert db.get(PrepRun, run.id).status == "void"
    assert db.get(PrepRun, run.id).voided_at is not None


def test_latest_falls_back_to_previous_active_run(db, db_factory):
    _f, _i, order_id = db_factory
    run1 = prep_service.generate_prep_run(db, order_id)
    run2 = prep_service.generate_prep_run(db, order_id)
    assert prep_service.latest_active_run(db, order_id).id == run2.id
    prep_service.void_prep_run(db, run2.id)
    # 切到上一张仍有效的单，而不是继续停在作废单上
    assert prep_service.latest_active_run(db, order_id).id == run1.id


def test_latest_empty_when_all_void_and_shortages_empty(db, db_factory):
    _f, _i, order_id = db_factory
    run = prep_service.generate_prep_run(db, order_id)
    prep_service.void_prep_run(db, run.id)
    assert prep_service.latest_active_run(db, order_id) is None


def test_regenerate_after_void_inserts_new_run_voided_row_immutable(db, db_factory):
    _f, _i, order_id = db_factory
    run1 = prep_service.generate_prep_run(db, order_id)
    prep_service.void_prep_run(db, run1.id)
    snapshot = db.get(PrepRun, run1.id).result_json

    run2 = prep_service.generate_prep_run(db, order_id)  # 再点生成
    assert run2.id != run1.id
    assert run2.status == "active"
    voided = db.get(PrepRun, run1.id)
    assert voided.status == "void"                        # 作废单没被新生成覆盖/改字
    assert voided.result_json == snapshot
    assert prep_service.latest_active_run(db, order_id).id == run2.id


def test_cannot_revoid(db, db_factory):
    _f, _i, order_id = db_factory
    run = prep_service.generate_prep_run(db, order_id)
    prep_service.void_prep_run(db, run.id)
    with pytest.raises(PrepError) as ei:
        prep_service.void_prep_run(db, run.id)
    assert ei.value.status_code == 409


def test_void_failure_rolls_back_pointer_and_status(db, db_factory):
    _f, ing_id, order_id = db_factory
    run = prep_service.generate_prep_run(db, order_id)
    # 人为把占用账改乱，模拟作废中途失败：占用数对不上。
    db.get(Ingredient, ing_id).reserved_qty = 0.0
    db.commit()
    with pytest.raises(PrepError):
        prep_service.void_prep_run(db, run.id)
    db.rollback()
    assert db.get(PrepRun, run.id).status == "active"     # 单状态退回
    assert _reserved(db, ing_id) == 0.0                   # 也没有被部分释放
    assert prep_service.latest_active_run(db, order_id).id == run.id  # 指针退回


def test_voiding_latest_does_not_touch_earlier_run_or_its_reservation(db, db_factory):
    _f, ing_id, order_id = db_factory
    run1 = prep_service.generate_prep_run(db, order_id)
    run2 = prep_service.generate_prep_run(db, order_id)
    assert _reserved(db, ing_id) == 20.0
    r1_snapshot = db.get(PrepRun, run1.id).result_json

    prep_service.void_prep_run(db, run2.id)

    assert _reserved(db, ing_id) == 10.0                  # 只剩更早单 run1 的占用
    r1 = db.get(PrepRun, run1.id)
    assert r1.status == "active"                          # 不是当前这张的更早单没被改字
    assert r1.result_json == r1_snapshot


# ---- API 层：缺料贴/统计跟随有效单 ----

@pytest.fixture()
def client(db_factory):
    from app.main import app
    from app.database import get_db
    factory, _i, _o = db_factory

    def _get_db():
        s = factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _get_db
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_shortages_hides_void_and_void_endpoint_switches_latest(client, db_factory):
    _f, _i, order_id = db_factory
    r1 = client.post(f"/api/prep/run?order_id={order_id}").json()
    r2 = client.post(f"/api/prep/run?order_id={order_id}").json()
    assert client.get("/api/prep/latest").json()["id"] == r2["id"]

    resp = client.post(f"/api/prep/{r2['id']}/void")
    assert resp.status_code == 200
    body = resp.json()
    assert body["voided_id"] == r2["id"]
    assert body["latest"]["id"] == r1["id"]               # 直接告诉前端切到上一张

    latest = client.get("/api/prep/latest").json()
    assert latest["id"] == r1["id"]
    sh = client.get("/api/prep/shortages").json()
    assert sh["run_id"] == r1["id"]
    assert len(sh["shortages"]) == 1                      # 缺料贴跟随有效单，不停作废单


def test_api_void_all_leaves_three_views_empty(client, db_factory):
    _f, _i, order_id = db_factory
    r = client.post(f"/api/prep/run?order_id={order_id}").json()
    client.post(f"/api/prep/{r['id']}/void")
    assert client.get("/api/prep/latest").json() is None
    sh = client.get("/api/prep/shortages").json()
    assert sh == {"order_id": 1, "run_id": None, "shortages": [], "stats": {}}
