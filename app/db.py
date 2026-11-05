"""Database tables. SQLite file at data/mbom.db (created on first run)."""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from sqlalchemy import (Boolean, DateTime, Float, ForeignKey, Integer, String, Text,
                        create_engine)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

DATA_DIR = Path(os.environ.get("MBOM_DATA_DIR", Path(__file__).resolve().parent.parent / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"
DATA_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

engine = create_engine(f"sqlite:///{DATA_DIR / 'mbom.db'}", connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# ---------------------------------------------------------------- users
class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(60), unique=True)
    full_name: Mapped[str] = mapped_column(String(120), default="")
    role: Mapped[str] = mapped_column(String(20))  # admin / engineering / purchase / sales
    password_hash: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False)


class Setting(Base):
    __tablename__ = "settings"
    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[float] = mapped_column(Float)


# ---------------------------------------------------------------- rate databases
class PlasticMaterial(Base):
    __tablename__ = "plastic_materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    sap_no: Mapped[str] = mapped_column(String(40), default="")
    manufacturer: Mapped[str] = mapped_column(String(120), default="")
    grade: Mapped[str] = mapped_column(String(160))
    family: Mapped[str] = mapped_column(String(40), default="")
    filler: Mapped[str] = mapped_column(String(20), default="")
    fill_pct: Mapped[str] = mapped_column(String(20), default="")
    cost_per_kg: Mapped[float] = mapped_column(Float, default=0)


class SheetMetalMaterial(Base):
    __tablename__ = "sheet_metal_materials"
    id: Mapped[int] = mapped_column(primary_key=True)
    division: Mapped[str] = mapped_column(String(120), default="")
    category: Mapped[str] = mapped_column(String(60), default="")
    sub_category: Mapped[str] = mapped_column(String(120), default="")
    grade: Mapped[str] = mapped_column(String(160))
    thickness_mm: Mapped[float | None] = mapped_column(Float, nullable=True)
    cost_per_kg: Mapped[float] = mapped_column(Float, default=0)


class MouldingMachine(Base):
    __tablename__ = "moulding_machines"
    id: Mapped[int] = mapped_column(primary_key=True)
    tonnage: Mapped[str] = mapped_column(String(20))
    machine_hour_rate: Mapped[float] = mapped_column(Float, default=0)


class RunnerSystem(Base):
    __tablename__ = "runner_systems"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    wastage: Mapped[float] = mapped_column(Float, default=0)


class Coating(Base):
    __tablename__ = "coatings"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(60))
    cost_per_sq_in: Mapped[float] = mapped_column(Float, default=0)


# ---------------------------------------------------------------- products and BOMs
class Product(Base):
    __tablename__ = "products"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    customer: Mapped[str] = mapped_column(String(160), default="")
    notes: Mapped[str] = mapped_column(Text, default="")
    usd_inr: Mapped[float] = mapped_column(Float, default=0)
    eur_inr: Mapped[float] = mapped_column(Float, default=0)
    edd_cost: Mapped[float] = mapped_column(Float, default=0)
    validation_cost: Mapped[float] = mapped_column(Float, default=0)
    # Assembly labour and line amortization ('Costing - Assy' sheet)
    asm_manpower: Mapped[float] = mapped_column(Float, default=0)
    asm_cycle_time_s: Mapped[float] = mapped_column(Float, default=0)
    asm_efficiency: Mapped[float] = mapped_column(Float, default=0.8)
    asm_man_hour_cost: Mapped[float] = mapped_column(Float, default=0)
    asm_line_cost_specific: Mapped[float] = mapped_column(Float, default=0)
    asm_line_cost_shared: Mapped[float] = mapped_column(Float, default=0)
    asm_line_utilization: Mapped[float] = mapped_column(Float, default=1)
    asm_amortization_volume: Mapped[float] = mapped_column(Float, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, onupdate=datetime.now)

    variants: Mapped[list[Variant]] = relationship(back_populates="product", cascade="all, delete-orphan",
                                                   order_by="Variant.position")
    lines: Mapped[list[BomLine]] = relationship(back_populates="product", cascade="all, delete-orphan",
                                                order_by="BomLine.position")


