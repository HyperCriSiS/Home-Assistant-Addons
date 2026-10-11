#!/usr/bin/env python3
"""Patch MCPHub 1.1.1 for trusted Home Assistant Ingress sessions.

The Supervisor injects X-Remote-User-* headers for authenticated Ingress sessions.
A second private proxy secret prevents those headers from being trusted outside the
Home Assistant Ingress adapter. The trusted proxy itself is sufficient for the
session, while Supervisor user headers enrich the identity when available.

Home Assistant Ingress users remain identifiable by their Home Assistant username,
but persistent MCPHub server ownership is normalized to the canonical local
`admin` principal. MCPHub uses the persisted owner to decide whether a configured
upstream may access private/internal networks, so this mapping is required for
trusted Home Assistant-local MCP endpoints such as http://homeassistant:8123.
"""

from __future__ import annotations

from pathlib import Path


AUTH_FILE = Path("/app/dist/middlewares/auth.js")
BETTER_AUTH_CONTROLLER_FILE = Path("/app/dist/controllers/betterAuthController.js")
SERVER_CONTROLLER_FILE = Path("/app/dist/controllers/serverController.js")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"Unexpected MCPHub 1.1.1 structure for {label}: found {count}")
    return text.replace(old, new, 1)


def patch_auth() -> None:
    text = AUTH_FILE.read_text(encoding="utf-8")

    marker = "const resolveBetterAuthUserSafe = async (req) => {"
    helper = """export const resolveHomeAssistantIngressUser = (req) => {
    const expectedSecret = process.env.HA_INGRESS_PROXY_SECRET;
    const providedSecret = req.header('x-mcphub-ha-proxy-secret');

    if (!expectedSecret || !providedSecret) {
        return null;
    }

    if (!safeCompare(expectedSecret, providedSecret)) {
        return null;
    }

    const userId = req.header('x-remote-user-id')?.trim();
    const remoteUsername = req.header('x-remote-user-name')?.trim();
    const displayName = req.header('x-remote-user-display-name')?.trim();
    const username =
        remoteUsername || displayName || (userId ? ('ha-' + userId) : 'homeassistant-admin');

    return {
        username,
        isAdmin: true,
        credentialEligible: false,
        homeAssistantUserId: userId || 'ingress',
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


def patch_server_controller() -> None:
    text = SERVER_CONTROLLER_FILE.read_text(encoding="utf-8")

    owner_marker = """    if (currentUser.isAdmin) {
        config.owner = config.owner || existingOwner || currentUser.username;
        return;
    }
"""
    owner_block = """    if (currentUser.isAdmin) {
        if (currentUser.homeAssistantUserId) {
            config.owner = 'admin';
            return;
        }
        config.owner = config.owner || existingOwner || currentUser.username;
        return;
    }
"""
    text = replace_once(
        text,
        owner_marker,
        owner_block,
        "Home Assistant canonical server owner",
    )

    batch_owner_marker = "    const defaultOwner = currentUser?.username || 'admin';\n"
    batch_owner_block = """    const defaultOwner =
        currentUser?.isAdmin && currentUser?.homeAssistantUserId
            ? 'admin'
            : currentUser?.username || 'admin';
"""
    text = replace_once(
        text,
        batch_owner_marker,
        batch_owner_block,
        "Home Assistant canonical batch server owner",
    )

    SERVER_CONTROLLER_FILE.write_text(text, encoding="utf-8")


def main() -> None:
    patch_auth()
    patch_better_auth_controller()
    patch_server_controller()


if __name__ == "__main__":
    main()