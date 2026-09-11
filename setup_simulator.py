#!/usr/bin/env python3
"""Cross-platform minimal checkout; no CV, ML or Rust dependencies."""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent
DEST = ROOT / '.physical_deps/cr-bot'
PIN = '40ca2b16bc276fc982a3aa80c7415b24439cbd3c'
REMOTE = 'https://github.com/Keschler/cr-bot.git'


def git(*args, cwd=DEST):
    return subprocess.check_output(['git', '-C', str(cwd), *args], text=True).strip()


def main():
    full = ROOT / 'upstream/cr-bot'
    if (full / 'simulator').is_dir() and git('rev-parse', 'HEAD', cwd=full) == PIN:
        print(f'Ready: {full}')
        return
    DEST.parent.mkdir(exist_ok=True)
    if not DEST.exists():
        DEST.mkdir()
        git('init')
        git('remote', 'add', 'origin', REMOTE)
        git('sparse-checkout', 'init', '--cone')
        git('sparse-checkout', 'set', 'simulator')
    elif not (DEST / '.git').is_dir():
        raise SystemExit(f'{DEST} exists and is not a Git checkout; preserve it and use a separate CRBOT_PATH.')
    if git('status', '--porcelain'):
        raise SystemExit(f'Local changes in {DEST}; preserve them before running setup.')
    if git('remote', 'get-url', 'origin') != REMOTE:
        raise SystemExit('Existing backend remote differs from the expected source.')
    current = subprocess.run(['git','-C',str(DEST),'rev-parse','HEAD'],capture_output=True,text=True)
    if current.returncode == 0 and current.stdout.strip() == PIN and (DEST/'simulator').is_dir():
        print(f'Ready: {DEST}')
        return
    git('fetch', '--depth', '1', '--filter=blob:none', 'origin', PIN)
    git('checkout', '--detach', PIN)
    if not (DEST / 'simulator').is_dir():
        raise SystemExit('Missing simulator/ after checkout')
    print(f'Ready: {DEST}\nRun: python simulate.py examples/hog_cannon_primary.json')


if __name__ == '__main__':
    main()
