#!/usr/bin/env python3

import os
import sys

from .i18n import DEFAULT_LANGUAGE


ENV_LOGIN = "CHOMIKUJ_LOGIN"
ENV_PASSWORD = "CHOMIKUJ_PASSWORD"
ENV_LANGUAGE = "CHOMIKUJ_LANGUAGE"
ENV_KEYS = (ENV_LOGIN, ENV_PASSWORD, ENV_LANGUAGE)


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
    env = load_env(resolve_default_env_path(script_path))
    for key in ENV_KEYS:
        value = os.environ.get(key)
        if value:
            env[key] = value
    return env


def env_language(env):
    return env.get(ENV_LANGUAGE, DEFAULT_LANGUAGE)
