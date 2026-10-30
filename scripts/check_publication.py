"""Reject private runtime files in the Git index; never print their contents."""
from pathlib import PurePosixPath
import re
import subprocess
import sys


def private_path(name: str) -> bool:
    path = PurePosixPath(name)
    if any(part in {'.research-artifacts', '.omc', '.codex', '.claude', '.worktrees', 'node_modules', '.next'}
           or part.startswith('.venv') for part in path.parts):
        return True
    leaf = path.name
    if leaf.startswith('.env') and leaf not in {'.env.example', '.env.enterprise.example'}:
        return True
    return bool(
        leaf in {'.DS_Store', 'auth.json', 'credentials.json'}
        or re.search(r'\.(db|sqlite3?)(-|$)|\.(pem|key|p12|pfx|tsbuildinfo)$', leaf)
        or name.startswith('docs/PAPER_TRIAL_')
    )


def main() -> int:
    names = subprocess.check_output(['git', 'ls-files', '-z']).decode().split('\0')
    blocked = [name for name in names if name and private_path(name)]
    for name in blocked:
        print(f'Private/runtime file is tracked: {name}', file=sys.stderr)
    if blocked:
        return 1
    print('No prohibited private/runtime paths in the Git index.')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
