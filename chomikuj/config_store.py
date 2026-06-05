#!/usr/bin/env python3

import configparser
import os
import threading
from urllib.parse import quote

try:
    from platformdirs import user_config_dir
except ModuleNotFoundError:
    def user_config_dir(appname, appauthor=None):
        if os.name == "nt":
            base_dir = os.environ.get("APPDATA") or os.path.expanduser("~")
            return os.path.join(base_dir, appname)
        if xdg_config_home := os.environ.get("XDG_CONFIG_HOME"):
            return os.path.join(xdg_config_home, appname)
        return os.path.join(os.path.expanduser("~"), ".config", appname)


class ConfigStore:
    APP_NAME = "Chomikuj Magic"
    FILE_NAME = "credentials.ini"

    APP_SECTION = "app"
    LOGIN_SECTION = "login"
    OWNER_PASSWORDS_SECTION = "owner_passwords"
    ACCOUNT_PASSWORDS_SECTION = "account_passwords"
    FOLDER_PASSWORDS_SECTION = "folder_passwords"

    def __init__(self, path=None, enabled=True):
        self.enabled = bool(enabled)
        self.path = path or self.default_path()
        self.lock = threading.Lock()

    @classmethod
    def disabled(cls):
        return cls(path=None, enabled=False)

    @classmethod
    def default_path(cls):
        return os.path.join(user_config_dir(cls.APP_NAME, appauthor=False), cls.FILE_NAME)

    def _key(self, value):
        return quote(str(value or "").strip().casefold(), safe="")

    def _folder_key(self, owner_key, folder_id):
        return f"{self._key(owner_key)}|{self._key(folder_id)}"

    def _read(self):
        parser = configparser.RawConfigParser()
        if self.enabled and os.path.exists(self.path):
            parser.read(self.path, encoding="utf-8")
        return parser

    def _write(self, parser):
        if not self.enabled:
            return
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as handle:
            parser.write(handle)
        try:
            os.chmod(self.path, 0o600)
        except OSError:
            pass

    def _get(self, section, option, default=""):
        if not self.enabled:
            return default
        with self.lock:
            parser = self._read()
            if not parser.has_section(section):
                return default
            return parser.get(section, option, fallback=default)

    def _set(self, section, option, value):
        if not self.enabled:
            return
        with self.lock:
            parser = self._read()
            if not parser.has_section(section):
                parser.add_section(section)
            parser.set(section, option, str(value or ""))
            self._write(parser)

    def _remove(self, section, option):
        if not self.enabled:
            return
        with self.lock:
            parser = self._read()
            if parser.has_section(section):
                parser.remove_option(section, option)
                self._write(parser)

    def language(self):
        return self._get(self.APP_SECTION, "language")

    def set_language(self, language):
        if language:
            self._set(self.APP_SECTION, "language", language)

    def login(self):
        return {
            "username": self._get(self.LOGIN_SECTION, "username"),
            "password": self._get(self.LOGIN_SECTION, "password"),
        }

    def set_login(self, username, password=None):
        self._set(self.LOGIN_SECTION, "username", username)
        if password is not None:
            self._set(self.LOGIN_SECTION, "password", password)

    def clear_login_password(self):
        self._remove(self.LOGIN_SECTION, "password")

    def owner_password(self, owner_key):
        return self._get(self.OWNER_PASSWORDS_SECTION, self._key(owner_key))

    def set_owner_password(self, owner_key, password):
        self._set(self.OWNER_PASSWORDS_SECTION, self._key(owner_key), password)

    def account_password(self, owner_key):
        return self._get(self.ACCOUNT_PASSWORDS_SECTION, self._key(owner_key))

    def set_account_password(self, owner_key, password):
        self._set(self.ACCOUNT_PASSWORDS_SECTION, self._key(owner_key), password)

    def forget_account_password(self, owner_key):
        self._remove(self.ACCOUNT_PASSWORDS_SECTION, self._key(owner_key))

    def folder_password(self, owner_key, folder_id):
        return self._get(self.FOLDER_PASSWORDS_SECTION, self._folder_key(owner_key, folder_id))

    def set_folder_password(self, owner_key, folder_id, password):
        self._set(self.FOLDER_PASSWORDS_SECTION, self._folder_key(owner_key, folder_id), password)

    def forget_folder_password(self, owner_key, folder_id):
        self._remove(self.FOLDER_PASSWORDS_SECTION, self._folder_key(owner_key, folder_id))
