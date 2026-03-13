#!/usr/bin/env python3

import os
import re

BASE_URL = "https://mobile.chomikuj.pl"
DEBUG = False
TIMEOUT = 60
RETRY_ATTEMPTS = 3
RETRY_BACKOFF_SECONDS = 1
USER_AGENT = "android/3.8.4 (python; python)"
SECRET_KEY = "wzrwYua$.DSe8suk!`'2"
FILE_ID_RE = re.compile(r",(\d+)(?:\.[^./]+)?$")


class ChomikujError(RuntimeError):
    pass


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


def load_default_env(script_path):
    env_path = ".env"
    if not os.path.exists(env_path):
        env_path = os.path.join(os.path.dirname(os.path.abspath(script_path)), ".env")
    return load_env(env_path)
