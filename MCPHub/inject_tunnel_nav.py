#!/usr/bin/env python3
"""Add a HA-Ingress-only tunnel control link to the pinned upstream SPA shell."""
from pathlib import Path

INDEX = Path("/app/frontend/dist/index.html")
TAG = '<script defer src="./mcphub-ha-nav.js"></script>'


def inject_shell(html):
    if html.count("</body>") != 1:
        raise ValueError("Unexpected MCPHub frontend HTML: missing closing body")
    if TAG in html:
        raise ValueError("MCPHub navigation script is already installed")
    return html.replace("</body>", TAG + "\n</body>", 1)


def main():
    if not INDEX.is_file():
        raise SystemExit("MCPHub upstream frontend bundle not found")
    INDEX.write_text(inject_shell(INDEX.read_text(encoding="utf-8")),
                     encoding="utf-8")


if __name__ == "__main__":
    main()
