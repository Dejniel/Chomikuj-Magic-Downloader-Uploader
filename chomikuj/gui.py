#!/usr/bin/env python3

import os
import queue
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk

from . import ChomikujDownloader, ChomikujUploader
from .common import ChomikujError, load_default_env, resolve_default_env_path, save_env_values


class ChomikujGui(tk.Tk):
    def __init__(self, script_path):
        super().__init__()
        env = load_default_env(script_path)
        self.env_path = resolve_default_env_path(script_path)
        self.title("Chomikuj Magic Downloader Uploader")
        self.geometry("1040x858")
        self.minsize(920, 748)

        self.queue = queue.Queue()
        self.worker = None
        self.busy = False
        self.rows = {}
        self.env_save_job = None
        self.max_download_threads = max(1, (os.cpu_count() or 1) * 2)

        self.username_var = tk.StringVar(value=env.get("USERNAME", ""))
        self.password_var = tk.StringVar(value=env.get("PASSWORD", ""))
        self.download_output_var = tk.StringVar(value=os.getcwd())
        self.download_threads_var = tk.IntVar(value=min(5, self.max_download_threads))
        self.download_threads_label_var = tk.StringVar()
        self.download_flatten_var = tk.BooleanVar(value=False)
        self.upload_folder_var = tk.StringVar(value="")
        self.status_var = tk.StringVar(value="Idle")

        self._build_ui()
        self._refresh_threads_label()
        self.username_var.trace_add("write", self._schedule_env_save)
        self.password_var.trace_add("write", self._schedule_env_save)
        self.download_threads_var.trace_add("write", self._refresh_threads_label)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._process_queue)

    def _build_ui(self):
        padding = {"padx": 10, "pady": 6}
        style = ttk.Style(self)
        style.configure("Activity.Treeview", rowheight=26)

        account = ttk.LabelFrame(self, text="Account")
        account.pack(fill="x", padx=10, pady=10)
        account.columnconfigure(1, weight=1)

        ttk.Label(account, text="Username:").grid(row=0, column=0, sticky="w", **padding)
        self.username_entry = ttk.Entry(account, textvariable=self.username_var)
        self.username_entry.grid(row=0, column=1, sticky="ew", **padding)

        ttk.Label(account, text="Password:").grid(row=1, column=0, sticky="w", **padding)
        self.password_entry = ttk.Entry(account, textvariable=self.password_var, show="*")
        self.password_entry.grid(row=1, column=1, sticky="ew", **padding)

        notebook = ttk.Notebook(self)
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        download_tab = ttk.Frame(notebook)
        upload_tab = ttk.Frame(notebook)
        notebook.add(download_tab, text="Download")
        notebook.add(upload_tab, text="Upload")

        self._build_download_tab(download_tab)
        self._build_upload_tab(upload_tab)

        activity = ttk.LabelFrame(self, text="Activity")
        activity.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        activity.columnconfigure(0, weight=1)
        activity.rowconfigure(0, weight=1)
        columns = ("kind", "state", "progress", "target")
        self.activity = ttk.Treeview(activity, columns=columns, show="headings", height=16, style="Activity.Treeview")
        self.activity.heading("kind", text="Kind")
        self.activity.heading("state", text="State")
        self.activity.heading("progress", text="Progress")
        self.activity.heading("target", text="Target")
        self.activity.column("kind", width=90, anchor="w")
        self.activity.column("state", width=120, anchor="w")
        self.activity.column("progress", width=180, anchor="w")
        self.activity.column("target", width=700, anchor="w")
        self.activity.grid(row=0, column=0, sticky="nsew")
        activity_scroll = ttk.Scrollbar(activity, orient="vertical", command=self.activity.yview)
        activity_scroll.grid(row=0, column=1, sticky="ns")
        self.activity.configure(yscrollcommand=activity_scroll.set)

        status = ttk.Frame(self)
        status.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Label(status, text="Status:").pack(side="left")
        ttk.Label(status, textvariable=self.status_var).pack(side="left", padx=6)

    def _build_download_tab(self, parent):
        padding = {"padx": 10, "pady": 6}
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        config = ttk.Frame(parent)
        config.grid(row=0, column=0, sticky="ew")
        config.columnconfigure(1, weight=1)

        ttk.Label(config, text="Output:").grid(row=0, column=0, sticky="w", **padding)
        self.output_entry = ttk.Entry(config, textvariable=self.download_output_var)
        self.output_entry.grid(row=0, column=1, sticky="ew", **padding)
        self.output_button = ttk.Button(config, text="Browse", command=self._browse_output)
        self.output_button.grid(row=0, column=2, **padding)

        ttk.Label(config, text="Workers:").grid(row=1, column=0, sticky="w", **padding)
        self.threads_scale = tk.Scale(
            config,
            from_=1,
            to=self.max_download_threads,
            orient="horizontal",
            variable=self.download_threads_var,
            resolution=1,
            showvalue=False,
            highlightthickness=0,
        )
        self.threads_scale.grid(row=1, column=1, sticky="ew", **padding)
        ttk.Label(config, textvariable=self.download_threads_label_var, width=10).grid(row=1, column=2, sticky="w", **padding)

        self.flatten_check = ttk.Checkbutton(
            config,
            text="Flatten initial tree",
            variable=self.download_flatten_var,
        )
        self.flatten_check.grid(row=2, column=1, sticky="w", **padding)

        urls_frame = ttk.LabelFrame(parent, text="URLs (one per line)")
        urls_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        urls_frame.columnconfigure(0, weight=1)
        urls_frame.rowconfigure(0, weight=1)
        self.download_text = tk.Text(urls_frame, height=12, wrap="word")
        self.download_text.grid(row=0, column=0, sticky="nsew")
        urls_scroll = ttk.Scrollbar(urls_frame, orient="vertical", command=self.download_text.yview)
        urls_scroll.grid(row=0, column=1, sticky="ns")
        self.download_text.configure(yscrollcommand=urls_scroll.set)

        actions = ttk.Frame(parent)
        actions.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.download_clear_button = ttk.Button(actions, text="Clear", command=lambda: self._clear_text(self.download_text))
        self.download_clear_button.pack(side="left")
        self.download_button = ttk.Button(actions, text="Start Download", command=self._start_download)
        self.download_button.pack(side="right")

    def _build_upload_tab(self, parent):
        padding = {"padx": 10, "pady": 6}
        parent.columnconfigure(0, weight=1)
        parent.rowconfigure(1, weight=1)

        config = ttk.Frame(parent)
        config.grid(row=0, column=0, sticky="ew")
        config.columnconfigure(1, weight=1)

        ttk.Label(config, text="Remote folder:").grid(row=0, column=0, sticky="w", **padding)
        self.remote_folder_entry = ttk.Entry(config, textvariable=self.upload_folder_var)
        self.remote_folder_entry.grid(row=0, column=1, sticky="ew", **padding)

        paths_frame = ttk.LabelFrame(parent, text="Local files or folders (one per line)")
        paths_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        paths_frame.columnconfigure(0, weight=1)
        paths_frame.rowconfigure(0, weight=1)
        self.upload_text = tk.Text(paths_frame, height=12, wrap="word")
        self.upload_text.grid(row=0, column=0, sticky="nsew")
        paths_scroll = ttk.Scrollbar(paths_frame, orient="vertical", command=self.upload_text.yview)
        paths_scroll.grid(row=0, column=1, sticky="ns")
        self.upload_text.configure(yscrollcommand=paths_scroll.set)

        actions = ttk.Frame(parent)
        actions.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))
        self.add_files_button = ttk.Button(actions, text="Add Files", command=self._add_files)
        self.add_files_button.pack(side="left")
        self.add_folder_button = ttk.Button(actions, text="Add Folder", command=self._add_folder)
        self.add_folder_button.pack(side="left", padx=(6, 0))
        self.upload_clear_button = ttk.Button(actions, text="Clear", command=lambda: self._clear_text(self.upload_text))
        self.upload_clear_button.pack(side="left", padx=(6, 0))
        self.upload_button = ttk.Button(actions, text="Start Upload", command=self._start_upload)
        self.upload_button.pack(side="right")

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
                },
            )
        except OSError as exc:
            self.status_var.set(f"Failed to save .env: {exc}")

    def _refresh_threads_label(self, *_):
        value = max(1, min(self.max_download_threads, int(self.download_threads_var.get() or 1)))
        if value != self.download_threads_var.get():
            self.download_threads_var.set(value)
            return
        self.download_threads_label_var.set(f"{value} / {self.max_download_threads}")

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
        if self.busy and not messagebox.askyesno("Close", "An operation is still running. Close anyway?"):
            return
        self.destroy()

    def _set_busy(self, busy):
        self.busy = busy
        state = "disabled" if busy else "normal"
        for widget in (
            self.username_entry,
            self.password_entry,
            self.output_entry,
            self.output_button,
            self.threads_scale,
            self.flatten_check,
            self.download_button,
            self.download_clear_button,
            self.remote_folder_entry,
            self.add_files_button,
            self.add_folder_button,
            self.upload_button,
            self.upload_clear_button,
        ):
            widget.configure(state=state)
        if busy:
            self.status_var.set("Working...")

    def _start_worker(self, label, worker, *args):
        if self.busy:
            messagebox.showinfo("Busy", "Wait for the current operation to finish.")
            return
        self._set_busy(True)
        self.status_var.set(label)
        self.worker = threading.Thread(target=self._worker_main, args=(worker, args), daemon=True)
        self.worker.start()

    def _worker_main(self, worker, args):
        try:
            worker(*args)
            self.queue.put(("done", "Done"))
        except ChomikujError as exc:
            self.queue.put(("error", str(exc)))
        except Exception as exc:
            self.queue.put(("error", str(exc)))
        finally:
            self.queue.put(("worker_finished",))

    def _credentials(self):
        username = self.username_var.get().strip()
        password = self.password_var.get()
        if not username:
            raise ChomikujError("Missing username.")
        if not password:
            raise ChomikujError("Missing password.")
        return username, password

    def _start_download(self):
        try:
            username, password = self._credentials()
        except ChomikujError as exc:
            messagebox.showerror("Error", str(exc))
            return
        urls = self._lines(self.download_text)
        if not urls:
            messagebox.showerror("Error", "Enter at least one URL to download.")
            return
        output = self.download_output_var.get().strip() or os.getcwd()
        threads = max(1, min(self.max_download_threads, int(self.download_threads_var.get() or 1)))
        flatten = bool(self.download_flatten_var.get())
        self._start_worker("Downloading...", self._download_worker, username, password, urls, output, threads, flatten)

    def _start_upload(self):
        try:
            username, password = self._credentials()
        except ChomikujError as exc:
            messagebox.showerror("Error", str(exc))
            return
        paths = self._lines(self.upload_text)
        if not paths:
            messagebox.showerror("Error", "Enter at least one file or folder to upload.")
            return
        folder = self.upload_folder_var.get().strip()
        self._start_worker("Uploading...", self._upload_worker, username, password, paths, folder)

    def _download_worker(self, username, password, urls, output, threads, flatten):
        os.makedirs(output, exist_ok=True)
        downloader = ChomikujDownloader(
            username,
            password,
            threads,
            output,
            password_provider=self.password,
            status_sink=self,
            flatten=flatten,
        )
        for url in urls:
            downloader.handle_url(url)
        downloader.wait()

    def _upload_worker(self, username, password, paths, folder):
        uploader = ChomikujUploader(
            username,
            password,
            password_provider=self.password,
            status_sink=self,
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
                self.status_var.set(action[1])
            elif kind == "error":
                self.status_var.set(action[1])
                messagebox.showerror("Error", action[1])
            elif kind == "worker_finished":
                self._set_busy(False)
            elif kind == "task":
                self._update_task(*action[1:])
            elif kind == "password_prompt":
                _, prompt_kind, identifier, event, box = action
                if prompt_kind == "account":
                    prompt = f"Password for protected resources of user {identifier}:"
                else:
                    prompt = f"Password for folder {identifier}:"
                box["value"] = simpledialog.askstring("Password", prompt, show="*", parent=self) or ""
                event.set()
        self.after(100, self._process_queue)

    def _task_key(self, kind, path):
        return f"{kind}:{path}"

    def _format_progress(self, current, total):
        if total:
            percent = int((current / total) * 100)
            return f"{percent}% ({current}/{total})"
        if current:
            return str(current)
        return "-"

    def _update_task(self, kind, state, path, current, total, target, error_text):
        row_key = self._task_key(kind, path)
        row_id = self.rows.get(row_key)
        progress = self._format_progress(current or 0, total)
        target_text = target or path
        if error_text:
            target_text = f"{target_text} ({error_text})"
        values = (kind, state, progress, target_text)
        if not row_id:
            row_id = f"row_{len(self.rows) + 1}"
            self.rows[row_key] = row_id
            self.activity.insert("", "end", iid=row_id, values=values)
        else:
            self.activity.item(row_id, values=values)
        self.status_var.set(f"{kind}: {state}")

    def _push(self, action, *payload):
        self.queue.put((action, *payload))

    def password(self, kind, identifier):
        event = threading.Event()
        box = {}
        self._push("password_prompt", kind, identifier, event, box)
        event.wait()
        return box.get("value", "")

    def download_queued(self, path):
        self._push("task", "download", "queued", path, 0, None, None, None)

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
    app = ChomikujGui(script_path)
    app.mainloop()
