# CLAUDE.md

AI assistant guidance for this repository. See README.md for project overview and workflow documentation.

## Quick Commands

```bash
just search "cocio"     # Search products
just details 701025     # Product details
just basket             # View basket
just add 701025 2       # Add product
just history            # Order history
```

Requires `NEMLIG_USER` and `NEMLIG_PASS` environment variables.

## MCP Usage

Chrome DevTools MCP is configured via `.mcp.json`. Use for API discovery and debugging.

**Critical**: MCP calls return large payloads (>25KB). Always run MCP interactions from a sub-agent to avoid context bloat.

**Privacy**: Never record actual personal information (real names, addresses, phone numbers, order IDs). Replace with realistic placeholder values when documenting APIs (e.g., "Anders And", "Vesterbrogade 42", "+4512345678").

Pattern:
1. Sub-agent navigates, records network traffic, performs action
2. Sub-agent returns summary (endpoint, headers, body format)
3. Main context updates documentation or implements code

## Diagrams

Diagrams are stored as `.drawio.svg` files (SVG with embedded draw.io source). Keep them updated when architecture changes.

**To edit**: Open `.drawio.svg` directly in draw.io - the source is embedded.

**To create/update**:
```bash
# Create/edit in draw.io, save as .drawio file, then export:
drawio -x -f svg --embed-diagram -o diagram.drawio.svg diagram.drawio
rm diagram.drawio  # Keep only the .svg
```

Current diagrams:
- `arch_api.drawio.svg` - API architecture (endpoints, auth flow)
- `mcp-workflow.drawio.svg` - MCP workflow for API discovery

## Project Commands

Custom slash commands for this project. **Run both in sub-agents in parallel before every commit.**

- `/drawio-updater` - Audit and update `.drawio.svg` diagrams
- `/privacy-checker` - Scan files for personal data leaks

## Files

- `nemlig_cli.py` - Single-file Python client
- `nemlig_api.md` - API documentation (source of truth for endpoints)
- `justfile` - Command shortcuts
