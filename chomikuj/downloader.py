#!/usr/bin/env python3

import os
import threading

from .base import ChomikujBase
from .common import ChomikujError
from .download_item import DownloadItem


class ChomikujDownloader(ChomikujBase):
    def __init__(self, username, password, max_threads, output_dir, debug=False, password_provider=None, status_sink=None, debug_hook=None):
        super().__init__(username, password, debug=debug, password_provider=password_provider, debug_hook=debug_hook)
        self.max_threads = int(max_threads)
        self.output_dir = output_dir
        self.status_sink = status_sink
        self.semaphore = threading.Semaphore(self.max_threads)
        self.threads = []
        self.queued = set()

    def download_url(self, file_id):
        payload = self.api.files_download(file_id)
        code = payload.get("Code")
        if code not in (0, 605):
            raise ChomikujError(f"Blad files/download dla fileId={file_id}: {code}")
        if not payload.get("FileUrl"):
            raise ChomikujError(f"Brak FileUrl dla fileId={file_id}")
        return payload["FileUrl"]

    def queue_file(self, file_name, url, rel_dir):
        if rel_dir:
            path = os.path.join(self.output_dir, rel_dir.strip("/"), file_name)
        else:
            path = os.path.join(self.output_dir, file_name)
        path = os.path.normpath(path)
        if path in self.queued:
            return
        self.queued.add(path)
        if self.status_sink:
            self.status_sink.download_queued(path)
        item = DownloadItem(self.semaphore, url, path, status_sink=self.status_sink)
        self.threads.append(item)
        item.start()

    def queue_file_by_id(self, file_id, file_name, rel_dir):
        self.queue_file(file_name, self.download_url(file_id), rel_dir)

    def add_folder_recursive(self, owner, folder_id, rel_dir):
        listing = self.list_folder(owner, folder_id)
        for entry in listing["Files"]:
            self.queue_file_by_id(entry["FileId"], self.file_name(entry), rel_dir)
        for folder in listing["Folders"]:
            child_rel_dir = f"{rel_dir}/{folder['Name']}".strip("/")
            self.add_folder_recursive(owner, folder["Id"], child_rel_dir)

    def handle_url(self, url):
        owner_name, segments = self.split_url(url)
        owner = self.owner_info(owner_name)
        if not segments:
            self.add_folder_recursive(owner, "0", "")
            return
        folder_id, _ = self.resolve_folder_path(owner, segments)
        if folder_id is not None:
            self.add_folder_recursive(owner, folder_id, "")
            return
        parent_id, resolved = self.resolve_folder_path(owner, segments[:-1])
        if parent_id is not None:
            entry = self.find_file_in_folder(owner, parent_id, segments[-1])
            if entry is not None:
                self.queue_file_by_id(entry["FileId"], self.file_name(entry), "/".join(resolved))
                return
        raise ChomikujError(f"Nie udalo sie rozpoznac URL-a przez nowe API: {url}")

    def wait(self):
        errors = []
        for thread in self.threads:
            thread.join()
            if thread.error:
                errors.append(thread)
        if errors:
            first = errors[0]
            raise ChomikujError(f"{len(errors)} pobran zakonczonych bledem. Pierwszy: {first.path}: {first.error}")
