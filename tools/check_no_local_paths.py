#!/usr/bin/env python
"""Refuse to commit an absolute path out of somebody's home directory.

This exists because one nearly shipped. A UX review was written by agents that
had been handed absolute paths in their brief, and one survived into the prose:
a citation reading `C:\\Users\\<name>\\Documents\\...\\src\\00_head.html:336`,
staged for two public repositories. It was caught by hand, which is not a
control. This is the control.

What it costs to get wrong is small but permanent: a public repo that names your
account and your directory layout, in history, after the file is fixed.

Run it on what is staged (the pre-commit hook does this):

    python tools/check_no_local_paths.py --staged

or over every tracked file, which is what you want from CI or a build gate:

    python tools/check_no_local_paths.py --all

Exits non-zero on any hit and prints file:line. It is a gate, not a formatter -
it never edits anything.
"""

import re
import subprocess
import sys

# The patterns are assembled from fragments on purpose. Written out whole, this
# file would match itself on every run, and the usual fix - excluding the
# checker from its own scan - carves out the one file where a leak could then
# hide forever. Fragments keep the scan total.
_U = 'Users'
_H = 'home'

# An absolute path token: something starting at a filesystem root - a leading
# slash, a drive letter, or a UNC \\ - and running to whitespace or the
# punctuation that ends a path in prose.
#
# The first version matched the home segment directly, with a lookbehind to keep
# `docs/home/index.md` from firing. That lookbehind also required the segment to
# sit at the root, so every mount-prefixed form went straight through: the
# character before `/Users` in `/mnt/c/Users/name` is `c`, so WSL, Git Bash and
# Silverblue paths all committed clean. Git Bash renders `C:\Users\name` as
# `/c/Users/name`, which is to say the checker missed the shape of the exact
# incident it exists for.
#
# Anchoring on the token instead keeps relative paths out - `docs/home/x` never
# starts at a root, so it is never a token - without blinding the scan to a
# prefix in front of the part that names somebody.
_TOKEN = re.compile(r'(?:[A-Za-z]:|\\\\|(?<![A-Za-z0-9_.\-]))[\\/][^\s"\'`,;)\]}<>]*')
_HOME = re.compile(r'[\\/](' + _U + '|' + _H + r')[\\/]+([A-Za-z0-9_.\-]+)')


def _kind(token, segment):
    if re.match(r'[A-Za-z]:', token):
        return 'windows home'
    if token.startswith('\\\\'):
        return 'unc home'
    return 'macos home' if segment == _U else 'linux home'

# Obvious stand-ins in documentation. A real account name is the thing we are
# stopping; `/home/you/project` in a README is fine and should stay writable.
PLACEHOLDERS = {
    'you', 'user', 'username', 'name', 'me', 'someone', 'yourname',
    'your-name', 'your_name', '<user>', '<username>', '<you>', '<name>',
    'USER', 'USERNAME', 'HOME', 'root', 'runner', 'ubuntu',
}

SKIP_SUFFIXES = (
    '.png', '.jpg', '.jpeg', '.gif', '.webp', '.ico', '.pdf',
    '.woff', '.woff2', '.ttf', '.otf', '.eot',
    '.zip', '.gz', '.bz2', '.xz', '.7z',
    '.mp4', '.webm', '.mp3', '.wav',
)

MAX_BYTES = 8 * 1024 * 1024


def _git(args):
    return subprocess.run(['git'] + args, capture_output=True).stdout


def staged_paths():
    out = _git(['diff', '--cached', '--name-only', '--diff-filter=ACMR', '-z'])
    return [p.decode('utf-8') for p in out.split(b'\x00') if p]


def tracked_paths():
    out = _git(['ls-files', '-z'])
    return [p.decode('utf-8') for p in out.split(b'\x00') if p]


def staged_blob(path):
    return _git(['show', ':' + path])


def worktree_blob(path):
    try:
        with open(path, 'rb') as fh:
            return fh.read()
    except OSError:
        return b''


def scan(path, raw):
    """Yield (lineno, kind, offending_text) for each hit in one file."""
    if len(raw) > MAX_BYTES or b'\x00' in raw[:8192]:
        return
    try:
        text = raw.decode('utf-8')
    except UnicodeDecodeError:
        return  # not text; nothing readable to leak

    for lineno, line in enumerate(text.splitlines(), 1):
        for tok in _TOKEN.finditer(line):
            token = tok.group(0)
            for m in _HOME.finditer(token):
                if m.group(2) in PLACEHOLDERS:
                    continue
                yield lineno, _kind(token, m.group(1)), token
                break


def main(argv):
    mode = argv[1] if len(argv) > 1 else '--staged'
    if mode not in ('--staged', '--all'):
        print(__doc__)
        return 2

    if mode == '--staged':
        paths, read = staged_paths(), staged_blob
    else:
        paths, read = tracked_paths(), worktree_blob

    hits = []
    for path in paths:
        if path.lower().endswith(SKIP_SUFFIXES):
            continue
        for lineno, kind, text in scan(path, read(path)):
            hits.append((path, lineno, kind, text))

    if not hits:
        return 0

    print('')
    print('  Refusing: %d absolute home-directory path%s in %s content.'
          % (len(hits), '' if len(hits) == 1 else 's',
             'staged' if mode == '--staged' else 'tracked'))
    print('  These repos are public. A path like this publishes an account')
    print('  name and a directory layout, and history keeps it.')
    print('')
    for path, lineno, kind, text in hits:
        print('    %s:%d  (%s)' % (path, lineno, kind))
        print('        %s' % text)
    print('')
    print('  Rewrite them repo-relative, e.g. src/00_head.html:336 - which is')
    print('  what every other citation in these repos already does.')
    print('')
    return 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
