#!/usr/bin/env python3

import os
import re
import sys

from .i18n import DEFAULT_LANGUAGE, ensure_i18n

BASE_URL = "https://mobile.chomikuj.pl"
DEBUG = False
TIMEOUT = 15
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1
USER_AGENT = "android/3.8.4 (python; python)"
SECRET_KEY = "wzrwYua$.DSe8suk!`'2"
FILE_ID_RE = re.compile(r",(\d+)(?:\.[^./]+)?$")
LOCAL_EXTENSION_RE = re.compile(r"\.[A-Za-z0-9]+$")
LOCAL_SAFE_CHARS = set(" .-_()[],")


class ChomikujError(RuntimeError):
    pass


class FileUnavailableError(ChomikujError):
    def __init__(self, file_id, code=None, message="", i18n=None):
        text = ensure_i18n(i18n, language="en")("error.file_unavailable", file_id=file_id)
        if code is not None:
            text += f": {code}"
        if message:
            text += f" {message}"
        super().__init__(text)
        self.file_id = str(file_id)
        self.code = code
        self.api_message = message


class DownloadSkippedError(ChomikujError):
    pass


class ApiRequestError(ChomikujError):
    def __init__(self, status, code=None, message="", body=""):
        super().__init__(message or f"HTTP {status}")
        self.status = status
        self.code = code
        self.body = body


def is_timeout_error(exc):
    current = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        class_name = current.__class__.__name__.lower()
        message = str(current).lower()
        if "timeout" in class_name or "timed out" in message or "read timeout" in message:
            return True
        current = getattr(current, "__cause__", None) or getattr(current, "__context__", None)
    return False


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


def encode_local_component(name, allow_extension=False):
    text = str(name or "")
    extension = ""
    if allow_extension:
        match = LOCAL_EXTENSION_RE.search(text)
        if match and 0 < match.start() < len(text) - 1:
            text, extension = text[: match.start()], match.group(0)

    encoded = []
    last_index = len(text) - 1
    for index, char in enumerate(text):
        if ("a" <= char <= "z") or ("A" <= char <= "Z") or ("0" <= char <= "9"):
            encoded.append(char)
        elif char in LOCAL_SAFE_CHARS and 0 < index < last_index:
            encoded.append(char)
        else:
            encoded.extend(f"*{byte:02x}" for byte in char.encode("utf-8"))
    encoded_text = "".join(encoded) or "_"
    return encoded_text + extension


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
