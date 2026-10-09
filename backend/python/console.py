import os
import re
import shlex

from accounts import ADMIN_USERNAME, reset_admin, revoke_sessions
from services import close_sessions_threadsafe, users

USERNAME = re.compile(r"[a-z0-9_.-]{3,32}")

HELP = """Commands:
  users                      list accounts
  adduser <name> [admin]     create an account; the user chooses a password at their first login
  resetuser <name>           the user chooses a new password at their next login
  resetadmin                 generate a new password for the admin account
  help                       show this text
  quit                       stop the server"""


def show_secret(heading: str, username: str, password: str) -> None:
    """Print a generated password once, then wipe the screen."""
    print(f"\n{heading}\n  username: {username}\n  password: {password}\nMemorize it: it will not be shown again.")
    try:
        input("Press Enter to continue (the screen will be cleared)... ")
    except EOFError:
        pass
    os.system("cls" if os.name == "nt" else "clear")


def run_command(line: str) -> bool:
    """Execute one console command; return False when the server should stop."""
    try:
        words = shlex.split(line)
    except ValueError as exc:
        print(f"Cannot read the command: {exc}")
        return True
    if not words:
        return True
    command, args = words[0].lower(), words[1:]
    if command in ("quit", "exit"):
        return False
    if command == "help":
        print(HELP)
    elif command == "users":
        for user in users.all():
            state = "disabled" if user.disabled else ("active" if user.opaque_record else "waiting for password")
            print(f"  {user.username:<20} {'admin' if user.is_admin else 'user':<6} {state}")
    elif command == "adduser" and args and args[0].lower() != ADMIN_USERNAME:
        name = args[0].lower()
        if not USERNAME.fullmatch(name):
            print("Usernames have 3 to 32 characters: letters, digits, '_', '.' or '-'.")
        elif users.by_username(name):
            print(f"'{name}' already exists.")
        else:
            users.create(name, is_admin=len(args) > 1 and args[1].lower() == "admin")
            print(f"Created '{name}'. They choose a password at their first login.")
    elif command == "resetuser" and args:
        user = users.by_username(args[0].lower())
        if user is None:
            print("No such user.")
        else:
            user.opaque_record, user.failed_attempts, user.locked_until = None, 0, None
            close_sessions_threadsafe(revoke_sessions(users.save(user).id))
            print(f"'{user.username}' chooses a new password at their next login.")
    elif command == "resetadmin":
        user, password = reset_admin()
        show_secret("The admin password was reset.", user.username, password)
    else:
        print("Unknown command or missing argument. Type 'help'.")
    return True


def run() -> bool:
    """Read commands until quit (True) or until there is no terminal to read from (False)."""
    print("Type 'help' for the commands.")
    while True:
        try:
            line = input()
        except EOFError:
            return False
        except KeyboardInterrupt:
            return True
        try:
            if not run_command(line):
                return True
        except Exception as exc:
            print(f"Command failed: {exc}")
