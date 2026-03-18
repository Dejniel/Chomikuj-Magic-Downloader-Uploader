#!/usr/bin/env python3

import re

from .i18n import ensure_i18n

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


class PasswordSkippedError(ChomikujError):
    def __init__(self, kind, identifier):
        super().__init__(f"Skipped password-protected {kind}: {identifier}")
        self.kind = kind
        self.identifier = identifier


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
