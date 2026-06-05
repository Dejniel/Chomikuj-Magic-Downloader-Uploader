#!/usr/bin/env python3

import os
import threading

from .common_local_name import encode_local_component
from .common_runtime import ChomikujError
from .download_worker import DownloadWorker
from .download_planner import DownloadPlanner
from .download_source import DownloadSourceDirect


class DownloadManager:
    def __init__(self, username, password, max_threads, output_dir, debug=False, password_provider=None, status_sink=None, debug_hook=None, flatten=False, keep_original_names=False, recursive=False, i18n=None, config_store=None):
        self.max_threads = int(max_threads)
        self.output_dir = output_dir
        self.status_sink = status_sink
        self.flatten = bool(flatten)
        self.keep_original_names = bool(keep_original_names)
        self.recursive = bool(recursive)
        self.planner = DownloadPlanner(
            username,
            password,
            debug=debug,
            password_provider=password_provider,
            debug_hook=debug_hook,
            flatten=self.flatten,
            recursive=self.recursive,
            i18n=i18n,
            config_store=config_store,
        )
        self.i18n = self.planner.i18n
        self.semaphore = threading.Semaphore(self.max_threads)
        self.threads = []
        self.queued = set()

    def queue_file(self, file_name, source, rel_dir):
        path = self._local_path(file_name, rel_dir)
        if path in self.queued:
            return
        self.queued.add(path)
        if self.status_sink:
            self.status_sink.download_queued(path)
        if isinstance(source, str):
            source = DownloadSourceDirect(source)
        worker = DownloadWorker(self.semaphore, source, path, status_sink=self.status_sink, i18n=self.i18n)
        self.threads.append(worker)
        worker.start()

    def _local_path(self, file_name, rel_dir):
        parts = [self.output_dir]
        if rel_dir:
            segments = [segment for segment in rel_dir.strip("/").split("/") if segment]
            if not self.keep_original_names:
                segments = [encode_local_component(segment) for segment in segments]
            if segments:
                parts.append(os.path.join(*segments))
        if self.keep_original_names:
            parts.append(file_name)
        else:
            parts.append(encode_local_component(file_name, allow_extension=True))
        return os.path.normpath(os.path.join(*parts))

    def handle_url(self, url):
        for file_name, source, rel_dir in self.planner.collect(url):
            self.queue_file(file_name, source, rel_dir)

    def wait(self):
        errors = []
        for thread in self.threads:
            thread.join()
            if thread.error:
                errors.append(thread)
        if errors:
            first = errors[0]
            raise ChomikujError(
                self.i18n("error.download_batch_failed", count=len(errors), path=first.path, error=first.error)
            )
