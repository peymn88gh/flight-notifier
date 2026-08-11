from __future__ import annotations

import argparse
import asyncio

from sqlalchemy import select

from app.core.phones import normalize_iranian_phone, redact_phone
from app.db.base import SessionFactory, create_schema
from app.db.models import User


async def _grant(phone: str) -> None:
    normalized = normalize_iranian_phone(phone)
    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.phone_e164 == normalized))
        if user:
            user.is_allowed = True
        else:
            session.add(User(phone_e164=normalized, is_allowed=True))
        await session.commit()
    print(f"Granted access to {redact_phone(normalized)}")


async def _revoke(phone: str) -> None:
    normalized = normalize_iranian_phone(phone)
    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.phone_e164 == normalized))
        if not user:
            raise SystemExit("Phone number is not provisioned")
        user.is_allowed = False
        await session.commit()
    print(f"Revoked access for {redact_phone(normalized)}")


async def _unbind(phone: str) -> None:
    normalized = normalize_iranian_phone(phone)
    async with SessionFactory() as session:
        user = await session.scalar(select(User).where(User.phone_e164 == normalized))
        if not user:
            raise SystemExit("Phone number is not provisioned")
        user.telegram_user_id = None
        user.telegram_chat_id = None
        user.telegram_username = None
        user.bound_at = None
        await session.commit()
    print(f"Removed Telegram binding for {redact_phone(normalized)}")


async def _list_users() -> None:
    async with SessionFactory() as session:
        users = list(await session.scalars(select(User).order_by(User.created_at)))
    for user in users:
        binding = str(user.telegram_user_id) if user.telegram_user_id else "unbound"
        state = "allowed" if user.is_allowed else "revoked"
        print(f"{redact_phone(user.phone_e164):14} {state:8} {binding}")


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="flight-notifier")
    subcommands = root.add_subparsers(dest="command", required=True)
    subcommands.add_parser("init-db")
    users = subcommands.add_parser("users")
    user_commands = users.add_subparsers(dest="user_command", required=True)
    for name in ("grant", "revoke", "unbind"):
        command = user_commands.add_parser(name)
        command.add_argument("phone")
    user_commands.add_parser("list")
    return root


def main() -> None:
    args = parser().parse_args()
    if args.command == "init-db":
        asyncio.run(create_schema())
        return
    operation = {
        "grant": _grant,
        "revoke": _revoke,
        "unbind": _unbind,
        "list": _list_users,
    }[args.user_command]
    asyncio.run(operation(args.phone) if hasattr(args, "phone") else operation())


if __name__ == "__main__":
    main()

