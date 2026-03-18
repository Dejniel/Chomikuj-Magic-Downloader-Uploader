#!/usr/bin/env python3

from .common import ChomikujError, PasswordSkippedError
from .download_reader_soap import DownloadReaderSoap
from .download_reader_v3 import DownloadReaderV3
from .download_source import DownloadSourceSoap, DownloadSourceV3
from .i18n import ensure_i18n


class DownloadPlanner:
    def __init__(self, username, password, debug=False, password_provider=None, debug_hook=None, flatten=False, recursive=False, i18n=None):
        self.username = username
        self.password = password
        self.debug = debug
        self.password_provider = password_provider
        self.debug_hook = debug_hook
        self.flatten = bool(flatten)
        self.recursive = bool(recursive)
        self.i18n = ensure_i18n(i18n, language="en")
        self._reader_soap = None
        self._reader_v3 = None

    @property
    def soap(self):
        if self._reader_soap is None:
            self._reader_soap = DownloadReaderSoap(
                self.username,
                self.password,
                debug=self.debug,
                debug_hook=self.debug_hook,
                i18n=self.i18n,
            )
        return self._reader_soap

    @property
    def v3(self):
        if self._reader_v3 is None:
            self._reader_v3 = DownloadReaderV3(
                self.username,
                self.password,
                debug=self.debug,
                password_provider=self.password_provider,
                debug_hook=self.debug_hook,
                i18n=self.i18n,
            )
        return self._reader_v3

    def _rel_dir(self, owner_name, resolved_segments):
        if self.flatten:
            return ""
        return "/".join([owner_name, *resolved_segments]).strip("/")

    def _display_path(self, owner_name, resolved_segments):
        parts = [part for part in [owner_name, *resolved_segments] if part]
        return "/".join(parts)

    def _recursive_error(self, owner_name, resolved_segments):
        raise ChomikujError(
            self.i18n(
                "error.download_recursive_unavailable",
                path=self._display_path(owner_name, resolved_segments),
            )
        )

    def _soap_current(self, url):
        result = self.soap.read_url(url)
        rel_dir = self._rel_dir(result["folder"]["owner_name"], self.soap.folder_segments(result["folder"]))
        return {
            "folder": result["folder"],
            "tasks": self.soap.folder_tasks(result["folder"], rel_dir),
            "is_exact_folder": result["is_exact_folder"],
        }

    def _folder_tasks(self, owner, resolved_segments, v3_listing, soap_folder):
        rel_dir = self._rel_dir(owner["name"], resolved_segments)
        fallback_by_id = {}
        if soap_folder:
            soap_ids = {str(entry.get("id")) for entry in soap_folder.get("files", []) if entry.get("id")}
            v3_ids = {str(entry.get("FileId")) for entry in v3_listing.get("Files", []) if entry.get("FileId")}
            # Some folders that contain pathological transfer-cost files are
            # returned incompletely by v3: once such files appear, other files in
            # the same folder can go missing from the whole v3 listing. When SOAP
            # sees extra ids or a different file set for the same folder, trust
            # SOAP for that folder instead of mixing an already truncated v3 view.
            if soap_ids and (len(soap_ids) > len(v3_ids) or not soap_ids.issubset(v3_ids)):
                return self.soap.folder_tasks(soap_folder, rel_dir)
            request_path = self.soap.folder_request_path(owner["name"], resolved_segments)
            for entry in soap_folder.get("files", []):
                fallback_by_id[str(entry.get("id"))] = DownloadSourceSoap(self.soap, entry, request_path)

        tasks = []
        for entry in v3_listing.get("Files", []):
            fallback_source = fallback_by_id.get(str(entry.get("FileId")))
            tasks.append((self.v3.file_name(entry), DownloadSourceV3(self.v3, entry, fallback_source=fallback_source), rel_dir))
        return tasks

    def _collect_folder_recursive(self, tasks, owner, folder_id, resolved_segments):
        soap_folder = None
        try:
            soap_folder = self.soap.read_folder(owner, folder_id, resolved_segments)
        except ChomikujError:
            soap_folder = None

        try:
            v3_listing = self.v3.list_folder(owner, folder_id)
        except PasswordSkippedError:
            return
        except ChomikujError:
            if soap_folder is not None:
                self._recursive_error(owner["name"], resolved_segments)
            raise

        tasks.extend(self._folder_tasks(owner, resolved_segments, v3_listing, soap_folder))
        for child in v3_listing.get("Folders", []):
            self._collect_folder_recursive(tasks, owner, str(child["Id"]), resolved_segments + [child["Name"]])

    def _collect_recursive(self, url):
        try:
            owner_name, segments = self.v3.split_url(url)
            owner = self.v3.owner_info(owner_name)
            if not segments:
                tasks = []
                self._collect_folder_recursive(tasks, owner, "0", [])
                return tasks
            folder_id, resolved = self.v3.resolve_folder_path(owner, segments)
        except PasswordSkippedError:
            return []
        except ChomikujError as exc:
            try:
                soap_result = self._soap_current(url)
            except ChomikujError:
                raise exc
            if soap_result["tasks"] and not soap_result["is_exact_folder"]:
                return soap_result["tasks"]
            if soap_result["is_exact_folder"]:
                self._recursive_error(soap_result["folder"]["owner_name"], self.soap.folder_segments(soap_result["folder"]))
            raise exc

        if folder_id is not None:
            tasks = []
            self._collect_folder_recursive(tasks, owner, folder_id, resolved)
            return tasks

        soap_result = self._soap_current(url)
        if soap_result["tasks"] and not soap_result["is_exact_folder"]:
            return soap_result["tasks"]
        if soap_result["is_exact_folder"]:
            self._recursive_error(soap_result["folder"]["owner_name"], self.soap.folder_segments(soap_result["folder"]))
        raise ChomikujError(self.i18n("error.download_unresolved_url", url=url))

    def collect(self, url):
        if not self.recursive:
            return self._soap_current(url)["tasks"]
        return self._collect_recursive(url)
