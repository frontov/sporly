from __future__ import annotations

from pathlib import Path

from app.config import settings
from app.partners import PartnerRegistry
from app.sessions import SearchSessionStore
from app.storage import Database


database = Database(
    path=Path(settings.database_path),
    legacy_data_dir=Path(settings.database_path).parent,
)
partner_registry = PartnerRegistry(settings.partner_config_path, database)
search_sessions = SearchSessionStore()
