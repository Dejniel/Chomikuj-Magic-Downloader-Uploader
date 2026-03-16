#!/usr/bin/env python3

import os
import re
import threading
import time
import zlib

import requests

from .common import RETRY_ATTEMPTS, RETRY_BACKOFF_SECONDS, TIMEOUT, USER_AGENT, ChomikujError, is_timeout_error
from .mobile_api import MobileApi

CHUNK_SIZE = 524288


class UploadItem(threading.Thread):
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
        self.api = MobileApi(username, password, debug=debug, debug_hook=debug_hook)
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
            raise ChomikujError(f"Connection error during upload of {self.local_path}: {exc}") from exc
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
            raise ChomikujError(f"Missing URL after partialUpload for file: {self.local_path}")
        uploaded = int(payload.get("Chunk") or 0)
        return upload_url, uploaded, False

    def run(self):
        with self.semaphore:
            try:
                if not os.path.isfile(self.local_path):
                    raise ChomikujError(f"This is not a file for upload: {self.local_path}")
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
                            raise ChomikujError(f"Connection error during upload of {self.local_path}: {exc}") from exc
                        timeout_attempt += 1
                        if timeout_attempt >= RETRY_ATTEMPTS:
                            raise ChomikujError(
                                f"Upload timeout for {self.local_path} after {RETRY_ATTEMPTS} attempts: {exc}"
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
                                f"Upload timeout for {self.local_path} after {RETRY_ATTEMPTS} attempts"
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
                        raise ChomikujError(f"Upload conflict for file: {self.local_path}")
                    if status == 410:
                        raise ChomikujError(f"Upload session expired for file: {self.local_path}")
                    if status == 500:
                        raise ChomikujError(f"Upload internal error for file: {self.local_path}")
                    raise ChomikujError(f"Unknown upload error {status} for {self.local_path} to {self.target}")
            except Exception as exc:
                self.error = exc
                self._emit("upload_failed", self.local_path, exc, self.target)
