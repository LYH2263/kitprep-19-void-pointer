from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base

class Dish(Base):
    __tablename__ = "dishes"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    portion_unit: Mapped[str] = mapped_column(String(16), default="份")

class Ingredient(Base):
    __tablename__ = "ingredients"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    name: Mapped[str] = mapped_column(String(128))
    unit: Mapped[str] = mapped_column(String(16), default="kg")
    # 账面结存：只有真实入库/领料出库才会变动，备料预占与备料单作废都不得改小它。
    stock_qty: Mapped[float] = mapped_column(Float, default=0.0)
    # 预占占用：被仍有效（active）的备料单锁住、尚未真正出库的数量。
    reserved_qty: Mapped[float] = mapped_column(Float, default=0.0)

    @property
    def available_qty(self) -> float:
        return (self.stock_qty or 0.0) - (self.reserved_qty or 0.0)

class BomLine(Base):
    __tablename__ = "bom_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"))
    ingredient_id: Mapped[int] = mapped_column(ForeignKey("ingredients.id"))
    qty_per_portion: Mapped[float] = mapped_column(Float)

class KitchenOrder(Base):
    __tablename__ = "kitchen_orders"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    outlet: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32), default="open")

class OrderLine(Base):
    __tablename__ = "order_lines"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("kitchen_orders.id"))
    dish_id: Mapped[int] = mapped_column(ForeignKey("dishes.id"))
    portions: Mapped[int] = mapped_column(Integer)

class PrepRun(Base):
    __tablename__ = "prep_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("kitchen_orders.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # active=有效（其预占仍占用库存）；void=已作废（预占已释放，记录留痕但不可再改）。
    status: Mapped[str] = mapped_column(String(16), default="active")
    result_json: Mapped[str] = mapped_column(Text, default="{}")

    @property
    def is_void(self) -> bool:
        return self.status == "void"
