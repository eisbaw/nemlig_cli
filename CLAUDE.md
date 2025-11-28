# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

CLI tool for interacting with nemlig.com (Danish online grocery store). Single-file Python script using `requests` for HTTP and `argparse` for CLI parsing. Authenticates via a 3-step flow (XSRF token, Bearer token, login) then provides commands for product search, basket management, and order history.

## Development Commands

```bash
# Enter dev environment (if shell.nix exists)
nix-shell

# Run CLI commands via justfile
just search "cocio"              # Search products
just details 701025              # Product details
just basket                      # View basket
just add 701025 2                # Add product (quantity optional)
just history                     # Order history
just history 12345678            # Order details

# Direct execution (requires NEMLIG_USER and NEMLIG_PASS env vars)
uv run python nemlig_cli.py -u "$NEMLIG_USER" -p "$NEMLIG_PASS" search "milk"
```

## Architecture

**Single file design**: All logic in `nemlig_cli.py` (~750 lines)

**Authentication**: `login()` returns `AuthTokens` dataclass holding XSRF token, bearer token, and session. All API functions take `AuthTokens` as first parameter.

**API endpoints**:
- Main site: `https://www.nemlig.com/webapi/*`
- Search: `https://webapi.prod.knl.nemlig.it/searchgateway/api/*`

**Key functions**:
- `login()` - 3-step auth flow
- `search_products()` - requires `get_page_settings()` for timeslot/timestamp params
- `get_product_details()` - first searches to get product URL, then fetches via GetAsJson
- `get_basket()`, `add_to_basket()` - basket operations
- `get_order_history()`, `get_order_details()` - order history

**Command handlers**: `cmd_*` functions parse args and call API functions

## API Documentation

See `nemlig_api.md` for complete API documentation including:
- Authentication flow details
- Search API parameters
- Basket API requests/responses
- Order history endpoints
- Product details via GetAsJson pattern

## Dependencies

- Python >=3.11
- `requests` - HTTP client
- `uv` - package manager (used via justfile)
