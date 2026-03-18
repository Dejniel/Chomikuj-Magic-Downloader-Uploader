#!/usr/bin/env python3

import os
import threading
import time

import requests

from .common_runtime import RETRY_ATTEMPTS, RETRY_BACKOFF_SECONDS, TIMEOUT, USER_AGENT, ChomikujError, DownloadSkippedError, is_timeout_error
from .i18n import ensure_i18n


class DownloadWorker(threading.Thread):
    def __init__(self, semaphore, source, path, status_sink=None, i18n=None):
        super().__init__(daemon=True)
        self.semaphore = semaphore
        self.source = source
        self.path = path
        self.status_sink = status_sink
        self.error = None
        self.skipped = False
        self.i18n = ensure_i18n(i18n, language="en")

    def _emit(self, event, *args):
        if self.status_sink:
            handler = getattr(self.status_sink, event, None)
            if handler:
                handler(*args)

    def _total_size(self, response, downloaded_bytes):
        content_range = response.headers.get("Content-Range", "")
        if "/" in content_range:
            total_text = content_range.split("/", 1)[1].strip()
            if total_text.isdigit():
                return int(total_text)
        content_length = response.headers.get("Content-Length")
        if content_length and content_length.isdigit():
            return int(content_length) + downloaded_bytes if response.status_code == 206 else int(content_length)
        return None

    def run(self):
        with self.semaphore:
            try:
                directory = os.path.dirname(self.path)
                if directory:
                    os.makedirs(directory, exist_ok=True)

                part_path = self.path + ".part"
                url = None
                for attempt in range(1, RETRY_ATTEMPTS + 1):
                    has_final = os.path.exists(self.path)
                    has_part = os.path.exists(part_path)
                    final_size = os.path.getsize(self.path) if has_final else 0
                    if has_final and not has_part:
                        self.skipped = True
                        self._emit("download_skipped", self.path)
                        return

                    local_size = os.path.getsize(part_path) if has_part else 0
                    if url is None:
                        url = self.source.resolve_url()
                    headers = {"User-Agent": USER_AGENT}
                    mode = "wb"
                    if local_size:
                        headers["Range"] = f"bytes={local_size}-"
                        mode = "ab"

                    try:
                        with requests.get(url, headers=headers, stream=True, timeout=TIMEOUT, allow_redirects=True) as response:
                            if response.status_code == 416:
                                total_size = self._total_size(response, local_size)
                                expected_size = total_size if total_size is not None else local_size
                                if has_final and final_size == expected_size:
                                    os.remove(part_path)
                                    self.skipped = True
                                    self._emit("download_skipped", self.path)
                                    return
                                if has_final:
                                    os.remove(self.path)
                                if os.path.exists(part_path):
                                    os.replace(part_path, self.path)
                                    self._emit("download_finished", self.path, expected_size, total_size)
                                    return
                                raise ChomikujError(self.i18n("error.download_missing_resume", path=self.path))
                            if response.status_code == 200 and mode == "ab":
                                local_size = 0
                                mode = "wb"
                            response.raise_for_status()
                            total_size = self._total_size(response, local_size)
                            if has_final:
                                if total_size is not None and final_size == total_size:
                                    os.remove(part_path)
                                    self.skipped = True
                                    self._emit("download_skipped", self.path)
                                    return
                                os.remove(self.path)
                            downloaded = local_size
                            self._emit("download_started", self.path, downloaded, total_size)
                            with open(part_path, mode) as handle:
                                for chunk in response.iter_content(131072):
                                    if chunk:
                                        handle.write(chunk)
                                        downloaded += len(chunk)
                                        self._emit("download_progress", self.path, downloaded, total_size)
                        os.replace(part_path, self.path)
                        self._emit("download_finished", self.path, downloaded, total_size)
                        return
                    except requests.RequestException as exc:
                        is_timeout = is_timeout_error(exc)
                        if is_timeout and attempt >= RETRY_ATTEMPTS:
                            raise ChomikujError(
                                self.i18n("error.download_timeout", path=self.path, attempts=RETRY_ATTEMPTS, error=exc)
                            ) from exc
                        if not is_timeout:
                            raise
                        time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            except DownloadSkippedError:
                self.skipped = True
                self._emit("download_skipped", self.path)
            except Exception as exc:
                self.error = exc
                self._emit("download_failed", self.path, exc)
