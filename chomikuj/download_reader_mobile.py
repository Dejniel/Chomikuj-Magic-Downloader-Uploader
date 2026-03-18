#!/usr/bin/env python3

from .base_account_folder import BaseAccountFolder
from .common_runtime import ChomikujError, FileUnavailableError
from .i18n import ensure_i18n


class DownloadReaderMobile(BaseAccountFolder):
    def __init__(self, username, password, debug=False, password_provider=None, debug_hook=None, i18n=None):
        self.i18n = ensure_i18n(i18n, language="en")
        super().__init__(
            username,
            password,
            debug=debug,
            password_provider=password_provider,
            debug_hook=debug_hook,
            i18n=self.i18n,
            allow_password_skip=True,
        )

    def download_url(self, file_id):
        payload = self.api.files_download(file_id)
        # TODO: Do not add a suspicious-transfer skip to the mobile path blindly.
        # The current mobile /api/v3/files/download payload exposes FileUrl,
        # Code, Message, LicenseValidTo and AccountBalance, but no confirmed
        # per-file transfer cost. The pathological files found so far are not
        # visible in the mobile API at all, so there is nothing reliable to
        # compare or skip on the mobile path yet. Revisit only after finding a
        # real mobile-visible file whose transfer cost can be observed and
        # verified end-to-end.
        code = payload.get("Code")
        message = (payload.get("Message") or "").strip()
        if code == 604:
            raise FileUnavailableError(file_id, code, message, i18n=self.i18n)
        if code not in (0, 605):
            suffix = f": {code}"
            if message:
                suffix += f" {message}"
            raise ChomikujError(self.i18n("error.download_api", file_id=file_id, suffix=suffix))
        if not payload.get("FileUrl"):
            if code == 605:
                raise FileUnavailableError(file_id, code, message, i18n=self.i18n)
            raise ChomikujError(self.i18n("error.download_missing_url", file_id=file_id))
        return payload["FileUrl"]
