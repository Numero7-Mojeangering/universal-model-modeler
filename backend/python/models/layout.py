from sqlalchemy import BigInteger, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base, Database


class EntityLayout(Base):
    """Display data only (position); kept apart from the entity model.

    The shape column is legacy: the shape now comes from the entity type's style.
    """

    __tablename__ = "entity_layout"

    entity_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("entity.id", ondelete="CASCADE"), primary_key=True, autoincrement=False
    )
    x: Mapped[float]
    y: Mapped[float]
    shape: Mapped[str] = mapped_column(Text, default="box")

    def __repr__(self) -> str:
        return f"EntityLayout(entity_id={self.entity_id}, x={self.x}, y={self.y}, shape={self.shape!r})"


class LayoutDEM:
    """Data Expert Manipulator for entity layouts."""

    def __init__(self, db: Database):
        self.db = db

    def all(self) -> list[EntityLayout]:
        return self.db.get_all(EntityLayout)

    def get(self, entity_id: int) -> EntityLayout | None:
        return self.db.get(EntityLayout, entity_id)

    def set(self, entity_id: int, x: float, y: float) -> EntityLayout:
        layout = self.db.get(EntityLayout, entity_id)
        if layout is None:
            return self.db.add(EntityLayout(entity_id=entity_id, x=x, y=y, shape="box"))
        layout.x, layout.y = x, y
        return self.db.update(layout)
