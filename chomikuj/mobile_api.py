#!/usr/bin/env python3

import base64
import hashlib
import json
import time
from urllib.parse import quote, urlencode

import requests

from .common import BASE_URL, RETRY_ATTEMPTS, RETRY_BACKOFF_SECONDS, SECRET_KEY, TIMEOUT, USER_AGENT, ApiRequestError, ChomikujError, is_timeout_error
from .i18n import ensure_i18n


class MobileApi:
    """Client for `mobile.chomikuj.pl/api/v3`.

    Public methods use explicit parameters instead of an anonymous `body`,
    so it is immediately clear which fields a given endpoint expects.
    """

    def __init__(self, username, password, debug=False, debug_hook=None, i18n=None):
        self.username = username
        self.password = password
        self.debug = debug
        self.debug_hook = debug_hook
        self.i18n = ensure_i18n(i18n, language="en")
        self.api_key = None
        self.account_id = None
        self.account_name = None
        self.session = requests.Session()

    def _debug(self, message):
        if self.debug and self.debug_hook:
            self.debug_hook(message)

    def _quote(self, value):
        return quote(str(value), safe="")

    def _urlsafe_b64(self, data):
        return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")

    def _token(self, path_query, body=""):
        return hashlib.md5((path_query + body + SECRET_KEY)[1:].encode("utf-8")).hexdigest()

    def _request(self, method, path, query=None, body=None, use_api_key=True):
        query = query or []
        query_string = urlencode(query)
        path_query = path + (f"?{query_string}" if query_string else "")
        body_text = "" if body is None else json.dumps(body, separators=(",", ":"))
        headers = {
            "User-Agent": USER_AGENT,
            "Token": self._token(path_query, body_text),
        }
        if body is not None:
            headers["Content-Type"] = "application/json; charset=utf-8"
        if use_api_key and self.api_key:
            headers["Api-Key"] = self.api_key
        if self.debug:
            self._debug(f"DEBUG {method} {path_query}")
            if body_text:
                self._debug(body_text[:4000])
        attempts = RETRY_ATTEMPTS if method.upper() == "GET" else 1
        for attempt in range(1, attempts + 1):
            try:
                response = self.session.request(
                    method,
                    BASE_URL + path_query,
                    data=body_text or None,
                    headers=headers,
                    timeout=TIMEOUT,
                )
                break
            except requests.RequestException as exc:
                if is_timeout_error(exc):
                    if attempt >= attempts:
                        raise ChomikujError(
                            self.i18n("error.api_timeout", method=method, path=path, attempts=attempts, error=exc)
                        ) from exc
                    if self.debug:
                        self._debug(f"DEBUG timeout {method} {path_query}, attempt {attempt}/{attempts}, retrying")
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                    continue
                raise ChomikujError(self.i18n("error.api_connection", method=method, path=path, error=exc)) from exc
        if self.debug:
            self._debug(f"DEBUG HTTP {response.status_code}")
            self._debug(response.text[:4000])
        if response.ok:
            return response
        code = None
        message = response.text or f"HTTP {response.status_code}"
        try:
            payload = response.json()
            code = payload.get("Code")
            message = payload.get("Message") or payload.get("message") or message
        except ValueError:
            pass
        raise ApiRequestError(response.status_code, code, message, response.text)

    def _json(self, method, path, query=None, body=None, use_api_key=True):
        response = self._request(method, path, query=query, body=body, use_api_key=use_api_key)
        if not response.text:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise ChomikujError(self.i18n("error.api_invalid_json", path=path, error=exc)) from exc

    def activate_payment(self, purchase_info, signature):
        """POST /api/v3/payments/android/activate.

        Parameters:
        - `purchase_info`: raw purchase JSON from Google Play
        - `signature`: purchase signature in base64 from Google Play
        """
        receipt = {
            "PurchaseInfo": self._urlsafe_b64(str(purchase_info).encode("utf-8")),
            "Signature": self._urlsafe_b64(base64.b64decode(signature)),
        }
        payload = {"ReceiptData": self._urlsafe_b64(json.dumps(receipt, separators=(",", ":")).encode("utf-8"))}
        return self._json("POST", "/api/v3/payments/android/activate", body=payload)

    def account_info(self):
        """GET /api/v3/account/info. Basic information about the logged-in account."""
        return self._json("GET", "/api/v3/account/info")

    def account_login(self):
        """POST /api/v3/account/login.

        Parameters:
        - uses `username` and `password` passed to the constructor
        """
        payload = self._json(
            "POST",
            "/api/v3/account/login",
            body={"AccountName": self.username, "Password": self.password},
            use_api_key=False,
        )
        self.api_key = payload.get("ApiKey")
        self.account_id = str(payload.get("AccountId") or "")
        self.account_name = payload.get("AccountName") or self.username
        if not self.api_key:
            raise ChomikujError(self.i18n("error.api_missing_key"))
        return payload

    def account_password_read(self, account_id, password):
        """POST /api/v3/account/passwords/read.

        Parameters:
        - `account_id`: account ID protected by a password
        - `password`: password for the account resources
        """
        return self._json(
            "POST",
            "/api/v3/account/passwords/read",
            body={"AccountId": str(account_id), "Password": password},
        )

    def account_password_recover(self, account_name, email):
        """POST /api/v3/account/password/recover.

        Parameters:
        - `account_name`: account name
        - `email`: email assigned to the account
        """
        payload = {"AccountName": account_name, "Email": email}
        return self._json("POST", "/api/v3/account/password/recover", body=payload, use_api_key=False)

    def account_register(self, account_name, password, email):
        """POST /api/v3/account/register.

        Parameters:
        - `account_name`: new account name
        - `password`: new account password
        - `email`: new account email
        """
        payload = {"AccountName": account_name, "Password": password, "Email": email}
        return self._json("POST", "/api/v3/account/register", body=payload, use_api_key=False)

    def account_search(self, account_name, page=1):
        """GET /api/v3/account/search.

        Parameters:
        - `account_name`: account name or a fragment of it
        - `page`: results page number
        """
        return self._json(
            "GET",
            "/api/v3/account/search",
            query=[("Query", account_name), ("PageNumber", str(page))],
        )

    def account_transfer(self):
        """GET /api/v3/account/transfer. Account balance and transfer information."""
        return self._json("GET", "/api/v3/account/transfer")

    def account_validate_email(self, email):
        """GET /api/v3/account/register/validate/email.

        Parameters:
        - `email`: email to validate
        """
        return self._json("GET", "/api/v3/account/register/validate/email", query=[("email", email)], use_api_key=False)

    def account_validate_name(self, account_name):
        """GET /api/v3/account/register/validate/accountName.

        Parameters:
        - `account_name`: account name to validate
        """
        return self._json(
            "GET",
            "/api/v3/account/register/validate/accountName",
            query=[("accountName", account_name)],
            use_api_key=False,
        )

    def files_change_name(self, file_id, file_name):
        """POST /api/v3/files/changeName.

        Parameters:
        - `file_id`: file ID
        - `file_name`: new file name without changing the extension
        """
        payload = {"FileId": int(file_id), "FileName": file_name}
        return self._json("POST", "/api/v3/files/changeName", body=payload)

    def files_copies_get(self, query=None):
        """GET /api/v3/files/copies.

        Parameters:
        - `query`: optional list of `(key, value)` pairs for pagination or filters
        """
        return self._json("GET", "/api/v3/files/copies", query=query)

    def files_copies_post(self, owner_account_id, file_id):
        """POST /api/v3/files/copies.

        Parameters:
        - `owner_account_id`: owner ID of the original file
        - `file_id`: ID of the file to save to your account
        """
        payload = {"OwnerAccountId": str(owner_account_id), "FileId": int(file_id)}
        return self._json("POST", "/api/v3/files/copies", body=payload)

    def files_delete(self, file_ids=None, folder_ids=None):
        """POST /api/v3/files/delete.

        Parameters:
        - `file_ids`: list of file IDs to delete
        - `folder_ids`: list of folder IDs to delete
        """
        payload = {
            "Files": [int(file_id) for file_id in (file_ids or [])],
            "Folders": [int(folder_id) for folder_id in (folder_ids or [])],
        }
        return self._json("POST", "/api/v3/files/delete", body=payload)

    def files_download(self, file_id):
        """GET /api/v3/files/download.

        Parameters:
        - `file_id`: file ID to download
        """
        return self._json("GET", "/api/v3/files/download", query=[("fileId", str(file_id))])

    def files_move(self, source_folder_id, target_folder_id, file_ids=None, folder_ids=None):
        """POST /api/v3/files/move.

        Parameters:
        - `source_folder_id`: source folder
        - `target_folder_id`: target folder
        - `file_ids`: list of file IDs to move
        - `folder_ids`: list of folder IDs to move
        """
        payload = {
            "SourceFolderId": str(source_folder_id),
            "TargetFolderId": str(target_folder_id),
            "Files": [int(file_id) for file_id in (file_ids or [])],
            "Folders": [int(folder_id) for folder_id in (folder_ids or [])],
        }
        return self._json("POST", "/api/v3/files/move", body=payload)

    def files_search(self, query):
        """GET /api/v3/files/search.

        Parameters:
        - `query`: list of `(key, value)` pairs with search filters
        """
        return self._json("GET", "/api/v3/files/search", query=query)

    def files_upload_partial(self, name, size, folder_id, hash_value):
        """POST /api/v3/files/upload/partialUpload.

        Parameters:
        - `name`: file name
        - `size`: file size in bytes
        - `folder_id`: target folder
        - `hash_value`: CRC/hash of the file
        """
        payload = {"Name": name, "Size": int(size), "FolderId": str(folder_id), "Hash": str(hash_value)}
        return self._json("POST", "/api/v3/files/upload/partialUpload", body=payload)

    def folders_change_name(self, folder_id, folder_name):
        """POST /api/v3/folders/changeName.

        Parameters:
        - `folder_id`: folder ID
        - `folder_name`: new folder name
        """
        payload = {"FolderId": str(folder_id), "FolderName": folder_name}
        return self._json("POST", "/api/v3/folders/changeName", body=payload)

    def folders_change_password(self, folder_id, password):
        """POST /api/v3/folders/changePassword.

        Parameters:
        - `folder_id`: folder ID
        - `password`: new folder password
        """
        payload = {"FolderId": str(folder_id), "Password": password}
        return self._json("POST", "/api/v3/folders/changePassword", body=payload)

    def folders_create(self, folder_name, parent_id):
        """POST /api/v3/folders/create.

        Parameters:
        - `folder_name`: new folder name
        - `parent_id`: parent folder ID
        """
        payload = {"FolderName": folder_name, "ParentId": str(parent_id)}
        return self._json("POST", "/api/v3/folders/create", body=payload)

    def folders_download_items(self, account_id, folder_id):
        """GET /api/v3/folders/download/items.

        Parameters:
        - `account_id`: folder owner ID
        - `folder_id`: folder ID
        """
        return self._json(
            "GET",
            "/api/v3/folders/download/items",
            query=[("accountId", str(account_id)), ("folderId", str(folder_id))],
        )

    def folders_get(self, account_id, folder_id, page=1):
        """GET /api/v3/folders.

        Parameters:
        - `account_id`: folder owner ID; omit or pass empty for the logged-in account
        - `folder_id`: folder ID or `0` for root
        - `page`: listing page number
        """
        query = [("Parent", str(folder_id)), ("page", str(page))]
        if account_id:
            query.insert(0, ("AccountId", str(account_id)))
        return self._json(
            "GET",
            "/api/v3/folders",
            query=query,
        )

    def folders_password(self, account_id, folder_id, password):
        """POST /api/v3/folders/password.

        Parameters:
        - `account_id`: folder owner ID
        - `folder_id`: folder ID
        - `password`: password required to open the folder
        """
        return self._json(
            "POST",
            "/api/v3/folders/password",
            body={"AccountId": str(account_id), "FolderId": str(folder_id), "Password": password},
        )

    def friends_add(self, account_id):
        """POST /api/v3/friends.

        Parameters:
        - `account_id`: account ID to add as a friend
        """
        return self._json("POST", "/api/v3/friends", body={"id": str(account_id)})

    def friends_delete(self, friend_id):
        """DELETE /api/v3/friends/{id}.

        Parameters:
        - `friend_id`: friend ID
        """
        return self._json("DELETE", f"/api/v3/friends/{self._quote(friend_id)}")

    def friends_get(self):
        """GET /api/v3/friends. Friends list."""
        return self._json("GET", "/api/v3/friends")

    def instance_modules(self):
        """GET /api/v3/instance/modules. Application module flags."""
        return self._json("GET", "/api/v3/instance/modules")

    def messages_block_sender(self, message_id):
        """POST /api/v3/messages/{id}/blockSender.

        Parameters:
        - `message_id`: message ID from the sender to block
        """
        return self._json("POST", f"/api/v3/messages/{self._quote(message_id)}/blockSender")

    def messages_delete(self, message_id):
        """DELETE /api/v3/messages/{id}.

        Parameters:
        - `message_id`: message ID
        """
        return self._json("DELETE", f"/api/v3/messages/{self._quote(message_id)}")

    def messages_get(self, message_id):
        """GET /api/v3/messages/{id}.

        Parameters:
        - `message_id`: message ID
        """
        return self._json("GET", f"/api/v3/messages/{self._quote(message_id)}")

    def messages_inbox(self, query=None):
        """GET /api/v3/messages/inbox.

        Parameters:
        - `query`: optional list of `(key, value)` pairs for pagination
        """
        return self._json("GET", "/api/v3/messages/inbox", query=query)

    def messages_mark_all_read(self):
        """POST /api/v3/messages/markAllAsRead. Mark all messages as read."""
        return self._json("POST", "/api/v3/messages/markAllAsRead")

    def messages_outbox(self, query=None):
        """GET /api/v3/messages/outbox.

        Parameters:
        - `query`: optional list of `(key, value)` pairs for pagination
        """
        return self._json("GET", "/api/v3/messages/outbox", query=query)

    def messages_reply(self, message_id, subject, body_text, email=None):
        """POST /api/v3/messages/{id}/reply.

        Parameters:
        - `message_id`: message ID
        - `subject`: reply subject
        - `body_text`: reply body
        - `email`: optional contact email
        """
        payload = {"Subject": subject, "Body": body_text}
        if email:
            payload["Email"] = email
        return self._json("POST", f"/api/v3/messages/{self._quote(message_id)}/reply", body=payload)

    def messages_report_fraud(self, message_id):
        """POST /api/v3/messages/{id}/markAsFraud.

        Parameters:
        - `message_id`: message ID
        """
        return self._json("POST", f"/api/v3/messages/{self._quote(message_id)}/markAsFraud")

    def messages_report_spam(self, message_id):
        """POST /api/v3/messages/{id}/markAsSpam.

        Parameters:
        - `message_id`: message ID
        """
        return self._json("POST", f"/api/v3/messages/{self._quote(message_id)}/markAsSpam")

    def messages_send(self, account_to, subject, body_text):
        """POST /api/v3/messages/send.

        Parameters:
        - `account_to`: recipient name or ID
        - `subject`: subject
        - `body_text`: message body
        """
        payload = {"AccountTo": str(account_to), "Subject": subject, "Body": body_text}
        return self._json("POST", "/api/v3/messages/send", body=payload)

    def synchronization_state(self):
        """GET /api/v3/synchronization/state. Synchronization backup state."""
        return self._json("GET", "/api/v3/synchronization/state")

    def synchronization_upload(self, name, extension, size, hash_value, media_type, last_modified):
        """POST /api/v3/synchronization/upload.

        Parameters:
        - `name`: file name
        - `extension`: extension without the dot
        - `size`: file size in bytes
        - `hash_value`: CRC/hash of the file
        - `media_type`: media type number used by the app
        - `last_modified`: file modification timestamp
        """
        payload = {
            "Name": name,
            "Extension": extension,
            "Size": int(size),
            "Hash": str(hash_value),
            "MediaType": int(media_type),
            "LastModified": int(last_modified),
        }
        return self._json("POST", "/api/v3/synchronization/upload", body=payload)
