#!/usr/bin/env python3

import re
from urllib.parse import unquote_plus, urlsplit

from .common import FILE_ID_RE, ApiRequestError, ChomikujError
from .mobile_api import MobileApi


class ChomikujBase:
    def __init__(self, username, password, debug=False, password_provider=None, debug_hook=None):
        self.api = MobileApi(username, password, debug=debug, debug_hook=debug_hook)
        self.api.account_login()
        self.debug = debug
        self.password_provider = password_provider
        self.owner_cache = {}
        self.folder_cache = {}
        self.account_passwords = {}
        self.folder_passwords = {}

    def clean(self, value):
        value = re.sub(r"\*([0-9a-fA-F]{2})", r"%\1", str(value))
        return unquote_plus(value).strip().strip("/")

    def same_name(self, left, right):
        return self.clean(left).casefold() == self.clean(right).casefold()

    def file_name(self, entry):
        name = entry.get("FileName") or ""
        ext = (entry.get("FileType") or "").strip()
        return f"{name}.{ext}" if ext and not name.lower().endswith("." + ext.lower()) else name

    def account_password(self, owner_name):
        if owner_name not in self.account_passwords:
            if not self.password_provider:
                raise ChomikujError(f"Password required for protected resources of user {owner_name}")
            password = self.password_provider("account", owner_name)
            if not password:
                raise ChomikujError(f"No password provided for protected resources of user {owner_name}")
            self.account_passwords[owner_name] = password
        return self.account_passwords[owner_name]

    def folder_password(self, folder_key):
        if folder_key not in self.folder_passwords:
            if not self.password_provider:
                raise ChomikujError(f"Password required for folder {folder_key}")
            password = self.password_provider("folder", folder_key)
            if not password:
                raise ChomikujError(f"No password provided for folder {folder_key}")
            self.folder_passwords[folder_key] = password
        return self.folder_passwords[folder_key]

    def owner_info(self, owner_name):
        key = self.clean(owner_name).casefold()
        if key in self.owner_cache:
            return self.owner_cache[key]
        login_name = self.api.account_name or self.api.username
        if self.same_name(login_name, owner_name):
            owner = self.current_owner()
            self.owner_cache[key] = owner
            return owner
        owner = self._search_owner(owner_name)
        self.owner_cache[key] = owner
        return owner

    def _search_owner(self, owner_name):
        page = 1
        matches = []
        while True:
            payload = self.api.account_search(owner_name, page)
            for result in payload.get("Results", []):
                if self.same_name(result.get("AccountName", ""), owner_name):
                    matches.append(result)
            if matches or not payload.get("IsNextPageAvailable"):
                break
            page += 1
        if not matches:
            raise ChomikujError(f"Account not found for name: {owner_name}")
        if len(matches) > 1:
            raise ChomikujError(f"Ambiguous account name: {owner_name}")
        return {"id": str(matches[0]["AccountId"]), "name": matches[0]["AccountName"]}

    def current_owner(self):
        if "__current_owner__" in self.owner_cache:
            return self.owner_cache["__current_owner__"]
        owner_name = self.api.account_name or self.api.username
        try:
            owner = self._search_owner(owner_name)
        except ChomikujError:
            if not self.api.account_id:
                raise
            owner = {"id": self.api.account_id, "name": owner_name}
        self.owner_cache["__current_owner__"] = owner
        self.owner_cache[self.clean(owner["name"]).casefold()] = owner
        return owner

    def list_folder(self, owner, folder_id):
        key = (owner["id"], str(folder_id))
        if key in self.folder_cache:
            return self.folder_cache[key]
        result = {"Folders": [], "Files": [], "Owner": None, "ParentId": None, "ParentName": None}
        page = 1
        account_id = owner["id"]
        if self.api.account_id and str(owner["id"]) == str(self.api.account_id):
            account_id = None
        while True:
            try:
                payload = self.api.folders_get(account_id, folder_id, page)
            except ApiRequestError as exc:
                if exc.status == 401 and exc.code == 2:
                    self.api.account_password_read(owner["id"], self.account_password(owner["name"]))
                    continue
                if exc.status == 401 and exc.code == 12:
                    self.api.folders_password(owner["id"], folder_id, self.folder_password(f"{owner['name']}:{folder_id}"))
                    continue
                raise
            result["Folders"].extend(payload.get("Folders", []))
            result["Files"].extend(payload.get("Files", []))
            result["Owner"] = payload.get("Owner", result["Owner"])
            result["ParentId"] = payload.get("ParentId", result["ParentId"])
            result["ParentName"] = payload.get("ParentName", result["ParentName"])
            if not payload.get("IsNextPageAvailable"):
                break
            page += 1
        self.folder_cache[key] = result
        return result

    def split_url(self, url):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or parsed.netloc not in ("chomikuj.pl", "www.chomikuj.pl"):
            raise ChomikujError(f"Unsupported URL: {url}")
        parts = [self.clean(part) for part in parsed.path.split("/") if part]
        if not parts:
            raise ChomikujError(f"Invalid URL: {url}")
        return parts[0], parts[1:]

    def find_named_folder(self, folders, segment):
        matches = [folder for folder in folders if self.same_name(folder.get("Name", ""), segment)]
        if len(matches) > 1:
            raise ChomikujError(f"Ambiguous folder: {segment}")
        return matches[0] if matches else None

    def resolve_folder_path(self, owner, segments):
        folder_id, resolved = "0", []
        for segment in segments:
            folder = self.find_named_folder(self.list_folder(owner, folder_id)["Folders"], segment)
            if folder is None:
                return None, resolved
            folder_id = str(folder["Id"])
            resolved.append(folder["Name"])
        return folder_id, resolved

    def extract_file_id(self, segment):
        match = FILE_ID_RE.search(self.clean(segment))
        return match.group(1) if match else None

    def find_file_in_folder(self, owner, folder_id, segment):
        listing = self.list_folder(owner, folder_id)
        file_id = self.extract_file_id(segment)
        if file_id:
            for entry in listing["Files"]:
                if str(entry.get("FileId")) == file_id:
                    return entry
        names = {self.clean(segment).casefold()}
        for entry in listing["Files"]:
            if self.clean(self.file_name(entry)).casefold() in names:
                return entry
            if self.clean(entry.get("FileName", "")).casefold() in names:
                return entry
        return None
