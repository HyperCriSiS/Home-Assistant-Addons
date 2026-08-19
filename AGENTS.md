# Home Assistant Add-ons — Repository Instructions

Follow the global Codex instructions first.

## Project constraints

- Preserve Home Assistant add-on packaging and configuration conventions.
- Treat container image changes, architecture support, persistent data paths, ingress/network settings, permissions, and upgrade behavior as compatibility-sensitive.
- Do not introduce destructive migration behavior for existing users.
- Validate shell scripts defensively and fail clearly on invalid configuration.

## Repository workflow

- Inspect add-on metadata/config, Dockerfiles/container build files, scripts, supported architectures, README/docs, and CI before changes.
- Test build paths for the architectures/environments the repository claims to support where practical.
