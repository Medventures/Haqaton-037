"""Admin tool: create a curator account, or reset an existing curator's password.

Curators never come from app registration, and a parent account can't be turned into a curator
(one phone number, one role). Run from backend/ with DATABASE_URL pointing at the target database:

    python scripts/create_curator.py --phone "+7 701 000 00 00" --last-name Иванова --first-name Айгерим
"""

import argparse
import getpass
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
load_dotenv()

from sqlmodel import Session, select  # noqa: E402

from db import create_db_and_tables, engine  # noqa: E402
from models import User, UserRole  # noqa: E402
from services.auth import hash_password  # noqa: E402
from services.phone import normalize_phone  # noqa: E402

MIN_PASSWORD = 8


class CuratorError(Exception):
    pass


def upsert_curator(
    session: Session, phone: str, last_name: str, first_name: str, middle_name: str | None, password: str
) -> tuple[User, bool]:
    """Returns (user, created). An existing curator gets the new name and password."""
    if len(password) < MIN_PASSWORD:
        raise CuratorError(f"Пароль короче {MIN_PASSWORD} символов")
    phone = normalize_phone(phone)
    user = session.exec(select(User).where(User.phone == phone)).first()
    if user is not None and user.role != UserRole.curator:
        raise CuratorError(f"Номер +{phone} уже зарегистрирован как родитель. Для куратора нужен другой номер.")
    created = user is None
    if created:
        user = User(phone=phone, last_name="", first_name="", password_hash="", role=UserRole.curator)
    user.last_name, user.first_name, user.middle_name = last_name.strip(), first_name.strip(), middle_name
    user.password_hash = hash_password(password)
    session.add(user)
    session.commit()
    session.refresh(user)
    return user, created


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--phone", required=True)
    parser.add_argument("--last-name", required=True)
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--middle-name")
    parser.add_argument("--password", help="omit to be asked (keeps it out of shell history)")
    args = parser.parse_args()

    password = args.password
    if password is None:
        password = getpass.getpass("Пароль куратора: ")
        if getpass.getpass("Ещё раз: ") != password:
            sys.exit("Пароли не совпадают")

    create_db_and_tables()
    with Session(engine) as session:
        try:
            user, created = upsert_curator(
                session, args.phone, args.last_name, args.first_name, args.middle_name, password
            )
        except (CuratorError, ValueError) as e:
            sys.exit(str(e))
    print(f"{'Создан' if created else 'Обновлён'} куратор {user.last_name} {user.first_name}, телефон +{user.phone}")


if __name__ == "__main__":
    main()
