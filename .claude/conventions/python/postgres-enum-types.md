---
title: "Use PostgreSQL ENUM column types (`sqlalchemy.dialects.postgresql.ENUM`) for enum-like columns — never plain string columns with a CHECK constraint or no constraint at all."
---

# Use PostgreSQL ENUM Types

A bare `String(20)` column accepts any string until your business code happens to look at it. ENUM is enforced at the DB layer, surfaces in introspection, and pairs with Python's `enum.StrEnum` cleanly.

- ALWAYS map enum-like columns to `ENUM(MyEnum, name="my_enum_name", create_type=False)`
- `create_type=False` because the migration owns the type creation
- AVOID `Mapped[str] = mapped_column(String(20))` for finite-domain values

## Bad

```python
class Message(Base):
    role: Mapped[str] = mapped_column(sa.String(20), nullable=False)
```

## Good

```python
from sqlalchemy.dialects.postgresql import ENUM

class MessageRole(enum.StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class Message(Base):
    role: Mapped[MessageRole] = mapped_column(
        ENUM(MessageRole, name="message_role", create_type=False),
        nullable=False,
    )
```
