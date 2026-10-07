from database import Database
from models.user import User, UserDEM

db = Database(
    "postgresql+psycopg://postgres:password@localhost:5432/postgres",
)
users = UserDEM(db)


def main():
    db.create_tables()

    # generic Database for any model, UserDEM for User-specific operations
    user = users.create("Alice", "alice@example.com")
    print(db.get(User, user.id))
    print(users.find_by_email("alice@example.com"))

    users.rename(user, "Alice B")

    print(db.get_all(User))
    db.delete(user)

    db.close()


if __name__ == "__main__":
    main()