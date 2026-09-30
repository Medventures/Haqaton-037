from sqlmodel import Field, SQLModel

# TODO: Case, InterviewAnswer, Plan, Event tables (see CLAUDE.md).


class User(SQLModel, table=True):
    __tablename__ = "users"

    id: int | None = Field(default=None, primary_key=True)
    last_name: str = Field(max_length=100)
    first_name: str = Field(max_length=100)
    middle_name: str | None = Field(default=None, max_length=100)
    phone: str = Field(max_length=20, unique=True, index=True)
    password_hash: str = Field(max_length=255)
