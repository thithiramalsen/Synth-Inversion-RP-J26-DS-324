"""Prompt locally for a researcher password and print only its salted hash."""
from getpass import getpass
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'backend'))
from security import password_hash


def main():
    password = getpass('Choose a researcher password (at least 12 characters): ')
    if len(password) < 12:
        raise SystemExit('Use at least 12 characters')
    if getpass('Confirm password: ') != password:
        raise SystemExit('Passwords did not match')
    print('Paste this value into Render: SURVEY_RESEARCHER_PASSWORD_HASH')
    print(password_hash(password))


if __name__ == '__main__':
    main()
