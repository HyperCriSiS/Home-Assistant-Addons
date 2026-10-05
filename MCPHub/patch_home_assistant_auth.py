#!/usr/bin/env python3
"""Patch MCPHub 1.1.0 to trust Home Assistant Ingress identity headers.

The Supervisor injects X-Remote-User-* headers for authenticated Ingress sessions.
A second private proxy secret prevents those headers from being trusted outside the
Home Assistant Ingress adapter.
"""

from __future__ import annotations

from pathlib import Path


AUTH_FILE = Path("/app/dist/middlewares/auth.js")
BETTER_AUTH_CONTROLLER_FILE = Path("/app/dist/controllers/betterAuthController.js")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Unexpected MCPHub 1.1.0 structure for {label}: found {count}")
    return text.replace(old, new, 1)


def patch_auth() -> None:
    text = AUTH_FILE.read_text(encoding="utf-8")

    marker = "const resolveBetterAuthUserSafe = async (req) => {"
    helper = """export const resolveHomeAssistantIngressUser = (req) => {
    const expectedSecret = process.env.HA_INGRESS_PROXY_SECRET;
    const providedSecret = req.header('x-mcphub-ha-proxy-secret');
    const userId = req.header('x-remote-user-id');

    if (!expectedSecret || !providedSecret || !userId) {
        return null;
    }

    if (!safeCompare(expectedSecret, providedSecret)) {
        return null;
    }

    const remoteUsername = req.header('x-remote-user-name')?.trim();
    const displayName = req.header('x-remote-user-display-name')?.trim();
    const username = remoteUsername || displayName || ('ha-' + userId);

    return {
        username,
        isAdmin: true,
        credentialEligible: false,
        homeAssistantUserId: userId,
        homeAssistantDisplayName: displayName || remoteUsername || username,
    };
};

"""
    text = replace_once(text, marker, helper + marker, "Home Assistant auth helper")

    auth_marker = "    // Check if bearer auth via configured keys can validate this request\n"
    auth_block = """    const homeAssistantUser = resolveHomeAssistantIngressUser(req);
    if (homeAssistantUser) {
        req.user = homeAssistantUser;
        next();
        return;
    }

"""
    text = replace_once(
        text,
        auth_marker,
        auth_block + auth_marker,
        "Home Assistant auth middleware",
    )

    AUTH_FILE.write_text(text, encoding="utf-8")


def patch_better_auth_controller() -> None:
    text = BETTER_AUTH_CONTROLLER_FILE.read_text(encoding="utf-8")

    import_marker = "import { logger } from '../utils/logger.js';\n"
    text = replace_once(
        text,
        import_marker,
        import_marker
        + "import { resolveHomeAssistantIngressUser } from '../middlewares/auth.js';\n",
        "Home Assistant auth import",
    )

    handler_marker = "export const getBetterAuthUser = async (req, res) => {\n    try {\n"
    handler_block = """export const getBetterAuthUser = async (req, res) => {
    try {
        const homeAssistantUser = resolveHomeAssistantIngressUser(req);
        if (homeAssistantUser) {
            res.json({
                success: true,
                user: {
                    username: homeAssistantUser.username,
                    isAdmin: homeAssistantUser.isAdmin,
                    permissions: dataService.getPermissions(homeAssistantUser),
                },
            });
            return;
        }
"""
    text = replace_once(
        text,
        handler_marker,
        handler_block,
        "Home Assistant current-user fallback",
    )

    BETTER_AUTH_CONTROLLER_FILE.write_text(text, encoding="utf-8")


def main() -> None:
    patch_auth()
    patch_better_auth_controller()


if __name__ == "__main__":
    main()
