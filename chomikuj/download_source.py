#!/usr/bin/env python3

from .common_runtime import ApiRequestError, FileUnavailableError


class DownloadSourceDirect:
    def __init__(self, url):
        self.url = url

    def resolve_url(self):
        return self.url


class DownloadSourceSoap:
    def __init__(self, reader, entry, folder_request_path):
        self.reader = reader
        self.entry = entry
        self.folder_request_path = folder_request_path

    def resolve_url(self):
        return self.reader.download_url(self.entry, self.folder_request_path)


class DownloadSourceMobile:
    def __init__(self, reader, entry, fallback_source=None):
        self.reader = reader
        self.entry = entry
        self.fallback_source = fallback_source

    def resolve_url(self):
        try:
            return self.reader.download_url(self.entry["FileId"])
        except FileUnavailableError:
            if self.fallback_source is None:
                raise
        except ApiRequestError as exc:
            if self.fallback_source is None or exc.status != 404:
                raise
        return self.fallback_source.resolve_url()
