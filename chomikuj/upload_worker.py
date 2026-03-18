#!/usr/bin/env python3

import os
import re
import threading
import time
import zlib

import requests

from .common_runtime import RETRY_ATTEMPTS, RETRY_BACKOFF_SECONDS, TIMEOUT, USER_AGENT, ChomikujError, is_timeout_error
from .i18n import ensure_i18n
from .api_mobile import ApiMobile

CHUNK_SIZE = 524288


class UploadWorker(threading.Thread):
    def __init__(
        self,
        semaphore,
        username,
        password,
        api_key,
        account_id,
        account_name,
        local_path,
        folder_id,
        target,
        status_sink=None,
        debug=False,
        debug_hook=None,
        i18n=None,
    ):
        super().__init__(daemon=True)
        self.semaphore = semaphore
        self.local_path = os.path.abspath(local_path)
        self.folder_id = str(folder_id)
        self.target = target
        self.status_sink = status_sink
        self.debug = debug
        self.debug_hook = debug_hook
        self.error = None
        self.i18n = ensure_i18n(i18n, language="en")
        self.api = ApiMobile(username, password, debug=debug, debug_hook=debug_hook, i18n=self.i18n)
        self.api.api_key = api_key
        self.api.account_id = account_id
        self.api.account_name = account_name

    def _emit(self, event, *args):
        if self.status_sink:
            handler = getattr(self.status_sink, event, None)
            if handler:
                handler(*args)

    def _crc32(self):
        crc = 0
        with open(self.local_path, "rb") as handle:
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    break
                crc = zlib.crc32(chunk, crc)
        return format(crc & 0xFFFFFFFF, "x")

    def _escape_file_name(self, name):
        return re.sub(r'[\?\:\<\>\/\*"\\\\]+', "_", name)

    def _upload_chunk(self, name, upload_url, offset, size):
        boundary = f"***{int(time.time() * 1000)}***"
        with open(self.local_path, "rb") as handle:
            handle.seek(offset)
            chunk = handle.read(min(CHUNK_SIZE, max(0, size - offset)))
        body = b"".join(
            [
                f"--{boundary}\r\n".encode("utf-8"),
                f'Content-Disposition: form-data; name="files[]";filename="{self._escape_file_name(name)}"\r\n'.encode("utf-8"),
                b"\r\n",
                chunk,
                b"\r\n",
                f"--{boundary}--\r\n".encode("utf-8"),
            ]
        )
        next_offset = offset + len(chunk)
        headers = {
            "User-Agent": USER_AGENT,
            "Connection": "Keep-Alive",
            "ENCTYPE": "multipart/form-data",
            "Content-Type": f"multipart/form-data;boundary={boundary}",
            "Content-Length": str(len(body)),
            "File-Range": f"{offset}-{next_offset}",
        }
        try:
            response = requests.post(upload_url, headers=headers, data=body, timeout=TIMEOUT)
        except requests.RequestException as exc:
            if is_timeout_error(exc):
                raise
            raise ChomikujError(self.i18n("error.upload_connection", path=self.local_path, error=exc)) from exc
        return response.status_code, next_offset

    def _refresh_upload_state(self, name, size, crc):
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                payload = self.api.files_upload_partial(name, size, self.folder_id, crc)
                break
            except ChomikujError as exc:
                is_timeout = is_timeout_error(exc)
                if not is_timeout or attempt >= RETRY_ATTEMPTS:
                    raise
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
        if payload.get("UploadCompleted"):
            return None, int(size), True
        upload_url = payload.get("Url")
        if not upload_url:
            raise ChomikujError(self.i18n("error.upload_missing_partial_url", path=self.local_path))
        uploaded = int(payload.get("Chunk") or 0)
        return upload_url, uploaded, False

    def run(self):
        with self.semaphore:
            try:
                if not os.path.isfile(self.local_path):
                    raise ChomikujError(self.i18n("error.upload_not_file", path=self.local_path))
                name = os.path.basename(self.local_path)
                size = os.path.getsize(self.local_path)
                crc = self._crc32()
                self._emit("upload_started", self.local_path, self.target, size)
                upload_url, uploaded, completed = self._refresh_upload_state(name, size, crc)
                if completed:
                    self._emit("upload_finished", self.local_path, self.target, size)
                    return
                self._emit("upload_progress", self.local_path, uploaded, size, self.target)
                timeout_attempt = 0
                while True:
                    try:
                        status, uploaded = self._upload_chunk(name, upload_url, uploaded, size)
                    except requests.RequestException as exc:
                        if not is_timeout_error(exc):
                            raise ChomikujError(self.i18n("error.upload_connection", path=self.local_path, error=exc)) from exc
                        timeout_attempt += 1
                        if timeout_attempt >= RETRY_ATTEMPTS:
                            raise ChomikujError(
                                self.i18n("error.upload_timeout", path=self.local_path, attempts=RETRY_ATTEMPTS, error=exc)
                            ) from exc
                        time.sleep(RETRY_BACKOFF_SECONDS * timeout_attempt)
                        upload_url, uploaded, completed = self._refresh_upload_state(name, size, crc)
                        if completed:
                            self._emit("upload_finished", self.local_path, self.target, size)
                            return
                        self._emit("upload_progress", self.local_path, uploaded, size, self.target)
                        continue
                    if status == 408:
                        timeout_attempt += 1
                        if timeout_attempt >= RETRY_ATTEMPTS:
                            raise ChomikujError(
                                self.i18n("error.upload_timeout_no_detail", path=self.local_path, attempts=RETRY_ATTEMPTS)
                            )
                        time.sleep(RETRY_BACKOFF_SECONDS * timeout_attempt)
                        upload_url, uploaded, completed = self._refresh_upload_state(name, size, crc)
                        if completed:
                            self._emit("upload_finished", self.local_path, self.target, size)
                            return
                        self._emit("upload_progress", self.local_path, uploaded, size, self.target)
                        continue
                    timeout_attempt = 0
                    self._emit("upload_progress", self.local_path, uploaded, size, self.target)
                    if status == 200:
                        self._emit("upload_finished", self.local_path, self.target, size)
                        return
                    if status == 206:
                        continue
                    if status == 409:
                        raise ChomikujError(self.i18n("error.upload_conflict", path=self.local_path))
                    if status == 410:
                        raise ChomikujError(self.i18n("error.upload_expired", path=self.local_path))
                    if status == 500:
                        raise ChomikujError(self.i18n("error.upload_internal", path=self.local_path))
                    raise ChomikujError(self.i18n("error.upload_unknown", status=status, path=self.local_path, target=self.target))
            except Exception as exc:
                self.error = exc
                self._emit("upload_failed", self.local_path, exc, self.target)
