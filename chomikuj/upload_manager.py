#!/usr/bin/env python3

import os
import threading

from .base_account_folder import BaseAccountFolder
from .common_runtime import ChomikujError
from .upload_worker import UploadWorker


class UploadManager(BaseAccountFolder):
    def __init__(self, username, password, max_threads=2, debug=False, password_provider=None, status_sink=None, debug_hook=None, i18n=None):
        super().__init__(username, password, debug=debug, password_provider=password_provider, debug_hook=debug_hook, i18n=i18n)
        self.max_threads = max(1, int(max_threads or 1))
        self.status_sink = status_sink
        self.semaphore = threading.Semaphore(self.max_threads)
        self.threads = []
        self.pre_errors = []

    def _emit(self, event, *args):
        if self.status_sink:
            handler = getattr(self.status_sink, event, None)
            if handler:
                handler(*args)

    def _split_remote_folder(self, folder):
        if not folder:
            return []
        folder = folder.strip()
        if folder.startswith(("http://", "https://")):
            owner_name, segments = self.split_url(folder)
            owner = self.current_owner()
            if not self.same_name(owner_name, owner["name"]):
                raise ChomikujError(self.i18n("error.upload_account_only"))
            return segments
        return [self.clean(part) for part in folder.split("/") if self.clean(part)]

    def _invalidate_folder_cache(self, owner, folder_id):
        self.folder_cache.pop((owner["id"], str(folder_id)), None)

    def _create_remote_folder(self, owner, parent_id, folder_name):
        payload = self.api.folders_create(folder_name, parent_id)
        folder_id = payload.get("FolderId")
        self._invalidate_folder_cache(owner, parent_id)
        if folder_id:
            return str(folder_id), folder_name
        listing = self.list_folder(owner, parent_id)
        folder = self.find_named_folder(listing["Folders"], folder_name)
        if folder is None:
            raise ChomikujError(self.i18n("error.upload_create_folder", folder_name=folder_name))
        return str(folder["Id"]), folder["Name"]

    def ensure_remote_folder_path(self, owner, segments):
        folder_id, resolved = "0", []
        for segment in segments:
            listing = self.list_folder(owner, folder_id)
            folder = self.find_named_folder(listing["Folders"], segment)
            if folder is None:
                folder_id, folder_name = self._create_remote_folder(owner, folder_id, segment)
                resolved.append(folder_name)
                continue
            folder_id = str(folder["Id"])
            resolved.append(folder["Name"])
        return folder_id, resolved

    def resolve_target_folder(self, folder):
        owner = self.current_owner()
        segments = self._split_remote_folder(folder)
        if not segments:
            return owner, "0", []
        folder_id, resolved = self.ensure_remote_folder_path(owner, segments)
        return owner, folder_id, resolved

    def _record_pre_error(self, path, error, target):
        local_path = os.path.abspath(path)
        exc = error if isinstance(error, Exception) else ChomikujError(str(error))
        self.pre_errors.append((local_path, exc))
        self._emit("upload_failed", local_path, exc, target)

    def _queue_file(self, local_path, folder_id, target):
        worker = UploadWorker(
            self.semaphore,
            self.api.username,
            self.api.password,
            self.api.api_key,
            self.api.account_id,
            self.api.account_name,
            local_path,
            folder_id,
            target,
            status_sink=self.status_sink,
            debug=self.api.debug,
            debug_hook=self.api.debug_hook,
            i18n=self.i18n,
        )
        self.threads.append(worker)
        worker.start()

    def _collect_directory_tasks(self, local_dir, owner, folder_id, resolved, tasks):
        if not os.path.isdir(local_dir):
            raise ChomikujError(self.i18n("error.upload_not_directory", path=local_dir))
        local_name = os.path.basename(os.path.normpath(local_dir))
        remote_folder_id, remote_resolved = self.ensure_remote_folder_path(owner, resolved + [local_name])
        entries = sorted(os.listdir(local_dir), key=str.casefold)
        for entry in entries:
            local_entry = os.path.join(local_dir, entry)
            if os.path.isfile(local_entry):
                tasks.append((os.path.abspath(local_entry), str(remote_folder_id), "/".join(remote_resolved) if remote_resolved else "/"))
            elif os.path.isdir(local_entry):
                try:
                    self._collect_directory_tasks(local_entry, owner, remote_folder_id, remote_resolved, tasks)
                except ChomikujError as exc:
                    self._record_pre_error(local_entry, exc, "/".join(remote_resolved) if remote_resolved else "/")

    def _collect_tasks(self, paths, folder):
        owner, folder_id, resolved = self.resolve_target_folder(folder)
        tasks = []
        for path in paths:
            local_path = os.path.abspath(path)
            target = "/".join(resolved) if resolved else "/"
            if os.path.isfile(local_path):
                tasks.append((local_path, str(folder_id), target))
                continue
            if os.path.isdir(local_path):
                try:
                    self._collect_directory_tasks(local_path, owner, folder_id, resolved, tasks)
                except ChomikujError as exc:
                    self._record_pre_error(local_path, exc, target)
                continue
            self._record_pre_error(local_path, ChomikujError(self.i18n("error.upload_unsupported_path", path=path)), target)
        return tasks

    def upload_files(self, paths, folder=None):
        self.threads = []
        self.pre_errors = []
        tasks = self._collect_tasks(paths, folder)
        for local_path, folder_id, target in tasks:
            self._queue_file(local_path, folder_id, target)
        self.wait()

    def wait(self):
        errors = list(self.pre_errors)
        for thread in self.threads:
            thread.join()
            if thread.error:
                errors.append((thread.local_path, thread.error))
        if errors:
            first_path, first_error = errors[0]
            raise ChomikujError(
                self.i18n("error.upload_batch_failed", count=len(errors), path=first_path, error=first_error)
            )
