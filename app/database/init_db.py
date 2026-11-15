from .base import Base, engine
from sqlalchemy import inspect, text
from . import models  # noqa: F401


def init_db() -> None:
    Base.metadata.create_all(bind=engine)

    columns = {column["name"] for column in inspect(engine).get_columns("conversations")}
    if "deepseek_parent_message_id" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text("ALTER TABLE conversations ADD COLUMN deepseek_parent_message_id INTEGER")
            )
