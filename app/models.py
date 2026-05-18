from dataclasses import dataclass, field
from typing import Optional


@dataclass
class User:
    email: str
    verified: bool = False
    created_at: str = ""

    @classmethod
    def from_row(cls, row):
        return cls(
            email=row["email"],
            verified=bool(row["verified"]),
            created_at=row["created_at"],
        )


@dataclass
class VerificationToken:
    email: str
    token: str
    expires_at: str
    used: bool = False
    id: Optional[int] = None

    @classmethod
    def from_row(cls, row):
        return cls(
            id=row["id"],
            email=row["email"],
            token=row["token"],
            expires_at=row["expires_at"],
            used=bool(row["used"]),
        )


@dataclass
class ApiKey:
    key: str
    email: str
    name: str = "default"
    created_at: str = ""

    @classmethod
    def from_row(cls, row):
        return cls(
            key=row["key"],
            email=row["email"],
            name=row.get("name", "default"),
            created_at=row["created_at"],
        )


@dataclass
class Site:
    shortcode: str
    email: str
    title: str = ""
    size_bytes: int = 0
    created_at: str = ""

    @classmethod
    def from_row(cls, row):
        return cls(
            shortcode=row["shortcode"],
            email=row["email"],
            title=row.get("title", ""),
            size_bytes=row["size_bytes"],
            created_at=row["created_at"],
        )
