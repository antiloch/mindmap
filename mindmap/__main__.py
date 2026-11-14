"""Запуск: mindmap [файл.md]"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

from .system import MAC, default_file, default_file_hint

DEFAULT_FILE = default_file()


def _fetch_from_icloud(path: Path) -> None:
    """Файл, выгруженный из iCloud, на диске лежит заглушкой. Без скачивания программа
    решила бы, что карты нет, и новая пустая карта затёрла бы настоящую."""
    stub = path.with_name(f".{path.name}.icloud")
    if not MAC or path.exists() or not stub.exists():
        return
    subprocess.run(["brctl", "download", str(path)], capture_output=True)
    for _ in range(60):
        if path.exists():
            return
        time.sleep(0.5)
    sys.exit(f"Файл ещё не скачан из iCloud: {path}\nОткройте его в Finder и запустите снова.")


def main() -> None:
    parser = argparse.ArgumentParser(prog="mindmap", description="Интеллект-карты и канбан в терминале.")
    parser.add_argument("file", nargs="?", default=str(DEFAULT_FILE), help=f"файл карты .md (по умолчанию {default_file_hint()})")
    args = parser.parse_args()

    path = Path(args.file).expanduser().resolve()
    if path.is_dir():
        sys.exit(f"Это папка, а нужен файл: {path}")
    _fetch_from_icloud(path)

    from .app import MindmapApp

    try:
        app = MindmapApp(path)
    except (OSError, UnicodeDecodeError) as err:
        sys.exit(f"Не удалось прочитать {path}: {err}")
    app.run()


if __name__ == "__main__":
    main()
