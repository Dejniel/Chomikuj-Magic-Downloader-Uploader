#!/usr/bin/env python3

import hashlib
import time
from xml.etree import ElementTree as ET

import requests

from .common import RETRY_ATTEMPTS, RETRY_BACKOFF_SECONDS, TIMEOUT, ApiRequestError, ChomikujError, is_timeout_error
from .i18n import ensure_i18n

SOAP_URL = "https://box.chomikuj.pl/services/ChomikBoxService.svc"
SOAP_NS = "http://schemas.xmlsoap.org/soap/envelope/"
CHOMIK_NS = "http://chomikuj.pl/"
SOAP_CLIENT_NAME = "chomikbox"
SOAP_CLIENT_VERSION = "2.0.8.2"


class ApiSoap:
    def __init__(self, username, password, debug=False, debug_hook=None, i18n=None):
        self.username = username
        self.password = password
        self.debug = debug
        self.debug_hook = debug_hook
        self.i18n = ensure_i18n(i18n, language="en")
        self.session = requests.Session()
        self.token = ""
        self.account_id = ""
        self.account_name = ""

    def _debug(self, message):
        if self.debug and self.debug_hook:
            self.debug_hook(message)

    def _element(self, name, text=None):
        element = ET.Element(name)
        if text is not None:
            element.text = str(text)
        return element

    def _child(self, node, name):
        for child in list(node):
            if child.tag.rsplit("}", 1)[-1] == name:
                return child
        return None

    def _child_text(self, node, name):
        child = self._child(node, name)
        return child.text if child is not None else None

    def _find_text(self, node, name):
        for element in node.iter():
            if element.tag.rsplit("}", 1)[-1] == name:
                return element.text
        return None

    def _agreement_entries(self, node):
        entries = []
        agreement_info = self._child(node, "agreementInfo")
        if agreement_info is None:
            return entries
        for agreement in list(agreement_info):
            if agreement.tag.rsplit("}", 1)[-1] != "AgreementInfo":
                continue
            name = self._child_text(agreement, "name")
            cost = self._child_text(agreement, "cost")
            if not name:
                continue
            entries.append({"name": name, "cost": int(cost or 0)})
        return entries

    def _request(self, action, payload):
        envelope = ET.Element(
            f"{{{SOAP_NS}}}Envelope",
            {f"{{{SOAP_NS}}}encodingStyle": "http://schemas.xmlsoap.org/soap/encoding/"},
        )
        body = ET.SubElement(envelope, f"{{{SOAP_NS}}}Body")
        body.append(payload)
        xml = ET.tostring(envelope, encoding="utf-8", xml_declaration=True)
        headers = {
            "SOAPAction": f"http://chomikuj.pl/IChomikBoxService/{action}",
            "Content-Type": "text/xml;charset=utf-8",
            "Accept-Encoding": "identity",
            "Accept-Language": "pl-PL,en,*",
            "User-Agent": "Mozilla/5.0",
            "Host": "box.chomikuj.pl",
        }
        for attempt in range(1, RETRY_ATTEMPTS + 1):
            try:
                response = self.session.post(SOAP_URL, data=xml, headers=headers, timeout=TIMEOUT)
                break
            except requests.RequestException as exc:
                if is_timeout_error(exc):
                    if attempt >= RETRY_ATTEMPTS:
                        raise ChomikujError(
                            self.i18n("error.soap_timeout", action=action, attempts=RETRY_ATTEMPTS, error=exc)
                        ) from exc
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                    continue
                raise ChomikujError(self.i18n("error.soap_connection", action=action, error=exc)) from exc
        if self.debug:
            self._debug(f"DEBUG SOAP {action} HTTP {response.status_code}")
            self._debug(response.text[:4000])
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:
            raise ApiRequestError(response.status_code, None, response.text or f"HTTP {response.status_code}", response.text) from exc
        try:
            return ET.fromstring(response.content)
        except ET.ParseError as exc:
            raise ChomikujError(self.i18n("error.soap_invalid_xml", action=action, error=exc)) from exc

    def auth(self):
        payload = ET.Element("Auth", {"xmlns": CHOMIK_NS})
        payload.append(self._element("name", self.username))
        payload.append(self._element("passHash", hashlib.md5(self.password.encode("utf-8")).hexdigest()))
        payload.append(self._element("ver", "4"))
        client = ET.SubElement(payload, "client")
        client.append(self._element("name", SOAP_CLIENT_NAME))
        client.append(self._element("version", SOAP_CLIENT_VERSION))
        root = self._request("Auth", payload)
        status = self._find_text(root, "status") or ""
        if status.upper() != "OK":
            raise ChomikujError(self.i18n("error.soap_auth_failed", status=status or "unknown"))
        self.token = self._find_text(root, "token") or ""
        self.account_id = self._find_text(root, "hamsterId") or ""
        self.account_name = self._find_text(root, "name") or self.username
        if not self.token:
            raise ChomikujError(self.i18n("error.soap_missing_token"))
        return {"token": self.token, "account_id": self.account_id, "account_name": self.account_name}

    def download(self, req_id, agreement_name=None, cost=None):
        payload = ET.Element("Download", {"xmlns": CHOMIK_NS})
        payload.append(self._element("token", self.token))
        sequence = ET.SubElement(payload, "sequence")
        sequence.append(self._element("stamp", "0"))
        sequence.append(self._element("part", "0"))
        sequence.append(self._element("count", "1"))
        payload.append(self._element("disposition", "download"))
        list_node = ET.SubElement(payload, "list")
        entry = ET.SubElement(list_node, "DownloadReqEntry")
        entry.append(self._element("id", req_id))
        if agreement_name is not None:
            agreement_node = ET.SubElement(entry, "agreementInfo")
            agreement_info = ET.SubElement(agreement_node, "AgreementInfo")
            agreement_info.append(self._element("name", agreement_name))
            if cost is not None:
                agreement_info.append(self._element("cost", cost))
        root = self._request("Download", payload)
        status = self._find_text(root, "status") or ""
        if status.upper() != "OK":
            raise ChomikujError(self.i18n("error.soap_download_failed", req_id=req_id, status=status or "unknown"))
        folder = None
        for element in root.iter():
            if element.tag.rsplit("}", 1)[-1] == "DownloadFolder":
                folder = self._parse_download_folder(element)
                break
        if folder is None:
            list_node = None
            for element in root.iter():
                if element.tag.rsplit("}", 1)[-1] == "list":
                    list_node = element
                    break
            if list_node is not None and not list(list_node):
                return {
                    "id": "0",
                    "owner_id": "",
                    "owner_name": "",
                    "name": "",
                    "global_id": str(req_id),
                    "files": [],
                }
            raise ChomikujError(self.i18n("error.soap_missing_download_folder", req_id=req_id))
        return folder

    def _parse_download_folder(self, node):
        files = []
        files_node = self._child(node, "files")
        if files_node is not None:
            for entry in files_node:
                if entry.tag.rsplit("}", 1)[-1] != "FileEntry":
                    continue
                files.append(
                    {
                        "id": str(self._child_text(entry, "id") or ""),
                        "real_id": str(self._child_text(entry, "realId") or ""),
                        "name": self._child_text(entry, "name") or "",
                        "size": int(self._child_text(entry, "size") or 0),
                        "url": self._child_text(entry, "url"),
                        "agreements": self._agreement_entries(entry),
                    }
                )
        return {
            "id": str(self._child_text(node, "id") or "0"),
            "owner_id": str(self._child_text(node, "hamsterId") or ""),
            "owner_name": self._child_text(node, "hamsterName") or "",
            "name": self._child_text(node, "name") or "",
            "global_id": self._child_text(node, "globalId") or "",
            "files": files,
        }
