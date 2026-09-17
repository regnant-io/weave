"""Operator-only maintenance commands run inside the backend environment."""
from __future__ import annotations

import argparse
import getpass

from sqlalchemy.orm import Session

from .db import SessionLocal, init_db
from .models import User
from .security import hash_password


def provision_admin(db: Session, phone: str, password: str, email: str | None = None) -> User:
    phone = phone.strip()
    if len(phone) < 5 or len(phone) > 32:
        raise ValueError("phone must contain 5-32 characters")
    if len(password) < 12 or len(password) > 256:
        raise ValueError("admin password must contain 12-256 characters")

    user = db.query(User).filter(User.phone == phone).first()
    if user is None:
        user = User(phone=phone)
    user.password_hash = hash_password(password)
    user.role = "admin"
    user.trust_tier = "institutional"
    user.phone_verified = True
    if email:
        user.email = email.strip()[:320]
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _create_admin(args: argparse.Namespace) -> int:
    password = getpass.getpass("New admin password: ")
    repeat = getpass.getpass("Repeat password: ")
    if password != repeat:
        raise SystemExit("passwords do not match")
    init_db()
    db = SessionLocal()
    try:
        user = provision_admin(db, args.phone, password, args.email)
        print(f"Admin ready: {user.phone}")
    finally:
        db.close()
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    create = sub.add_parser("create-admin", help="create or rotate an explicit admin account")
    create.add_argument("--phone", required=True)
    create.add_argument("--email")
    create.set_defaults(handler=_create_admin)
    args = parser.parse_args()
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
