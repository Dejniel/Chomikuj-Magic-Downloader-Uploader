#!/usr/bin/env python3

import os
import sys

from .i18n import DEFAULT_LANGUAGE


def load_env(path=".env"):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, "r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            env[key.strip()] = value.strip()
    return env


def resolve_default_env_path(script_path):
    env_path = os.path.abspath(".env")
    if os.path.exists(env_path):
        return env_path
    if getattr(sys, "frozen", False):
        base_dir = os.path.dirname(os.path.abspath(sys.executable))
    else:
        base_dir = os.path.dirname(os.path.abspath(script_path))
    return os.path.join(base_dir, ".env")


def load_default_env(script_path):
    return load_env(resolve_default_env_path(script_path))


def env_language(env):
    return env.get("LANGUAGE", DEFAULT_LANGUAGE)


def save_env_values(path, values):
    existing_lines = []
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8") as handle:
            existing_lines = handle.readlines()

    keys = set(values)
    updated = []
    seen = set()
    for raw_line in existing_lines:
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#") or "=" not in raw_line:
            updated.append(raw_line)
            continue
        key, _ = raw_line.split("=", 1)
        key = key.strip()
        if key in keys:
            updated.append(f"{key}={values[key]}\n")
            seen.add(key)
            continue
        updated.append(raw_line)

    for key in values:
        if key not in seen:
            if updated and not updated[-1].endswith("\n"):
                updated[-1] += "\n"
            updated.append(f"{key}={values[key]}\n")

    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(updated)
