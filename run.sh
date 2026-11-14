#!/bin/sh
# Запуск mindmap. На этот файл указывает симлинк ~/.local/bin/mindmap.
DIR="$(cd "$(dirname "$(readlink -f "$0")")" && pwd)"
PYTHONPATH="$DIR" exec "$DIR/.venv/bin/python" -P -m mindmap "$@"
