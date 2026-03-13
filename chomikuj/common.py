#!/usr/bin/env python3

import os
import re

BASE_URL = "https://mobile.chomikuj.pl"
DEBUG = False
TIMEOUT = 15
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1
USER_AGENT = "android/3.8.4 (python; python)"
SECRET_KEY = "wzrwYua$.DSe8suk!`'2"
FILE_ID_RE = re.compile(r",(\d+)(?:\.[^./]+)?$")


class ChomikujError(RuntimeError):
    pass


class FileUnavailableError(ChomikujError):
    def __init__(self, file_id, code=None, message=""):
        text = f"Plik niedostepny w API dla fileId={file_id}"
        if code is not None:
            text += f": {code}"
        if message:
            text += f" {message}"
        super().__init__(text)
        self.file_id = str(file_id)
        self.code = code
        self.api_message = message


class ApiRequestError(ChomikujError):
    def __init__(self, status, code=None, message="", body=""):
        super().__init__(message or f"HTTP {status}")
        self.status = status
        self.code = code
        self.body = body


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
    env_path = ".env"
    if os.path.exists(env_path):
        return env_path
    return os.path.join(os.path.dirname(os.path.abspath(script_path)), ".env")


def load_default_env(script_path):
    return load_env(resolve_default_env_path(script_path))


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
