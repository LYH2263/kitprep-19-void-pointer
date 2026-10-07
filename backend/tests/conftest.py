import os

# 必须在导入 app.* 之前：模块级 engine 会按 DATABASE_URL 选择驱动，测试用 sqlite，免依赖 psycopg2。
os.environ.setdefault("DATABASE_URL", "sqlite://")

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.models.models import BomLine, Dish, Ingredient, KitchenOrder, OrderLine


@pytest.fixture()
def db_session():
    # 单连接内存库：StaticPool 让所有会话共享同一份库结构与数据。
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    db = Session()
    seed(db)
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session):
    from fastapi.testclient import TestClient
    from app.main import app

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    # 不进入 with：避免触发 lifespan 去连 Postgres。
    c = TestClient(app)
    try:
        yield c
    finally:
        app.dependency_overrides.clear()


def seed(db):
    """一张订单：红烧肉40份（五花肉单耗0.25 → 需求10）。"""
    dish = Dish(code="D-HS", name="红烧肉套餐", portion_unit="份")
    db.add(dish); db.flush()
    pork = Ingredient(code="I-PR", name="五花肉", unit="kg", stock_qty=10.0, reserved_qty=0.0)
    db.add(pork); db.flush()
    db.add(BomLine(dish_id=dish.id, ingredient_id=pork.id, qty_per_portion=0.25))
    order = KitchenOrder(code="KO-1", outlet="测试门店", status="open")
    db.add(order); db.flush()
    db.add(OrderLine(order_id=order.id, dish_id=dish.id, portions=40))
    db.commit()
