#!/usr/bin/env python3

import os
import re
import time
import zlib

import requests

from .base import ChomikujBase
from .common import TIMEOUT, USER_AGENT, ChomikujError

CHUNK_SIZE = 524288


class ChomikujUploader(ChomikujBase):
    def __init__(self, username, password, debug=False, password_provider=None, status_sink=None, debug_hook=None):
        super().__init__(username, password, debug=debug, password_provider=password_provider, debug_hook=debug_hook)
        self.status_sink = status_sink

    def _emit(self, event, *args):
        if self.status_sink:
            handler = getattr(self.status_sink, event, None)
            if handler:
                handler(*args)

    def _crc32(self, path):
        crc = 0
        with open(path, "rb") as handle:
            while True:
                chunk = handle.read(65536)
                if not chunk:
                    break
                crc = zlib.crc32(chunk, crc)
        return format(crc & 0xFFFFFFFF, "x")

    def _escape_file_name(self, name):
        return re.sub(r'[\?\:\<\>\/\*"\\\\]+', "_", name)

    def _split_remote_folder(self, folder):
        if not folder:
            return []
        folder = folder.strip()
        if folder.startswith(("http://", "https://")):
            owner_name, segments = self.split_url(folder)
            owner = self.current_owner()
            if not self.same_name(owner_name, owner["name"]):
                raise ChomikujError("Upload is only possible to your own account")
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
            raise ChomikujError(f"Failed to create remote folder: {folder_name}")
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

    def _upload_chunk(self, path, name, upload_url, offset, size):
        boundary = f"***{int(time.time() * 1000)}***"
        with open(path, "rb") as handle:
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
            raise ChomikujError(f"Connection error during upload of {path}: {exc}") from exc
        return response.status_code, next_offset

    def _upload_file_to_folder(self, path, owner, folder_id, resolved):
        local_path = os.path.abspath(path)
        if not os.path.isfile(local_path):
            raise ChomikujError(f"This is not a file for upload: {path}")
        name = os.path.basename(local_path)
        size = os.path.getsize(local_path)
        crc = self._crc32(local_path)
        target = "/".join(resolved) if resolved else "/"
        self._emit("upload_started", local_path, target, size)
        payload = self.api.files_upload_partial(name, size, folder_id, crc)
        if payload.get("UploadCompleted"):
            self._emit("upload_finished", local_path, target, size)
            return
        upload_url = payload.get("Url")
        if not upload_url:
            self._emit("upload_failed", local_path, ChomikujError(f"Missing URL after partialUpload for file: {path}"), target)
            raise ChomikujError(f"Missing URL after partialUpload for file: {path}")
        uploaded = int(payload.get("Chunk") or 0)
        self._emit("upload_progress", local_path, uploaded, size, target)
        while True:
            status, uploaded = self._upload_chunk(local_path, name, upload_url, uploaded, size)
            self._emit("upload_progress", local_path, uploaded, size, target)
            if status == 200:
                self._emit("upload_finished", local_path, target, size)
                return
            if status == 206:
                continue
            if status == 408:
                self._emit("upload_failed", local_path, ChomikujError(f"Upload timeout for file: {path}"), target)
                raise ChomikujError(f"Upload timeout for file: {path}")
            if status == 409:
                self._emit("upload_failed", local_path, ChomikujError(f"Upload conflict for file: {path}"), target)
                raise ChomikujError(f"Upload conflict for file: {path}")
            if status == 410:
                self._emit("upload_failed", local_path, ChomikujError(f"Upload session expired for file: {path}"), target)
                raise ChomikujError(f"Upload session expired for file: {path}")
            if status == 500:
                self._emit("upload_failed", local_path, ChomikujError(f"Upload internal error for file: {path}"), target)
                raise ChomikujError(f"Upload internal error for file: {path}")
            self._emit("upload_failed", local_path, ChomikujError(f"Unknown upload error {status} for {path} to {target}"), target)
            raise ChomikujError(f"Unknown upload error {status} for {path} to {target}")

    def _upload_directory_to_folder(self, path, owner, folder_id, resolved):
        local_dir = os.path.abspath(path)
        if not os.path.isdir(local_dir):
            raise ChomikujError(f"This is not a directory for upload: {path}")
        local_name = os.path.basename(os.path.normpath(local_dir))
        remote_folder_id, remote_resolved = self.ensure_remote_folder_path(owner, resolved + [local_name])
        entries = sorted(os.listdir(local_dir), key=str.casefold)
        for entry in entries:
            local_entry = os.path.join(local_dir, entry)
            if os.path.isfile(local_entry):
                self._upload_file_to_folder(local_entry, owner, remote_folder_id, remote_resolved)
            elif os.path.isdir(local_entry):
                self._upload_directory_to_folder(local_entry, owner, remote_folder_id, remote_resolved)

    def upload_files(self, paths, folder=None):
        owner, folder_id, resolved = self.resolve_target_folder(folder)
        for path in paths:
            local_path = os.path.abspath(path)
            if os.path.isfile(local_path):
                self._upload_file_to_folder(local_path, owner, folder_id, resolved)
            elif os.path.isdir(local_path):
                self._upload_directory_to_folder(local_path, owner, folder_id, resolved)
            else:
                raise ChomikujError(f"Unsupported upload path: {path}")
