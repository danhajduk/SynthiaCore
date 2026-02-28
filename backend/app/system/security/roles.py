from __future__ import annotations

from enum import Enum


class AuthRole(str, Enum):
    admin = "admin"
    service = "service"
    guest = "guest"