class Variant(Base):
    __tablename__ = "variants"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    part_no: Mapped[str] = mapped_column(String(80), default="")
    name: Mapped[str] = mapped_column(String(160))
    monthly_volume: Mapped[float] = mapped_column(Float, default=0)
    product: Mapped[Product] = relationship(back_populates="variants")


class BomLine(Base):
    __tablename__ = "bom_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    product_id: Mapped[int] = mapped_column(ForeignKey("products.id"))
    position: Mapped[int] = mapped_column(Integer, default=0)
    part_no: Mapped[str] = mapped_column(String(80), default="")
    description: Mapped[str] = mapped_column(String(200), default="")
    material_spec: Mapped[str] = mapped_column(String(200), default="")
    weight_g: Mapped[float] = mapped_column(Float, default=0)
    new_cop: Mapped[str] = mapped_column(String(10), default="")
    mat_type: Mapped[str] = mapped_column(String(60), default="")
    # How the part is costed: "manual" (MasterBOM columns), "plastic" or "sheet_metal"
    costing_method: Mapped[str] = mapped_column(String(20), default="manual")
    calc_inputs_json: Mapped[str] = mapped_column(Text, default="{}")
    rm_rate_per_kg: Mapped[float] = mapped_column(Float, default=0)
    economy_factor: Mapped[float] = mapped_column(Float, default=0)
    process_cost: Mapped[float] = mapped_column(Float, default=0)
    heat_treatment: Mapped[float] = mapped_column(Float, default=0)
    coating_cost: Mapped[float] = mapped_column(Float, default=0)
    bop_cost: Mapped[float] = mapped_column(Float, default=0)
    supplier: Mapped[str] = mapped_column(String(160), default="")
    tooling_description: Mapped[str] = mapped_column(String(200), default="")
    cavities: Mapped[float] = mapped_column(Float, default=0)
    cycle_time_s: Mapped[float] = mapped_column(Float, default=0)
    tool_owner: Mapped[str] = mapped_column(String(20), default="")
    tooling_cost: Mapped[float] = mapped_column(Float, default=0)
    fixture_gauge_cost: Mapped[float] = mapped_column(Float, default=0)
    machinery_cost: Mapped[float] = mapped_column(Float, default=0)
    comments: Mapped[str] = mapped_column(Text, default="")

    product: Mapped[Product] = relationship(back_populates="lines")
    quantities: Mapped[list[LineQuantity]] = relationship(back_populates="line", cascade="all, delete-orphan")
    attachments: Mapped[list[Attachment]] = relationship(back_populates="line", cascade="all, delete-orphan")

    @property
    def calc_inputs(self) -> dict:
        try:
            return json.loads(self.calc_inputs_json or "{}")
        except ValueError:
            return {}

    def qty_for(self, variant_id: int) -> float:
        return next((q.qty for q in self.quantities if q.variant_id == variant_id), 0.0)


class LineQuantity(Base):
    __tablename__ = "line_quantities"
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("bom_lines.id"))
    variant_id: Mapped[int] = mapped_column(ForeignKey("variants.id", ondelete="CASCADE"))
    qty: Mapped[float] = mapped_column(Float, default=0)
    line: Mapped[BomLine] = relationship(back_populates="quantities")


class Attachment(Base):
    """A drawing or quotation file stored against a BOM line."""
    __tablename__ = "attachments"
    id: Mapped[int] = mapped_column(primary_key=True)
    line_id: Mapped[int] = mapped_column(ForeignKey("bom_lines.id"))
    filename: Mapped[str] = mapped_column(String(255))
    stored_name: Mapped[str] = mapped_column(String(255))
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    uploaded_by: Mapped[str] = mapped_column(String(60), default="")
    uploaded_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    line: Mapped[BomLine] = relationship(back_populates="attachments")


def init_db() -> None:
    Base.metadata.create_all(engine)
