"""Что зависит от системы: карта по умолчанию, буфер обмена, открытие ссылок.

macOS — pbcopy и open, карта в iCloud. Linux — wl-copy/xclip/xsel и xdg-open, карта в домашней
папке. Нет ни одной программы буфера — копирование идёт через сам терминал (OSC 52).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

MAC = sys.platform == "darwin"
PASTE_KEY = "Cmd+V" if MAC else "Ctrl+Shift+V"


def default_file() -> Path:
    if MAC:
        return Path.home() / "Library/Mobile Documents/com~apple~CloudDocs/Карты/Карта.md"
    return Path.home() / "Карта.md"


def default_file_hint() -> str:
    return "iCloud/Карты/Карта.md" if MAC else "~/Карта.md"


def copy_command() -> list[str] | None:
    """Программа, кладущая текст из stdin в буфер обмена; None — такой нет."""
    if MAC:
        return ["pbcopy"]
    wayland = bool(os.environ.get("WAYLAND_DISPLAY"))
    candidates = [["wl-copy"]] if wayland else []
    candidates += [["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"], ["wl-copy"]]
    return next((c for c in candidates if shutil.which(c[0])), None)


def copy_text(text: str) -> None:
    """Положить текст в системный буфер. Нет программы буфера — FileNotFoundError."""
    command = copy_command()
    if command is None:
        raise FileNotFoundError("нет программы буфера обмена (wl-copy, xclip, xsel)")
    subprocess.run(command, input=text.encode("utf-8"), check=True, timeout=5,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_target(target: str) -> None:
    """Открыть адрес или файл в программе по умолчанию."""
    command = ["open", target] if MAC else ["xdg-open", target]
    # Вывод браузера не должен попасть на экран программы.
    subprocess.run(command, check=True, timeout=10, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=not MAC)
