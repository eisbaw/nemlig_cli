# Optional Bash/just shortcuts. Windows users can run Python directly (README).
set dotenv-load
set positional-arguments

default:
    @just --list

nemlig:
    uv run python nemlig_cli.py

search QUERY:
    uv run python nemlig_cli.py search "$1"

details PRODUCT_ID:
    uv run python nemlig_cli.py details "$1"

basket:
    uv run python nemlig_cli.py basket

add PRODUCT_ID QUANTITY="1":
    uv run python nemlig_cli.py add "$1" --quantity "$2"

history ORDER_ID="":
    if [ -n "$1" ]; then uv run python nemlig_cli.py history "$1"; else uv run python nemlig_cli.py history; fi

list:
    uv run python nemlig_cli.py list

list-add QUERY QUANTITY="1":
    uv run python nemlig_cli.py list add "$1" --quantity "$2"

list-remove PRODUCT_ID:
    uv run python nemlig_cli.py list remove "$1"

list-clear:
    uv run python nemlig_cli.py list clear

list-budget AMOUNT="":
    if [ -n "$1" ]; then uv run python nemlig_cli.py list budget "$1"; else uv run python nemlig_cli.py list budget; fi

list-sync:
    uv run python nemlig_cli.py list sync

plan:
    uv run python nemlig_cli.py plan

import SPREADSHEET_ID="":
    if [ -n "$1" ]; then uv run python nemlig_cli.py import "$1"; else uv run python nemlig_cli.py import; fi

import-setup:
    uv run python nemlig_cli.py import --setup

scan:
    uv run python nemlig_cli.py scan

fridge:
    uv run python nemlig_cli.py fridge

fridge-clear:
    uv run python nemlig_cli.py fridge clear

fridge-suggest:
    uv run python nemlig_cli.py fridge suggest
