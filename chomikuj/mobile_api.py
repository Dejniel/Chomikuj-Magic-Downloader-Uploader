#!/usr/bin/env python3

import base64
import hashlib
import json
import time
from urllib.parse import quote, urlencode

import requests

from .common import BASE_URL, RETRY_ATTEMPTS, RETRY_BACKOFF_SECONDS, SECRET_KEY, TIMEOUT, USER_AGENT, ApiRequestError, ChomikujError


class MobileApi:
    """Klient `mobile.chomikuj.pl/api/v3`.

    Publiczne metody maja jawne parametry zamiast anonimowego `body`,
    zeby bylo od razu widac jakich pol oczekuje endpoint.
    """

    def __init__(self, username, password, debug=False, debug_hook=None):
        self.username = username
        self.password = password
        self.debug = debug
        self.debug_hook = debug_hook
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
            except requests.Timeout as exc:
                if attempt >= attempts:
                    raise ChomikujError(f"Timeout API dla {method} {path} po {attempts} probach: {exc}") from exc
                if self.debug:
                    self._debug(f"DEBUG timeout {method} {path_query}, proba {attempt}/{attempts}, ponawiam")
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
            except requests.RequestException as exc:
                raise ChomikujError(f"Blad polaczenia z API dla {method} {path}: {exc}") from exc
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
            raise ChomikujError(f"Nieprawidlowy JSON z {path}: {exc}") from exc

    def activate_payment(self, purchase_info, signature):
        """POST /api/v3/payments/android/activate.

        Parametry:
        - `purchase_info`: surowy JSON zakupu z Google Play
        - `signature`: podpis zakupu w base64 z Google Play
        """
        receipt = {
            "PurchaseInfo": self._urlsafe_b64(str(purchase_info).encode("utf-8")),
            "Signature": self._urlsafe_b64(base64.b64decode(signature)),
        }
        payload = {"ReceiptData": self._urlsafe_b64(json.dumps(receipt, separators=(",", ":")).encode("utf-8"))}
        return self._json("POST", "/api/v3/payments/android/activate", body=payload)

    def account_info(self):
        """GET /api/v3/account/info. Podstawowe info o zalogowanym koncie."""
        return self._json("GET", "/api/v3/account/info")

    def account_login(self):
        """POST /api/v3/account/login.

        Parametry:
        - korzysta z `username` i `password` przekazanych do konstruktora
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
            raise ChomikujError("Brak ApiKey po logowaniu")
        return payload

    def account_password_read(self, account_id, password):
        """POST /api/v3/account/passwords/read.

        Parametry:
        - `account_id`: ID konta z haslem
        - `password`: haslo do zasobow konta
        """
        return self._json(
            "POST",
            "/api/v3/account/passwords/read",
            body={"AccountId": str(account_id), "Password": password},
        )

    def account_password_recover(self, account_name, email):
        """POST /api/v3/account/password/recover.

        Parametry:
        - `account_name`: nazwa konta
        - `email`: email przypisany do konta
        """
        payload = {"AccountName": account_name, "Email": email}
        return self._json("POST", "/api/v3/account/password/recover", body=payload, use_api_key=False)

    def account_register(self, account_name, password, email):
        """POST /api/v3/account/register.

        Parametry:
        - `account_name`: nazwa nowego konta
        - `password`: haslo nowego konta
        - `email`: email nowego konta
        """
        payload = {"AccountName": account_name, "Password": password, "Email": email}
        return self._json("POST", "/api/v3/account/register", body=payload, use_api_key=False)

    def account_search(self, account_name, page=1):
        """GET /api/v3/account/search.

        Parametry:
        - `account_name`: nazwa konta lub fragment nazwy
        - `page`: numer strony wynikow
        """
        return self._json(
            "GET",
            "/api/v3/account/search",
            query=[("Query", account_name), ("PageNumber", str(page))],
        )

    def account_transfer(self):
        """GET /api/v3/account/transfer. Saldo i transfer konta."""
        return self._json("GET", "/api/v3/account/transfer")

    def account_validate_email(self, email):
        """GET /api/v3/account/register/validate/email.

        Parametry:
        - `email`: email do sprawdzenia
        """
        return self._json("GET", "/api/v3/account/register/validate/email", query=[("email", email)], use_api_key=False)

    def account_validate_name(self, account_name):
        """GET /api/v3/account/register/validate/accountName.

        Parametry:
        - `account_name`: nazwa konta do sprawdzenia
        """
        return self._json(
            "GET",
            "/api/v3/account/register/validate/accountName",
            query=[("accountName", account_name)],
            use_api_key=False,
        )

    def files_change_name(self, file_id, file_name):
        """POST /api/v3/files/changeName.

        Parametry:
        - `file_id`: ID pliku
        - `file_name`: nowa nazwa pliku bez zmian w rozszerzeniu
        """
        payload = {"FileId": int(file_id), "FileName": file_name}
        return self._json("POST", "/api/v3/files/changeName", body=payload)

    def files_copies_get(self, query=None):
        """GET /api/v3/files/copies.

        Parametry:
        - `query`: opcjonalna lista par `(klucz, wartosc)` dla paginacji/filtrow
        """
        return self._json("GET", "/api/v3/files/copies", query=query)

    def files_copies_post(self, owner_account_id, file_id):
        """POST /api/v3/files/copies.

        Parametry:
        - `owner_account_id`: ID wlasciciela oryginalnego pliku
        - `file_id`: ID pliku do zachomikowania
        """
        payload = {"OwnerAccountId": str(owner_account_id), "FileId": int(file_id)}
        return self._json("POST", "/api/v3/files/copies", body=payload)

    def files_delete(self, file_ids=None, folder_ids=None):
        """POST /api/v3/files/delete.

        Parametry:
        - `file_ids`: lista ID plikow do usuniecia
        - `folder_ids`: lista ID folderow do usuniecia
        """
        payload = {
            "Files": [int(file_id) for file_id in (file_ids or [])],
            "Folders": [int(folder_id) for folder_id in (folder_ids or [])],
        }
        return self._json("POST", "/api/v3/files/delete", body=payload)

    def files_download(self, file_id):
        """GET /api/v3/files/download.

        Parametry:
        - `file_id`: ID pliku do pobrania
        """
        return self._json("GET", "/api/v3/files/download", query=[("fileId", str(file_id))])

    def files_move(self, source_folder_id, target_folder_id, file_ids=None, folder_ids=None):
        """POST /api/v3/files/move.

        Parametry:
        - `source_folder_id`: folder zrodlowy
        - `target_folder_id`: folder docelowy
        - `file_ids`: lista ID plikow do przeniesienia
        - `folder_ids`: lista ID folderow do przeniesienia
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

        Parametry:
        - `query`: lista par `(klucz, wartosc)` z filtrami wyszukiwarki
        """
        return self._json("GET", "/api/v3/files/search", query=query)

    def files_upload_partial(self, name, size, folder_id, hash_value):
        """POST /api/v3/files/upload/partialUpload.

        Parametry:
        - `name`: nazwa pliku
        - `size`: rozmiar pliku w bajtach
        - `folder_id`: folder docelowy
        - `hash_value`: CRC/hash pliku
        """
        payload = {"Name": name, "Size": int(size), "FolderId": str(folder_id), "Hash": str(hash_value)}
        return self._json("POST", "/api/v3/files/upload/partialUpload", body=payload)

    def folders_change_name(self, folder_id, folder_name):
        """POST /api/v3/folders/changeName.

        Parametry:
        - `folder_id`: ID folderu
        - `folder_name`: nowa nazwa folderu
        """
        payload = {"FolderId": str(folder_id), "FolderName": folder_name}
        return self._json("POST", "/api/v3/folders/changeName", body=payload)

    def folders_change_password(self, folder_id, password):
        """POST /api/v3/folders/changePassword.

        Parametry:
        - `folder_id`: ID folderu
        - `password`: nowe haslo folderu
        """
        payload = {"FolderId": str(folder_id), "Password": password}
        return self._json("POST", "/api/v3/folders/changePassword", body=payload)

    def folders_create(self, folder_name, parent_id):
        """POST /api/v3/folders/create.

        Parametry:
        - `folder_name`: nazwa nowego folderu
        - `parent_id`: ID folderu rodzica
        """
        payload = {"FolderName": folder_name, "ParentId": str(parent_id)}
        return self._json("POST", "/api/v3/folders/create", body=payload)

    def folders_download_items(self, account_id, folder_id):
        """GET /api/v3/folders/download/items.

        Parametry:
        - `account_id`: ID wlasciciela folderu
        - `folder_id`: ID folderu
        """
        return self._json(
            "GET",
            "/api/v3/folders/download/items",
            query=[("accountId", str(account_id)), ("folderId", str(folder_id))],
        )

    def folders_get(self, account_id, folder_id, page=1):
        """GET /api/v3/folders.

        Parametry:
        - `account_id`: ID wlasciciela folderu
        - `folder_id`: ID folderu lub `0` dla root
        - `page`: numer strony listingu
        """
        return self._json(
            "GET",
            "/api/v3/folders",
            query=[("AccountId", str(account_id)), ("Parent", str(folder_id)), ("page", str(page))],
        )

    def folders_password(self, account_id, folder_id, password):
        """POST /api/v3/folders/password.

        Parametry:
        - `account_id`: ID wlasciciela folderu
        - `folder_id`: ID folderu
        - `password`: haslo do otwarcia folderu
        """
        return self._json(
            "POST",
            "/api/v3/folders/password",
            body={"AccountId": str(account_id), "FolderId": str(folder_id), "Password": password},
        )

    def friends_add(self, account_id):
        """POST /api/v3/friends.

        Parametry:
        - `account_id`: ID konta do dodania do znajomych
        """
        return self._json("POST", "/api/v3/friends", body={"id": str(account_id)})

    def friends_delete(self, friend_id):
        """DELETE /api/v3/friends/{id}.

        Parametry:
        - `friend_id`: ID znajomego
        """
        return self._json("DELETE", f"/api/v3/friends/{self._quote(friend_id)}")

    def friends_get(self):
        """GET /api/v3/friends. Lista znajomych."""
        return self._json("GET", "/api/v3/friends")

    def instance_modules(self):
        """GET /api/v3/instance/modules. Flagi modulow aplikacji."""
        return self._json("GET", "/api/v3/instance/modules")

    def messages_block_sender(self, message_id):
        """POST /api/v3/messages/{id}/blockSender.

        Parametry:
        - `message_id`: ID wiadomosci od nadawcy do zablokowania
        """
        return self._json("POST", f"/api/v3/messages/{self._quote(message_id)}/blockSender")

    def messages_delete(self, message_id):
        """DELETE /api/v3/messages/{id}.

        Parametry:
        - `message_id`: ID wiadomosci
        """
        return self._json("DELETE", f"/api/v3/messages/{self._quote(message_id)}")

    def messages_get(self, message_id):
        """GET /api/v3/messages/{id}.

        Parametry:
        - `message_id`: ID wiadomosci
        """
        return self._json("GET", f"/api/v3/messages/{self._quote(message_id)}")

    def messages_inbox(self, query=None):
        """GET /api/v3/messages/inbox.

        Parametry:
        - `query`: opcjonalna lista par `(klucz, wartosc)` dla paginacji
        """
        return self._json("GET", "/api/v3/messages/inbox", query=query)

    def messages_mark_all_read(self):
        """POST /api/v3/messages/markAllAsRead. Oznaczenie wszystkich jako przeczytane."""
        return self._json("POST", "/api/v3/messages/markAllAsRead")

    def messages_outbox(self, query=None):
        """GET /api/v3/messages/outbox.

        Parametry:
        - `query`: opcjonalna lista par `(klucz, wartosc)` dla paginacji
        """
        return self._json("GET", "/api/v3/messages/outbox", query=query)

    def messages_reply(self, message_id, subject, body_text, email=None):
        """POST /api/v3/messages/{id}/reply.

        Parametry:
        - `message_id`: ID wiadomosci
        - `subject`: temat odpowiedzi
        - `body_text`: tresc odpowiedzi
        - `email`: opcjonalny email kontaktowy
        """
        payload = {"Subject": subject, "Body": body_text}
        if email:
            payload["Email"] = email
        return self._json("POST", f"/api/v3/messages/{self._quote(message_id)}/reply", body=payload)

    def messages_report_fraud(self, message_id):
        """POST /api/v3/messages/{id}/markAsFraud.

        Parametry:
        - `message_id`: ID wiadomosci
        """
        return self._json("POST", f"/api/v3/messages/{self._quote(message_id)}/markAsFraud")

    def messages_report_spam(self, message_id):
        """POST /api/v3/messages/{id}/markAsSpam.

        Parametry:
        - `message_id`: ID wiadomosci
        """
        return self._json("POST", f"/api/v3/messages/{self._quote(message_id)}/markAsSpam")

    def messages_send(self, account_to, subject, body_text):
        """POST /api/v3/messages/send.

        Parametry:
        - `account_to`: nazwa lub ID odbiorcy
        - `subject`: temat
        - `body_text`: tresc wiadomosci
        """
        payload = {"AccountTo": str(account_to), "Subject": subject, "Body": body_text}
        return self._json("POST", "/api/v3/messages/send", body=payload)

    def synchronization_state(self):
        """GET /api/v3/synchronization/state. Stan backupu synchronizacji."""
        return self._json("GET", "/api/v3/synchronization/state")

    def synchronization_upload(self, name, extension, size, hash_value, media_type, last_modified):
        """POST /api/v3/synchronization/upload.

        Parametry:
        - `name`: nazwa pliku
        - `extension`: rozszerzenie bez kropki
        - `size`: rozmiar pliku w bajtach
        - `hash_value`: CRC/hash pliku
        - `media_type`: typ mediow jako numer z aplikacji
        - `last_modified`: timestamp modyfikacji pliku
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
