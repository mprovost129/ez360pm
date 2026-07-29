"""Safe parsing for optional AI environment settings.

The AI assistant is optional. A malformed AI-only environment value must not stop
Django from importing settings when the feature is disabled. Parsing errors are
retained for Django's system-check framework so an enabled deployment still fails
closed with a clear configuration error.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation


_TRUE_VALUES = {"1", "true", "yes", "on"}
_FALSE_VALUES = {"0", "false", "no", "off"}


class AIEnvironment:
    def __init__(self, environ):
        self.environ = environ
        self.errors: list[str] = []

    def _raw(self, name):
        value = self.environ.get(name)
        return None if value is None else str(value).strip()

    def boolean(self, name, default=False, *, optional=False):
        raw = self._raw(name)
        if raw in {None, ""}:
            return None if optional else bool(default)
        normalized = raw.lower()
        if normalized in _TRUE_VALUES:
            return True
        if normalized in _FALSE_VALUES:
            return False
        self.errors.append(
            f"{name} must be one of: true, false, 1, 0, yes, no, on, or off."
        )
        return None if optional else bool(default)

    def integer(self, name, default):
        raw = self._raw(name)
        if raw in {None, ""}:
            return int(default)
        try:
            return int(raw)
        except (TypeError, ValueError):
            self.errors.append(f"{name} must be a whole number.")
            return int(default)

    def decimal(self, name, default):
        raw = self._raw(name)
        if raw in {None, ""}:
            return Decimal(str(default))
        try:
            return Decimal(raw)
        except (InvalidOperation, TypeError, ValueError):
            self.errors.append(f"{name} must be a valid decimal number.")
            return Decimal(str(default))

    def json_object(self, name, default=None):
        raw = self._raw(name)
        if raw in {None, ""}:
            return dict(default or {})
        try:
            value = json.loads(raw)
        except (json.JSONDecodeError, TypeError, ValueError):
            self.errors.append(f"{name} must contain valid JSON.")
            return dict(default or {})
        if not isinstance(value, dict):
            self.errors.append(f"{name} must decode to a JSON object.")
            return dict(default or {})
        return value
