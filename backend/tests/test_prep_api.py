def test_run_then_latest_then_void_flow(client):
    r = client.post("/api/prep/run?order_id=1")
    assert r.status_code == 200
    run_id = r.json()["id"]
    assert r.json()["status"] == "active"

    r = client.get("/api/prep/latest?order_id=1")
    assert r.status_code == 200
    assert r.json()["id"] == run_id           # 指针指向最新有效单

    r = client.post(f"/api/prep/{run_id}/void")
    assert r.status_code == 200
    assert r.json()["voided_id"] == run_id
    assert r.json()["latest"] is None         # 无更早有效单 → 同时变空

    r = client.get("/api/prep/latest?order_id=1")
    assert r.status_code == 200
    assert r.json() is None                   # 不再隐式建单，不展示作废单

    r = client.get("/api/prep/shortages?order_id=1")
    body = r.json()
    assert body["run_id"] is None
    assert body["shortages"] == []
    assert body["stats"]["shortage_count"] == 0


def test_void_latest_falls_back_to_previous_active(client):
    a = client.post("/api/prep/run?order_id=1").json()["id"]
    b = client.post("/api/prep/run?order_id=1").json()["id"]
    assert client.get("/api/prep/latest?order_id=1").json()["id"] == b

    res = client.post(f"/api/prep/{b}/void").json()
    assert res["latest"]["id"] == a           # 作废最新 → 切到上一张仍有效的单
    assert client.get("/api/prep/latest?order_id=1").json()["id"] == a


def test_void_twice_is_409(client):
    run_id = client.post("/api/prep/run?order_id=1").json()["id"]
    assert client.post(f"/api/prep/{run_id}/void").status_code == 200
    r = client.post(f"/api/prep/{run_id}/void")
    assert r.status_code == 409               # 作废单禁止再操作


def test_void_unknown_run_is_404(client):
    assert client.post("/api/prep/999/void").status_code == 404


def test_run_unknown_order_is_404(client):
    assert client.post("/api/prep/run?order_id=999").status_code == 404


def test_generate_after_void_creates_new_run_not_overwrite(client):
    old = client.post("/api/prep/run?order_id=1").json()
    client.post(f"/api/prep/{old['id']}/void")
    new = client.post("/api/prep/run?order_id=1").json()
    # 生成永远是新单：新 id 更大，旧作废单原样保留。
    assert new["id"] > old["id"]
    assert new["status"] == "active"
    latest = client.get("/api/prep/latest?order_id=1").json()
    assert latest["id"] == new["id"]


def test_book_stock_unchanged_through_void(client, db_session):
    from app.models.models import Ingredient
    before = db_session.get(Ingredient, 1).stock_qty
    run_id = client.post("/api/prep/run?order_id=1").json()["id"]
    client.post(f"/api/prep/{run_id}/void")
    db_session.expire_all()
    assert db_session.get(Ingredient, 1).stock_qty == before  # 账面结存不被改小
    assert db_session.get(Ingredient, 1).reserved_qty == 0.0  # 预占已释放
