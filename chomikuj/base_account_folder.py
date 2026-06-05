#!/usr/bin/env python3

import re
from urllib.parse import unquote_plus, urlsplit

from .config_store import ConfigStore
from .common_runtime import FILE_ID_RE, ApiRequestError, ChomikujError, PasswordSkippedError
from .i18n import ensure_i18n
from .api_mobile import ApiMobile


class BaseAccountFolder:
    def __init__(self, username, password, debug=False, password_provider=None, debug_hook=None, i18n=None, allow_password_skip=False, config_store=None):
        self.i18n = ensure_i18n(i18n, language="en")
        self.api = ApiMobile(username, password, debug=debug, debug_hook=debug_hook, i18n=self.i18n)
        self.api.account_login()
        self.debug = debug
        self.password_provider = password_provider
        self.allow_password_skip = bool(allow_password_skip)
        self.config_store = config_store or ConfigStore()
        self.owner_cache = {}
        self.folder_cache = {}
        self.account_passwords = {}
        self.folder_passwords = {}
        self.owner_passwords = {}

    def clean(self, value):
        value = re.sub(r"\*([0-9a-fA-F]{2})", r"%\1", str(value))
        return unquote_plus(value).strip().strip("/")

    def same_name(self, left, right):
        return self.clean(left).casefold() == self.clean(right).casefold()

    def file_name(self, entry):
        name = entry.get("FileName") or ""
        ext = (entry.get("FileType") or "").strip()
        return f"{name}.{ext}" if ext and not name.lower().endswith("." + ext.lower()) else name

    def _owner_key(self, owner_name):
        return self.clean(owner_name).casefold()

    def _remember_owner_password(self, owner_name, password):
        if not password:
            return
        owner_key = self._owner_key(owner_name)
        passwords = self.owner_passwords.setdefault(owner_key, [])
        if password in passwords:
            passwords.remove(password)
        passwords.insert(0, password)
        self.config_store.set_owner_password(owner_key, password)

    def _folder_password_key(self, owner_name, folder_id):
        return f"{self._owner_key(owner_name)}:{folder_id}"

    def _password_candidates(self, kind, owner_name, folder_id=None):
        owner_key = self._owner_key(owner_name)
        seen = set()
        if kind == "account":
            exact = self.account_passwords.get(owner_key) or self.config_store.account_password(owner_key)
            if exact:
                seen.add(exact)
                yield exact
        else:
            folder_key = self._folder_password_key(owner_name, folder_id)
            exact = self.folder_passwords.get(folder_key) or self.config_store.folder_password(owner_key, folder_id)
            if exact:
                seen.add(exact)
                yield exact
        for password in self.owner_passwords.get(owner_key, []):
            if password and password not in seen:
                seen.add(password)
                yield password
        owner_password = self.config_store.owner_password(owner_key)
        if owner_password and owner_password not in seen:
            seen.add(owner_password)
            yield owner_password
        if kind == "folder":
            account_password = self.account_passwords.get(owner_key) or self.config_store.account_password(owner_key)
            if account_password and account_password not in seen:
                yield account_password

    def _prompt_password(self, kind, identifier, owner_name, retry=False):
        if not self.password_provider:
            if kind == "account":
                raise ChomikujError(self.i18n("error.password_required_account", owner_name=owner_name))
            raise ChomikujError(self.i18n("error.password_required_folder", folder_key=identifier))
        while True:
            try:
                response = self.password_provider(
                    kind,
                    identifier,
                    owner_name=owner_name,
                    retry=retry,
                    allow_skip=self.allow_password_skip,
                )
            except TypeError:
                response = self.password_provider(kind, identifier)
            if isinstance(response, dict):
                action = str(response.get("action") or "submit").strip().lower()
                password = response.get("password") or response.get("value") or ""
            else:
                action = "submit"
                password = response or ""
            if action == "skip":
                if self.allow_password_skip:
                    raise PasswordSkippedError(kind, identifier)
                action = "cancel"
            if action == "cancel":
                raise ChomikujError(self.i18n("error.password_cancelled", identifier=identifier))
            if password:
                return password
            retry = True

    def _try_account_password(self, owner, password):
        try:
            self.api.account_password_read(owner["id"], password)
        except ApiRequestError as exc:
            if exc.status == 401 and exc.code == 2:
                return False
            raise
        owner_key = self._owner_key(owner["name"])
        self.account_passwords[owner_key] = password
        self.config_store.set_account_password(owner_key, password)
        self._remember_owner_password(owner["name"], password)
        return True

    def _try_folder_password(self, owner, folder_id, folder_key, password):
        try:
            self.api.folders_password(owner["id"], folder_id, password)
        except ApiRequestError as exc:
            if exc.status == 401 and exc.code == 12:
                return False
            raise
        owner_key = self._owner_key(owner["name"])
        self.folder_passwords[self._folder_password_key(owner["name"], folder_id)] = password
        self.config_store.set_folder_password(owner_key, folder_id, password)
        self._remember_owner_password(owner["name"], password)
        return True

    def _unlock_account(self, owner):
        owner_name = owner["name"]
        owner_key = self._owner_key(owner_name)
        cached_exact = self.account_passwords.get(owner_key) or self.config_store.account_password(owner_key)
        for password in self._password_candidates("account", owner_name):
            if self._try_account_password(owner, password):
                return
        if cached_exact:
            self.account_passwords.pop(owner_key, None)
            self.config_store.forget_account_password(owner_key)
        retry = False
        while True:
            password = self._prompt_password("account", owner_name, owner_name, retry=retry)
            if self._try_account_password(owner, password):
                return
            retry = True

    def _unlock_folder(self, owner, folder_id):
        folder_key = f"{owner['name']}:{folder_id}"
        owner_key = self._owner_key(owner["name"])
        password_key = self._folder_password_key(owner["name"], folder_id)
        cached_exact = self.folder_passwords.get(password_key) or self.config_store.folder_password(owner_key, folder_id)
        for password in self._password_candidates("folder", owner["name"], folder_id=folder_id):
            if self._try_folder_password(owner, folder_id, folder_key, password):
                return
        if cached_exact:
            self.folder_passwords.pop(password_key, None)
            self.config_store.forget_folder_password(owner_key, folder_id)
        retry = False
        while True:
            password = self._prompt_password("folder", folder_key, owner["name"], retry=retry)
            if self._try_folder_password(owner, folder_id, folder_key, password):
                return
            retry = True

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
        matches = {}
        while True:
            payload = self.api.account_search(owner_name, page)
            for result in payload.get("Results", []):
                if self.same_name(result.get("AccountName", ""), owner_name):
                    account_id = str(result.get("AccountId") or "")
                    key = account_id or self.clean(result.get("AccountName", "")).casefold()
                    matches.setdefault(key, result)
            if not payload.get("IsNextPageAvailable"):
                break
            page += 1
        if not matches:
            raise ChomikujError(self.i18n("error.account_not_found", owner_name=owner_name))
        unique_matches = list(matches.values())
        if len(unique_matches) > 1:
            raise ChomikujError(self.i18n("error.account_ambiguous", owner_name=owner_name))
        return {"id": str(unique_matches[0]["AccountId"]), "name": unique_matches[0]["AccountName"]}

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
                    self._unlock_account(owner)
                    continue
                if exc.status == 401 and exc.code == 12:
                    self._unlock_folder(owner, folder_id)
                    continue
                raise
            result["Folders"].extend(payload.get("Folders", []))
            result["Files"].extend(payload.get("Files", []))
            result["Owner"] = payload.get("Owner", result["Owner"])
            result["ParentId"] = payload.get("ParentId", result["ParentId"])
            result["ParentName"] = payload.get("ParentName", result["ParentName"])
            if not payload.get("Folders") and not payload.get("Files"):
                break
            if not payload.get("IsNextPageAvailable"):
                break
            page += 1
        self.folder_cache[key] = result
        return result

    def split_url(self, url):
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or parsed.netloc not in ("chomikuj.pl", "www.chomikuj.pl"):
            raise ChomikujError(self.i18n("error.unsupported_url", url=url))
        parts = [self.clean(part) for part in parsed.path.split("/") if part]
        if not parts:
            raise ChomikujError(self.i18n("error.invalid_url", url=url))
        return parts[0], parts[1:]

    def find_named_folder(self, folders, segment):
        matches = [folder for folder in folders if self.same_name(folder.get("Name", ""), segment)]
        if len(matches) > 1:
            raise ChomikujError(self.i18n("error.folder_ambiguous", segment=segment))
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
