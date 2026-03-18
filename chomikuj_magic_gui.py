#!/usr/bin/env python3
# TODO: DO NOT READ. This code is waiting to be rewritten :P
# One day I'll refactor the whole GUI properly;
# for now, the terrible single-file monolith stays.

import os
import queue
import sys
import threading

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ModuleNotFoundError as exc:
    if exc.name != "tkinter":
        raise
    tk = None
    filedialog = None
    messagebox = None
    ttk = None

from chomikuj import DownloadManager, UploadManager
from chomikuj.common_env import env_language, load_default_env, resolve_default_env_path, save_env_values
from chomikuj.common_runtime import ChomikujError
from chomikuj.i18n import Translator


if tk is not None:
    class ChomikujGui(tk.Tk):
        def __init__(self, script_path):
            super().__init__()
            env = load_default_env(script_path)
            self.env_path = resolve_default_env_path(script_path)
            self.i18n = Translator(env_language(env))

            self.queue = queue.Queue()
            self.busy = False
            self.row_ids = {}
            self.row_data = {}
            self.env_save_job = None
            self.max_worker_threads = max(1, (os.cpu_count() or 1) * 2)
            self.status_state = ("key", "gui.status.idle", {})

            self.username_var = tk.StringVar(value=env.get("USERNAME", ""))
            self.password_var = tk.StringVar(value=env.get("PASSWORD", ""))
            self.download_output_var = tk.StringVar(value=os.getcwd())
            self.download_threads_var = tk.IntVar(value=min(5, self.max_worker_threads))
            self.download_threads_label_var = tk.StringVar()
            self.upload_threads_var = tk.IntVar(value=min(2, self.max_worker_threads))
            self.upload_threads_label_var = tk.StringVar()
            self.download_recursive_var = tk.BooleanVar(value=False)
            self.download_flatten_var = tk.BooleanVar(value=False)
            self.download_keep_original_names_var = tk.BooleanVar(value=False)
            self.upload_folder_var = tk.StringVar(value="")
            self.status_var = tk.StringVar()

            self.title(self.i18n("app.title"))
            self.geometry("1040x858")
            self.minsize(920, 748)

            self._build_ui()
            self._refresh_download_threads_label()
            self._refresh_upload_threads_label()
            self._apply_texts()
            self._refresh_status()

            self.username_var.trace_add("write", self._schedule_env_save)
            self.password_var.trace_add("write", self._schedule_env_save)
            self.download_threads_var.trace_add("write", self._refresh_download_threads_label)
            self.upload_threads_var.trace_add("write", self._refresh_upload_threads_label)
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.after(100, self._process_queue)

        def _build_ui(self):
            padding = {"padx": 10, "pady": 6}
            style = ttk.Style(self)
            style.configure("Activity.Treeview", rowheight=26)

            self.header_frame = ttk.Frame(self)
            self.header_frame.pack(fill="x", padx=10, pady=10)
            self.header_frame.columnconfigure(1, weight=1)
            self.header_frame.columnconfigure(3, weight=1)

            self.username_label = ttk.Label(self.header_frame)
            self.username_label.grid(row=0, column=0, sticky="w", **padding)
            self.username_entry = ttk.Entry(self.header_frame, textvariable=self.username_var)
            self.username_entry.grid(row=0, column=1, sticky="ew", **padding)

            self.password_label = ttk.Label(self.header_frame)
            self.password_label.grid(row=0, column=2, sticky="w", **padding)
            self.password_entry = ttk.Entry(self.header_frame, textvariable=self.password_var, show="*")
            self.password_entry.grid(row=0, column=3, sticky="ew", **padding)

            self.language_button = ttk.Button(self.header_frame, text="PL/EN", command=self._toggle_language)
            self.language_button.grid(row=0, column=4, sticky="e", padx=(12, 10), pady=6)

            self.notebook = ttk.Notebook(self)
            self.notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

            self.download_tab = ttk.Frame(self.notebook)
            self.upload_tab = ttk.Frame(self.notebook)
            self.notebook.add(self.download_tab, text="")
            self.notebook.add(self.upload_tab, text="")

            self._build_download_tab(self.download_tab)
            self._build_upload_tab(self.upload_tab)

            self.activity_frame = ttk.LabelFrame(self)
            self.activity_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
            self.activity_frame.columnconfigure(0, weight=1)
            self.activity_frame.rowconfigure(0, weight=1)
            columns = ("kind", "state", "progress", "target")
            self.activity = ttk.Treeview(self.activity_frame, columns=columns, show="headings", height=16, style="Activity.Treeview")
            self.activity.heading("kind", text="")
            self.activity.heading("state", text="")
            self.activity.heading("progress", text="")
            self.activity.heading("target", text="")
            self.activity.column("kind", width=90, anchor="w")
            self.activity.column("state", width=120, anchor="w")
            self.activity.column("progress", width=180, anchor="w")
            self.activity.column("target", width=700, anchor="w")
            self.activity.grid(row=0, column=0, sticky="nsew")
            activity_scroll = ttk.Scrollbar(self.activity_frame, orient="vertical", command=self.activity.yview)
            activity_scroll.grid(row=0, column=1, sticky="ns")
            self.activity.configure(yscrollcommand=activity_scroll.set)

            self.status_frame = ttk.Frame(self)
            self.status_frame.pack(fill="x", padx=10, pady=(0, 10))
            self.status_label = ttk.Label(self.status_frame)
            self.status_label.pack(side="left")
            self.status_value = ttk.Label(self.status_frame, textvariable=self.status_var)
            self.status_value.pack(side="left", padx=6)

        def _build_download_tab(self, parent):
            padding = {"padx": 10, "pady": 6}
            parent.columnconfigure(0, weight=1)
            parent.rowconfigure(1, weight=1)

            config = ttk.Frame(parent)
            config.grid(row=0, column=0, sticky="ew")
            config.columnconfigure(1, weight=1)

            self.output_label = ttk.Label(config)
            self.output_label.grid(row=0, column=0, sticky="w", **padding)
            self.output_entry = ttk.Entry(config, textvariable=self.download_output_var)
            self.output_entry.grid(row=0, column=1, sticky="ew", **padding)
            self.output_button = ttk.Button(config, command=self._browse_output)
            self.output_button.grid(row=0, column=2, **padding)

            self.download_workers_label = ttk.Label(config)
            self.download_workers_label.grid(row=1, column=0, sticky="w", **padding)
            self.threads_scale = tk.Scale(
                config,
                from_=1,
                to=self.max_worker_threads,
                orient="horizontal",
                variable=self.download_threads_var,
                resolution=1,
                showvalue=False,
                highlightthickness=0,
            )
            self.threads_scale.grid(row=1, column=1, sticky="ew", **padding)
            self.download_threads_label = ttk.Label(config, textvariable=self.download_threads_label_var, width=10)
            self.download_threads_label.grid(row=1, column=2, sticky="w", **padding)

            self.download_flags = ttk.Frame(config)
            self.download_flags.grid(row=2, column=1, columnspan=2, sticky="w", **padding)

            self.recursive_check = ttk.Checkbutton(self.download_flags, variable=self.download_recursive_var)
            self.recursive_check.pack(side="left")

            self.flatten_check = ttk.Checkbutton(self.download_flags, variable=self.download_flatten_var)
            self.flatten_check.pack(side="left", padx=(12, 0))

            self.keep_original_names_check = ttk.Checkbutton(self.download_flags, variable=self.download_keep_original_names_var)
            self.keep_original_names_check.pack(side="left", padx=(12, 0))

            self.urls_frame = ttk.LabelFrame(parent)
            self.urls_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
            self.urls_frame.columnconfigure(0, weight=1)
            self.urls_frame.rowconfigure(0, weight=1)
            self.download_text = tk.Text(self.urls_frame, height=12, wrap="word")
            self.download_text.grid(row=0, column=0, sticky="nsew")
            urls_scroll = ttk.Scrollbar(self.urls_frame, orient="vertical", command=self.download_text.yview)
            urls_scroll.grid(row=0, column=1, sticky="ns")
            self.download_text.configure(yscrollcommand=urls_scroll.set)

            actions = ttk.Frame(parent)
            actions.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
            self.download_clear_button = ttk.Button(actions, command=lambda: self._clear_text(self.download_text))
            self.download_clear_button.pack(side="left")
            self.download_button = ttk.Button(actions, command=self._start_download)
            self.download_button.pack(side="right")

        def _build_upload_tab(self, parent):
            padding = {"padx": 10, "pady": 6}
            parent.columnconfigure(0, weight=1)
            parent.rowconfigure(1, weight=1)

            config = ttk.Frame(parent)
            config.grid(row=0, column=0, sticky="ew")
            config.columnconfigure(1, weight=1)

            self.remote_folder_label = ttk.Label(config)
            self.remote_folder_label.grid(row=0, column=0, sticky="w", **padding)
            self.remote_folder_entry = ttk.Entry(config, textvariable=self.upload_folder_var)
            self.remote_folder_entry.grid(row=0, column=1, sticky="ew", **padding)

            self.upload_workers_label = ttk.Label(config)
            self.upload_workers_label.grid(row=1, column=0, sticky="w", **padding)
            self.upload_threads_scale = tk.Scale(
                config,
                from_=1,
                to=self.max_worker_threads,
                orient="horizontal",
                variable=self.upload_threads_var,
                resolution=1,
                showvalue=False,
                highlightthickness=0,
            )
            self.upload_threads_scale.grid(row=1, column=1, sticky="ew", **padding)
            self.upload_threads_label = ttk.Label(config, textvariable=self.upload_threads_label_var, width=10)
            self.upload_threads_label.grid(row=1, column=2, sticky="w", **padding)

            self.paths_frame = ttk.LabelFrame(parent)
            self.paths_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
            self.paths_frame.columnconfigure(0, weight=1)
            self.paths_frame.rowconfigure(0, weight=1)
            self.upload_text = tk.Text(self.paths_frame, height=12, wrap="word")
            self.upload_text.grid(row=0, column=0, sticky="nsew")
            paths_scroll = ttk.Scrollbar(self.paths_frame, orient="vertical", command=self.upload_text.yview)
            paths_scroll.grid(row=0, column=1, sticky="ns")
            self.upload_text.configure(yscrollcommand=paths_scroll.set)

            actions = ttk.Frame(parent)
            actions.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
            self.add_files_button = ttk.Button(actions, command=self._add_files)
            self.add_files_button.pack(side="left")
            self.add_folder_button = ttk.Button(actions, command=self._add_folder)
            self.add_folder_button.pack(side="left", padx=(6, 0))
            self.upload_clear_button = ttk.Button(actions, command=lambda: self._clear_text(self.upload_text))
            self.upload_clear_button.pack(side="left", padx=(6, 0))
            self.upload_button = ttk.Button(actions, command=self._start_upload)
            self.upload_button.pack(side="right")

        def _apply_texts(self):
            self.title(self.i18n("app.title"))
            self.username_label.configure(text=self.i18n("gui.username"))
            self.password_label.configure(text=self.i18n("gui.password"))
            self.notebook.tab(self.download_tab, text=self.i18n("kind.download"))
            self.notebook.tab(self.upload_tab, text=self.i18n("kind.upload"))
            self.activity_frame.configure(text=self.i18n("gui.activity"))
            self.activity.heading("kind", text=self.i18n("gui.activity.kind"))
            self.activity.heading("state", text=self.i18n("gui.activity.state"))
            self.activity.heading("progress", text=self.i18n("gui.activity.progress"))
            self.activity.heading("target", text=self.i18n("gui.activity.target"))
            self.status_label.configure(text=self.i18n("gui.status.label"))
            self.output_label.configure(text=self.i18n("gui.download.output"))
            self.output_button.configure(text=self.i18n("gui.download.browse"))
            self.download_workers_label.configure(text=self.i18n("gui.workers"))
            self.recursive_check.configure(text=self.i18n("gui.download.recursive"))
            self.flatten_check.configure(text=self.i18n("gui.download.flatten"))
            self.keep_original_names_check.configure(text=self.i18n("gui.download.keep_original_names"))
            self.urls_frame.configure(text=self.i18n("gui.download.urls"))
            self.download_clear_button.configure(text=self.i18n("gui.clear"))
            self.download_button.configure(text=self.i18n("gui.download.start"))
            self.remote_folder_label.configure(text=self.i18n("gui.upload.remote_folder"))
            self.upload_workers_label.configure(text=self.i18n("gui.workers"))
            self.paths_frame.configure(text=self.i18n("gui.upload.paths"))
            self.add_files_button.configure(text=self.i18n("gui.upload.add_files"))
            self.add_folder_button.configure(text=self.i18n("gui.upload.add_folder"))
            self.upload_clear_button.configure(text=self.i18n("gui.clear"))
            self.upload_button.configure(text=self.i18n("gui.upload.start"))
            self._refresh_status()
            self._refresh_activity_rows()

        def _set_status_key(self, key, **kwargs):
            self.status_state = ("key", key, kwargs)
            self.status_var.set(self.i18n(key, **kwargs))

        def _set_status_text(self, text):
            self.status_state = ("text", str(text))
            self.status_var.set(str(text))

        def _set_status_task(self, kind, state):
            self.status_state = ("task", kind, state)
            self.status_var.set(
                self.i18n(
                    "gui.status.task",
                    kind=self.i18n(f"kind.{kind}"),
                    state=self.i18n(f"state.{state}"),
                )
            )

        def _refresh_status(self):
            kind = self.status_state[0]
            if kind == "key":
                _, key, kwargs = self.status_state
                self.status_var.set(self.i18n(key, **kwargs))
                return
            if kind == "task":
                _, task_kind, task_state = self.status_state
                self.status_var.set(
                    self.i18n(
                        "gui.status.task",
                        kind=self.i18n(f"kind.{task_kind}"),
                        state=self.i18n(f"state.{task_state}"),
                    )
                )
                return
            self.status_var.set(self.status_state[1])

        def _toggle_language(self):
            language = "en" if self.i18n.language == "pl" else "pl"
            self.i18n.set_language(language)
            self._apply_texts()
            try:
                save_env_values(
                    self.env_path,
                    {
                        "USERNAME": self.username_var.get().strip(),
                        "PASSWORD": self.password_var.get(),
                        "LANGUAGE": self.i18n.language,
                    },
                )
            except OSError as exc:
                self._set_status_text(self.i18n("gui.error.save_env", error=exc))

        def _schedule_env_save(self, *_):
            if self.env_save_job is not None:
                self.after_cancel(self.env_save_job)
            self.env_save_job = self.after(120, self._save_credentials_to_env)

        def _save_credentials_to_env(self):
            self.env_save_job = None
            try:
                save_env_values(
                    self.env_path,
                    {
                        "USERNAME": self.username_var.get().strip(),
                        "PASSWORD": self.password_var.get(),
                        "LANGUAGE": self.i18n.language,
                    },
                )
            except OSError as exc:
                self._set_status_text(self.i18n("gui.error.save_env", error=exc))

        def _refresh_download_threads_label(self, *_):
            value = max(1, min(self.max_worker_threads, int(self.download_threads_var.get() or 1)))
            if value != self.download_threads_var.get():
                self.download_threads_var.set(value)
                return
            self.download_threads_label_var.set(f"{value} / {self.max_worker_threads}")

        def _refresh_upload_threads_label(self, *_):
            value = max(1, min(self.max_worker_threads, int(self.upload_threads_var.get() or 1)))
            if value != self.upload_threads_var.get():
                self.upload_threads_var.set(value)
                return
            self.upload_threads_label_var.set(f"{value} / {self.max_worker_threads}")

        def _browse_output(self):
            path = filedialog.askdirectory(initialdir=self.download_output_var.get() or os.getcwd())
            if path:
                self.download_output_var.set(path)

        def _add_files(self):
            paths = filedialog.askopenfilenames()
            if paths:
                self._append_lines(self.upload_text, paths)

        def _add_folder(self):
            path = filedialog.askdirectory(initialdir=os.getcwd())
            if path:
                self._append_lines(self.upload_text, [path])

        def _append_lines(self, widget, lines):
            existing = widget.get("1.0", "end-1c").strip()
            text = "\n".join(lines)
            if existing:
                widget.insert("end", "\n" + text)
            else:
                widget.insert("1.0", text)

        def _clear_text(self, widget):
            widget.delete("1.0", "end")

        def _lines(self, widget):
            return [line.strip() for line in widget.get("1.0", "end-1c").splitlines() if line.strip()]

        def _on_close(self):
            if self.busy and not messagebox.askyesno(self.i18n("gui.dialog.close.title"), self.i18n("gui.dialog.close.message")):
                return
            if self.env_save_job is not None:
                self.after_cancel(self.env_save_job)
                self._save_credentials_to_env()
            self.destroy()

        def _set_busy(self, busy):
            self.busy = busy
            state = "disabled" if busy else "normal"
            for widget in (
                self.username_entry,
                self.password_entry,
                self.language_button,
                self.output_entry,
                self.output_button,
                self.threads_scale,
                self.recursive_check,
                self.flatten_check,
                self.keep_original_names_check,
                self.download_button,
                self.download_clear_button,
                self.remote_folder_entry,
                self.upload_threads_scale,
                self.add_files_button,
                self.add_folder_button,
                self.upload_button,
                self.upload_clear_button,
            ):
                widget.configure(state=state)
            if busy:
                self._set_status_key("gui.status.working")

        def _start_worker(self, status_key, worker, *args):
            if self.busy:
                messagebox.showinfo(self.i18n("gui.dialog.busy.title"), self.i18n("gui.dialog.busy.message"))
                return
            self._set_busy(True)
            self._set_status_key(status_key)
            thread = threading.Thread(target=self._worker_main, args=(worker, args), daemon=True)
            thread.start()

        def _worker_main(self, worker, args):
            try:
                worker(*args)
                self.queue.put(("done",))
            except ChomikujError as exc:
                self.queue.put(("error", exc))
            except Exception as exc:
                self.queue.put(("error", exc))
            finally:
                self.queue.put(("worker_finished",))

        def _credentials(self):
            username = self.username_var.get().strip()
            password = self.password_var.get()
            if not username:
                raise ChomikujError(self.i18n("gui.error.missing_username"))
            if not password:
                raise ChomikujError(self.i18n("gui.error.missing_password"))
            return username, password

        def _start_download(self):
            try:
                username, password = self._credentials()
            except ChomikujError as exc:
                messagebox.showerror(self.i18n("gui.dialog.error.title"), str(exc))
                return
            urls = self._lines(self.download_text)
            if not urls:
                messagebox.showerror(self.i18n("gui.dialog.error.title"), self.i18n("gui.error.missing_urls"))
                return
            output = self.download_output_var.get().strip() or os.getcwd()
            threads = max(1, min(self.max_worker_threads, int(self.download_threads_var.get() or 1)))
            recursive = bool(self.download_recursive_var.get())
            flatten = bool(self.download_flatten_var.get())
            keep_original_names = bool(self.download_keep_original_names_var.get())
            self._start_worker(
                "gui.status.downloading",
                self._download_worker,
                username,
                password,
                urls,
                output,
                threads,
                recursive,
                flatten,
                keep_original_names,
            )

        def _start_upload(self):
            try:
                username, password = self._credentials()
            except ChomikujError as exc:
                messagebox.showerror(self.i18n("gui.dialog.error.title"), str(exc))
                return
            paths = self._lines(self.upload_text)
            if not paths:
                messagebox.showerror(self.i18n("gui.dialog.error.title"), self.i18n("gui.error.missing_upload_paths"))
                return
            folder = self.upload_folder_var.get().strip()
            threads = max(1, min(self.max_worker_threads, int(self.upload_threads_var.get() or 1)))
            self._start_worker("gui.status.uploading", self._upload_worker, username, password, paths, folder, threads)

        def _download_worker(self, username, password, urls, output, threads, recursive, flatten, keep_original_names):
            os.makedirs(output, exist_ok=True)
            downloader = DownloadManager(
                username,
                password,
                threads,
                output,
                password_provider=self.password,
                status_sink=self,
                recursive=recursive,
                flatten=flatten,
                keep_original_names=keep_original_names,
                i18n=self.i18n,
            )
            for url in urls:
                downloader.handle_url(url)
            downloader.wait()

        def _upload_worker(self, username, password, paths, folder, threads):
            uploader = UploadManager(
                username,
                password,
                max_threads=threads,
                password_provider=self.password,
                status_sink=self,
                i18n=self.i18n,
            )
            uploader.upload_files(paths, folder=folder)

        def _process_queue(self):
            while True:
                try:
                    action = self.queue.get_nowait()
                except queue.Empty:
                    break

                kind = action[0]
                if kind == "done":
                    self._set_status_key("gui.status.done")
                elif kind == "error":
                    error_text = str(action[1])
                    self._set_status_text(error_text)
                    messagebox.showerror(self.i18n("gui.dialog.error.title"), error_text)
                elif kind == "worker_finished":
                    self._set_busy(False)
                elif kind == "task":
                    self._update_task(*action[1:])
                elif kind == "password_prompt":
                    _, prompt_kind, identifier, retry, allow_skip, event, box = action
                    if prompt_kind == "account":
                        prompt = self.i18n("terminal.prompt.account_password", identifier=identifier).rstrip()
                    else:
                        prompt = self.i18n("terminal.prompt.folder_password", identifier=identifier).rstrip()
                    box.update(self._prompt_password_dialog(prompt, retry=retry, allow_skip=allow_skip))
                    event.set()
            self.after(100, self._process_queue)

        def _prompt_password_dialog(self, prompt, retry=False, allow_skip=False):
            result = {"action": "cancel", "password": ""}
            dialog = tk.Toplevel(self)
            dialog.title(self.i18n("gui.dialog.password.title"))
            dialog.transient(self)
            dialog.resizable(False, False)
            dialog.grab_set()

            frame = ttk.Frame(dialog, padding=12)
            frame.grid(row=0, column=0, sticky="nsew")
            dialog.columnconfigure(0, weight=1)
            dialog.rowconfigure(0, weight=1)

            row = 0
            if retry:
                ttk.Label(frame, text=self.i18n("gui.dialog.password.retry")).grid(
                    row=row,
                    column=0,
                    columnspan=3,
                    sticky="w",
                    pady=(0, 8),
                )
                row += 1

            ttk.Label(frame, text=prompt, wraplength=420, justify="left").grid(
                row=row,
                column=0,
                columnspan=3,
                sticky="w",
            )
            row += 1

            password_var = tk.StringVar()
            entry = ttk.Entry(frame, textvariable=password_var, show="*", width=42)
            entry.grid(row=row, column=0, columnspan=3, sticky="ew", pady=(8, 0))
            frame.columnconfigure(0, weight=1)
            row += 1

            def finish(action):
                result["action"] = action
                result["password"] = password_var.get() if action == "submit" else ""
                dialog.destroy()

            button_frame = ttk.Frame(frame)
            button_frame.grid(row=row, column=0, columnspan=3, sticky="e", pady=(12, 0))
            ttk.Button(
                button_frame,
                text=self.i18n("gui.dialog.password.cancel"),
                command=lambda: finish("cancel"),
            ).pack(side="right", padx=(8, 0))
            if allow_skip:
                ttk.Button(
                    button_frame,
                    text=self.i18n("gui.dialog.password.skip"),
                    command=lambda: finish("skip"),
                ).pack(side="right")
            ttk.Button(
                button_frame,
                text=self.i18n("gui.dialog.password.submit"),
                command=lambda: finish("submit"),
            ).pack(side="right")

            dialog.protocol("WM_DELETE_WINDOW", lambda: finish("cancel"))
            dialog.bind("<Return>", lambda _event: finish("submit"))
            dialog.bind("<Escape>", lambda _event: finish("cancel"))
            self.update_idletasks()
            dialog.geometry(f"+{self.winfo_rootx() + 80}+{self.winfo_rooty() + 80}")
            entry.focus_set()
            dialog.wait_window()
            return result

        def _task_key(self, kind, path):
            return f"{kind}:{path}"

        def _format_progress(self, current, total):
            if total:
                percent = int((current / total) * 100)
                return f"{percent}% ({current}/{total})"
            if current:
                return str(current)
            return "-"

        def _task_values(self, data):
            progress = self._format_progress(data["current"] or 0, data["total"])
            target_text = data["target"] or data["path"]
            if data["error_text"]:
                target_text = f"{target_text} ({data['error_text']})"
            return (
                self.i18n(f"kind.{data['kind']}"),
                self.i18n(f"state.{data['state']}"),
                progress,
                target_text,
            )

        def _refresh_activity_rows(self):
            for row_key, row_id in self.row_ids.items():
                data = self.row_data.get(row_key)
                if data:
                    self.activity.item(row_id, values=self._task_values(data))

        def _update_task(self, kind, state, path, current, total, target, error_text):
            row_key = self._task_key(kind, path)
            row_id = self.row_ids.get(row_key)
            self.row_data[row_key] = {
                "kind": kind,
                "state": state,
                "path": path,
                "current": current,
                "total": total,
                "target": target,
                "error_text": error_text,
            }
            values = self._task_values(self.row_data[row_key])
            if not row_id:
                row_id = f"row_{len(self.row_ids) + 1}"
                self.row_ids[row_key] = row_id
                self.activity.insert("", "end", iid=row_id, values=values)
            else:
                self.activity.item(row_id, values=values)
            self._set_status_task(kind, state)

        def _push(self, action, *payload):
            self.queue.put((action, *payload))

        def password(self, kind, identifier, owner_name=None, retry=False, allow_skip=False):
            event = threading.Event()
            box = {}
            self._push("password_prompt", kind, identifier, retry, allow_skip, event, box)
            event.wait()
            return box or {"action": "cancel"}

        def download_queued(self, path):
            self._push("task", "download", "queued", path, 0, None, path, None)

        def download_started(self, path, downloaded, total):
            self._push("task", "download", "running", path, downloaded, total, path, None)

        def download_progress(self, path, downloaded, total):
            self._push("task", "download", "running", path, downloaded, total, path, None)

        def download_finished(self, path, downloaded, total):
            self._push("task", "download", "finished", path, downloaded, total, path, None)

        def download_skipped(self, path):
            self._push("task", "download", "skipped", path, 0, None, path, None)

        def download_failed(self, path, error):
            self._push("task", "download", "failed", path, 0, None, path, str(error))

        def upload_started(self, path, target, total):
            self._push("task", "upload", "running", path, 0, total, target, None)

        def upload_progress(self, path, uploaded, total, target):
            self._push("task", "upload", "running", path, uploaded, total, target, None)

        def upload_finished(self, path, target, total):
            self._push("task", "upload", "finished", path, total, total, target, None)

        def upload_failed(self, path, error, target):
            self._push("task", "upload", "failed", path, 0, None, target, str(error))


def run_gui(script_path):
    if tk is None:
        env = load_default_env(script_path)
        i18n = Translator(env_language(env))
        print(i18n("gui.no_tkinter"), file=sys.stderr)
        sys.exit(1)
    app = ChomikujGui(script_path)
    app.mainloop()


def main():
    run_gui(__file__)


if __name__ == "__main__":
    main()
