#!/usr/bin/env python3

import os
import sys
import threading
import time
from getpass import getpass

from .i18n import ensure_i18n


class UiTerminal:
    def __init__(self, download_slots=0, live=True, i18n=None):
        self.download_slots = max(0, int(download_slots))
        self.live = bool(live and sys.stdout.isatty())
        self.i18n = ensure_i18n(i18n, language="en")
        self.lock = threading.Lock()
        self.last_render = 0.0
        self.download_total = 0
        self.download_done = 0
        self.download_failed_count = 0
        self.download_skipped_count = 0
        self.download_states = {}
        self.download_slots_map = {}
        self.upload_states = {}
        self.plain = not self.live

    def login(self):
        return input(self.i18n("terminal.prompt.login")).strip()

    def login_password(self):
        return getpass(self.i18n("terminal.prompt.password"))

    def password(self, kind, identifier, owner_name=None, retry=False, allow_skip=False):
        if kind == "account":
            prompt = self.i18n("terminal.prompt.account_password", identifier=identifier)
        else:
            prompt = self.i18n("terminal.prompt.folder_password", identifier=identifier)
        if retry:
            with self.lock:
                print(self.i18n("terminal.password.retry", identifier=identifier), file=sys.stderr)
        action_prompt = self.i18n(
            "terminal.prompt.password_action_skip" if allow_skip else "terminal.prompt.password_action"
        )
        while True:
            choice = input(action_prompt).strip().lower()
            if not choice:
                return {"action": "submit", "password": getpass(prompt)}
            if choice in ("c", "cancel", "a", "anuluj"):
                return {"action": "cancel"}
            if allow_skip and choice in ("s", "skip", "p", "pomij", "pomin"):
                return {"action": "skip"}

    def error(self, message):
        with self.lock:
            print(message, file=sys.stderr)

    def debug(self, message):
        with self.lock:
            print(message, file=sys.stderr)

    def download_queued(self, path):
        with self.lock:
            self.download_total += 1
            self.download_states[path] = {
                "status": "queued",
                "downloaded": 0,
                "total": None,
                "slot": None,
            }
            self._render()

    def _allocate_slot(self, path):
        for slot in range(1, self.download_slots + 1):
            if slot not in self.download_slots_map:
                self.download_slots_map[slot] = path
                return slot
        return None

    def _release_slot(self, path):
        for slot, current in list(self.download_slots_map.items()):
            if current == path:
                del self.download_slots_map[slot]
                return slot
        return None

    def download_started(self, path, downloaded, total):
        with self.lock:
            state = self.download_states.setdefault(path, {})
            state["status"] = "running"
            state["downloaded"] = downloaded
            state["total"] = total
            state["slot"] = state.get("slot") or self._allocate_slot(path)
            self._render()

    def download_progress(self, path, downloaded, total):
        with self.lock:
            state = self.download_states.setdefault(path, {})
            state["status"] = "running"
            state["downloaded"] = downloaded
            state["total"] = total
            state["slot"] = state.get("slot") or self._allocate_slot(path)
            self._render()

    def download_finished(self, path, downloaded, total):
        with self.lock:
            self.download_done += 1
            state = self.download_states.setdefault(path, {})
            state["status"] = "done"
            state["downloaded"] = downloaded
            state["total"] = total
            self._release_slot(path)
            if self.plain:
                print(self.i18n("terminal.tag.done"), path)
            self._render(force=True)

    def download_skipped(self, path):
        with self.lock:
            self.download_skipped_count += 1
            state = self.download_states.setdefault(path, {})
            state["status"] = "skipped"
            self._release_slot(path)
            if self.plain:
                print(self.i18n("terminal.tag.skipped"), path)
            self._render(force=True)

    def download_failed(self, path, error):
        with self.lock:
            self.download_failed_count += 1
            state = self.download_states.setdefault(path, {})
            state["status"] = "error"
            state["error"] = str(error)
            self._release_slot(path)
            if self.plain:
                print(self.i18n("terminal.tag.failed"), path, error)
            self._render(force=True)

    def upload_started(self, path, target, total):
        with self.lock:
            self.upload_states[path] = {
                "status": "running",
                "target": target,
                "uploaded": 0,
                "total": total,
            }
            self._render()

    def upload_progress(self, path, uploaded, total, target):
        with self.lock:
            self.upload_states[path] = {
                "status": "running",
                "target": target,
                "uploaded": uploaded,
                "total": total,
            }
            self._render()

    def upload_finished(self, path, target, total):
        with self.lock:
            self.upload_states[path] = {
                "status": "done",
                "target": target,
                "uploaded": total,
                "total": total,
            }
            if self.plain:
                print(self.i18n("terminal.tag.done"), path)
            self._render(force=True)

    def upload_skipped(self, path, target):
        with self.lock:
            self.upload_states[path] = {
                "status": "skipped",
                "target": target,
            }
            if self.plain:
                print(self.i18n("terminal.tag.skipped"), path)
            self._render(force=True)

    def upload_failed(self, path, error, target):
        with self.lock:
            self.upload_states[path] = {
                "status": "error",
                "target": target,
                "error": str(error),
            }
            if self.plain:
                print(self.i18n("terminal.tag.failed"), path, error)
            self._render(force=True)

    def _format_bytes(self, value):
        if value is None:
            return "?"
        size = float(value)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.1f}{unit}" if unit != "B" else f"{int(size)}B"
            size /= 1024
        return f"{int(value)}B"

    def _bar(self, current, total, width=24):
        if not total:
            return "[" + "." * width + "]"
        ratio = max(0.0, min(1.0, current / total))
        filled = int(width * ratio)
        return "[" + "#" * filled + "." * (width - filled) + "]"

    def _basename(self, path):
        return os.path.basename(path.rstrip("/")) or path

    def _download_lines(self):
        active = []
        for slot in range(1, self.download_slots + 1):
            path = self.download_slots_map.get(slot)
            if not path:
                active.append(self.i18n("terminal.slot.idle", slot=slot))
                continue
            state = self.download_states.get(path, {})
            downloaded = state.get("downloaded") or 0
            total = state.get("total")
            percent = f"{int((downloaded / total) * 100):3d}%" if total else " ??%"
            bar = self._bar(downloaded, total)
            stats = f"{self._format_bytes(downloaded)}/{self._format_bytes(total)}"
            active.append(f"[D{slot}] {percent} {bar} {stats} {self._basename(path)}")
        return active

    def _upload_lines(self):
        lines = []
        for index, (path, state) in enumerate(sorted(self.upload_states.items()), start=1):
            status = state.get("status")
            if status not in ("running", "error", "skipped"):
                continue
            uploaded = state.get("uploaded") or 0
            total = state.get("total")
            percent = f"{int((uploaded / total) * 100):3d}%" if total else " ??%"
            bar = self._bar(uploaded, total)
            stats = f"{self._format_bytes(uploaded)}/{self._format_bytes(total)}"
            suffix = f" -> {state.get('target')}"
            if status == "error":
                lines.append(f"[U{index}] {self.i18n('terminal.tag.failed')} {self._basename(path)}{suffix}: {state.get('error')}")
            elif status == "skipped":
                lines.append(f"[U{index}] {self.i18n('terminal.tag.skipped')} {self._basename(path)}{suffix}")
            else:
                lines.append(f"[U{index}] {percent} {bar} {stats} {self._basename(path)}{suffix}")
        return lines

    def _render(self, force=False):
        if self.plain:
            return
        now = time.monotonic()
        if not force and now - self.last_render < 0.08:
            return
        lines = [
            self.i18n(
                "terminal.summary.downloads",
                total=self.download_total,
                done=self.download_done,
                skipped=self.download_skipped_count,
                failed=self.download_failed_count,
            ),
        ]
        lines.extend(self._download_lines())
        upload_lines = self._upload_lines()
        if upload_lines:
            lines.append("")
            lines.append(self.i18n("terminal.section.upload"))
            lines.extend(upload_lines)
        sys.stdout.write("\033[H\033[2J")
        sys.stdout.write("\n".join(lines) + "\n")
        sys.stdout.flush()
        self.last_render = now

    def finish(self):
        with self.lock:
            self._render(force=True)
