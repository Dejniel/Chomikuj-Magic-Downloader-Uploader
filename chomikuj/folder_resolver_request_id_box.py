#!/usr/bin/env python3

import re
import time

import requests

from .common_runtime import RETRY_ATTEMPTS, RETRY_BACKOFF_SECONDS, TIMEOUT, ChomikujError, is_timeout_error
from .i18n import ensure_i18n


class FolderResolverRequestIdBox:
    TOKEN_RE = re.compile(r'name="__RequestVerificationToken".*?value="([^"]+)"', re.S)
    REQ_ID_RE = re.compile(r"chomik://files/(\d+)/(\d+)")

    def __init__(self, username, password, soap_token, debug=False, debug_hook=None, i18n=None):
        self.username = username
        self.password = password
        self.soap_token = soap_token
        self.debug = debug
        self.debug_hook = debug_hook
        self.i18n = ensure_i18n(i18n, language="en")
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": "Mozilla/5.0",
                "X-Requested-With": "XMLHttpRequest",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
            }
        )
        self.request_token = ""
        self.req_id_cache = {}

    def _debug(self, message):
        if self.debug and self.debug_hook:
            self.debug_hook(message)

    def _request(self, method, action, url, **kwargs):
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                response = self.session.request(method, url, timeout=TIMEOUT, **kwargs)
                break
            except requests.RequestException as exc:
                if is_timeout_error(exc):
                    if attempt >= RETRY_ATTEMPTS:
                        raise ChomikujError(
                            self.i18n("error.box_timeout", action=action, attempts=RETRY_ATTEMPTS, error=exc)
                        ) from exc
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                    continue
                raise ChomikujError(self.i18n("error.box_connection", action=action, error=exc)) from exc
        if self.debug:
            self._debug(f"DEBUG WEB {action} HTTP {response.status_code}")
            self._debug(response.text[:4000])
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ChomikujError(self.i18n("error.box_http", action=action, status=response.status_code)) from exc
        return response

    def _ensure_login(self):
        if self.request_token:
            return
        response = self._request(
            "GET",
            "LoginFromBox",
            f"https://chomikuj.pl/chomik/chomikbox/LoginFromBox?t={self.soap_token}&returnUrl=/ChomikBox",
        )
        match = self.TOKEN_RE.search(response.text)
        if not match:
            raise ChomikujError(self.i18n("error.box_missing_token"))
        self.request_token = match.group(1)
        self._request(
            "POST",
            "TopBarLogin",
            "https://chomikuj.pl/action/Login/TopBarLogin",
            data={
                "ReturnUrl": "",
                "Login": self.username,
                "rememberLogin": "true",
                "Password": self.password,
                "__RequestVerificationToken": self.request_token,
            },
        )

    def resolve_request_id(self, owner_name, folder_id):
        key = (str(owner_name or "").casefold(), str(folder_id))
        if key in self.req_id_cache:
            return self.req_id_cache[key]
        self._ensure_login()
        response = self._request(
            "POST",
            "DownloadFolderChomikBox",
            "https://chomikuj.pl/action/chomikbox/DownloadFolderChomikBox",
            data={
                "chomikName": owner_name,
                "folderId": folder_id,
                "__RequestVerificationToken": self.request_token,
            },
        )
        match = self.REQ_ID_RE.search(response.text)
        if not match:
            raise ChomikujError(
                self.i18n("error.box_missing_request_id", owner_name=owner_name, folder_id=folder_id)
            )
        req_id = f"{match.group(1)}/{match.group(2)}"
        self.req_id_cache[key] = req_id
        return req_id
