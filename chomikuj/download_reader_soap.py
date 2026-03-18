#!/usr/bin/env python3

import re
import threading
from urllib.parse import quote_plus, unquote_plus, urlsplit

from .api_soap import ApiSoap
from .common_runtime import ChomikujError, DownloadSkippedError
from .download_source import DownloadSourceDirect, DownloadSourceSoap
from .folder_resolver_request_id_box import FolderResolverRequestIdBox
from .i18n import ensure_i18n


class DownloadReaderSoap:
    PAGE_SUFFIX_RE = re.compile(r",\d+$")
    FILE_PATH_RE = re.compile(r",\d+\.[^/]+(?:\([^)]+\))?$")
    SUSPICIOUS_TRANSFER_MULTIPLIER = 16

    def __init__(self, username, password, debug=False, debug_hook=None, i18n=None):
        self.username = username
        self.password = password
        self.debug = debug
        self.debug_hook = debug_hook
        self.i18n = ensure_i18n(i18n, language="en")
        self.api = ApiSoap(username, password, debug=debug, debug_hook=debug_hook, i18n=self.i18n)
        self.api.auth()
        self._folder_resolver = None
        self._thread_api = threading.local()

    def _debug(self, message):
        if self.debug and self.debug_hook:
            self.debug_hook(message)

    def _decode(self, value):
        value = re.sub(r"\*([0-9a-fA-F]{2})", r"%\1", str(value or ""))
        return unquote_plus(value).strip().strip("/")

    def _split_raw_url(self, url):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or parsed.netloc not in ("chomikuj.pl", "www.chomikuj.pl"):
            raise ChomikujError(self.i18n("error.unsupported_url", url=url))
        if not parsed.path or parsed.path == "/":
            raise ChomikujError(self.i18n("error.invalid_url", url=url))
        return parsed.path

    def _candidate_paths(self, raw_path):
        candidates = [raw_path]
        parts = raw_path.rstrip("/").split("/")
        if parts:
            last = parts[-1]
            stripped = self.PAGE_SUFFIX_RE.sub("", last).strip()
            if stripped and stripped != last:
                candidates.append("/".join(parts[:-1] + [stripped]))
        return candidates

    def _decoded_segments(self, raw_path):
        return [self._decode(part) for part in raw_path.split("/") if part]

    def folder_segments(self, folder):
        segments = [self._decode(part) for part in folder.get("global_id", "").split("/") if part]
        if segments:
            return segments[1:]
        return []

    def _encode_chomik_component(self, value):
        return re.sub(r"%([0-9A-Fa-f]{2})", lambda match: f"*{match.group(1).lower()}", quote_plus(str(value), safe="()"))

    def folder_request_path(self, owner_name, folder_segments):
        encoded = [self._encode_chomik_component(part) for part in [owner_name, *folder_segments] if part]
        return "/" + "/".join(encoded).strip("/")

    def _file_request_candidates(self, folder_request_path, entry):
        name = str(entry.get("name") or "")
        file_id = str(entry.get("id") or "")
        if not folder_request_path or not name or not file_id:
            return []
        stem, dot, ext = name.rpartition(".")
        if not dot:
            stem = name
            ext = ""
            suffixes = [""]
        else:
            suffixes = [""]
            lowered = ext.lower()
            if lowered in {"aac", "flac", "m4a", "mp3", "ogg", "wav", "wma"}:
                suffixes = ["(audio)", ""]
            elif lowered in {"avi", "mkv", "mov", "mp4", "mpeg", "mpg", "webm", "wmv"}:
                suffixes = ["(video)", ""]
        candidates = []
        for suffix in suffixes:
            request_name = f"{stem},{file_id}"
            if dot:
                request_name += f".{ext}"
            request_name += suffix
            encoded_name = self._encode_chomik_component(request_name)
            raw_comma_name = encoded_name.replace("*2c", ",")
            for candidate_name in (raw_comma_name, encoded_name):
                candidate = f"{folder_request_path}/{candidate_name}"
                if candidate not in candidates:
                    candidates.append(candidate)
        return candidates

    def _expected_transfer_cost(self, size_bytes):
        try:
            size_value = int(size_bytes or 0)
        except (TypeError, ValueError):
            return None
        if size_value <= 0:
            return None
        return max(1, size_value // 1024)

    def _is_suspicious_transfer(self, entry, agreement):
        if agreement.get("name") != "transfer":
            return False
        try:
            cost = int(agreement.get("cost") or 0)
        except (TypeError, ValueError):
            return False
        expected = self._expected_transfer_cost(entry.get("size"))
        if expected is None or cost <= 0:
            return False
        return cost > expected * self.SUSPICIOUS_TRANSFER_MULTIPLIER

    def _resolve_with_agreements(self, api, entry):
        suspicious = None
        for agreement in entry.get("agreements", []):
            if self._is_suspicious_transfer(entry, agreement):
                expected = self._expected_transfer_cost(entry.get("size"))
                self._debug(
                    f"DEBUG SOAP skip suspicious transfer agreement for fileId={entry.get('id')} "
                    f"cost={agreement.get('cost')} expected~{expected}"
                )
                suspicious = (agreement, expected)
                continue
            cost = agreement.get("cost")
            resolved = api.download(entry["id"], agreement["name"], cost if cost else None)
            if not resolved["files"]:
                continue
            resolved_entry = resolved["files"][0]
            if resolved_entry.get("url"):
                return resolved_entry["url"]
        if suspicious is not None:
            agreement, expected = suspicious
            raise DownloadSkippedError(
                self.i18n(
                    "error.download_suspicious_transfer",
                    file_id=entry.get("id"),
                    cost=int(agreement.get("cost") or 0),
                    expected=expected or "?",
                )
            )
        return None

    def download_url(self, entry, folder_request_path):
        if entry.get("url"):
            return entry["url"]
        api = self._resolver_api()
        for request_path in self._file_request_candidates(folder_request_path, entry):
            try:
                hinted = api.download(request_path, None, None)
            except ChomikujError:
                continue
            if hinted["files"]:
                resolved = self._resolve_with_agreements(api, hinted["files"][0])
                if resolved:
                    return resolved
        resolved = self._resolve_with_agreements(api, entry)
        if resolved:
            return resolved
        raise ChomikujError(self.i18n("error.soap_missing_direct_url", file_id=entry.get("id")))

    def _resolver_api(self):
        api = getattr(self._thread_api, "api", None)
        if api is None:
            api = ApiSoap(self.username, self.password, debug=self.debug, debug_hook=self.debug_hook, i18n=self.i18n)
            api.token = self.api.token
            api.account_id = self.api.account_id
            api.account_name = self.api.account_name
            self._thread_api.api = api
        return api

    def folder_tasks(self, folder, rel_dir):
        tasks = []
        if not folder.get("files"):
            return tasks
        request_path = self.folder_request_path(folder["owner_name"], self.folder_segments(folder))
        for entry in folder["files"]:
            source = DownloadSourceDirect(entry["url"]) if entry.get("url") else DownloadSourceSoap(self, entry, request_path)
            tasks.append((entry["name"], source, rel_dir))
        return tasks

    def read_url(self, url):
        raw_path = self._split_raw_url(url)
        last_error = None
        for candidate in self._candidate_paths(raw_path):
            try:
                folder = self.api.download(candidate, None, None)
            except ChomikujError as exc:
                last_error = exc
                continue
            request_path = "/" + "/".join(self._decoded_segments(candidate))
            folder_segments = self.folder_segments(folder)
            folder_path = "/" + "/".join([folder["owner_name"], *folder_segments]).strip("/")
            if not folder["files"] and request_path != folder_path:
                raise ChomikujError(self.i18n("error.download_unresolved_url", url=url))
            return {
                "folder": folder,
                "is_exact_folder": request_path == folder_path,
            }
        if last_error is not None:
            raise last_error
        raise ChomikujError(self.i18n("error.download_unresolved_url", url=url))

    def _folder_resolver_instance(self):
        if self._folder_resolver is None:
            self._folder_resolver = FolderResolverRequestIdBox(
                self.username,
                self.password,
                self.api.token,
                debug=self.debug,
                debug_hook=self.debug_hook,
                i18n=self.i18n,
            )
        return self._folder_resolver

    def read_folder(self, owner, folder_id, resolved_segments):
        first_error = None
        try:
            req_id = self._folder_resolver_instance().resolve_request_id(owner["name"], folder_id)
            return self.api.download(req_id, None, None)
        except ChomikujError as exc:
            first_error = exc
        folder_path = "/" + "/".join([owner["name"], *resolved_segments]).strip("/")
        if folder_path.strip("/"):
            try:
                return self.api.download(folder_path, None, None)
            except ChomikujError:
                pass
        raise first_error
