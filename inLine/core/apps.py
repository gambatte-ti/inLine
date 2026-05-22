from typing import Any

from django.apps import AppConfig
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.signals import connection_created


class CoreConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "core"

    def ready(self) -> None:
        connection_created.connect(configure_sqlite_connection, dispatch_uid="core_configure_sqlite")


def configure_sqlite_connection(
    sender: type[BaseDatabaseWrapper],
    connection: BaseDatabaseWrapper,
    **kwargs: Any,
) -> None:
    if connection.vendor != "sqlite":
        return

    cursor_manager: Any = connection.cursor()
    with cursor_manager as cursor:
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=30000;")
        cursor.execute("PRAGMA temp_store=MEMORY;")
