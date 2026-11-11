"""Shared request dependencies without importing an HTTP router."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.security import get_current_user
from app.users.models import User

# Finish the transaction before acknowledging a business mutation to the caller.
DB = Annotated[AsyncSession, Depends(get_db, scope="function")]
Actor = Annotated[User, Depends(get_current_user)]
