"""Provide a simple desktop GUI for portable chat exports.

This module exposes a Tkinter-based launcher for the existing export pipeline.
It maps GUI fields to ``ExportConfig``, runs exports in a background thread,
streams logs into the window, and is intended for packaging as a portable
Windows executable.
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import Any, Optional

from . import __version__
from .common.logging_setup import setup_logging
from .config import ExportConfig
from .config_factory import build_export_config, parse_non_negative_int
from .constants import DEFAULT_SOURCE_APP, DEFAULT_TIMEZONE, LOG_LEVELS, SOURCE_APPS, SOURCE_APP_THREEMA
from .orchestrator import export_all_conversations


class QueueLogHandler(logging.Handler):
    """Push formatted log records into a GUI queue."""

    def __init__(self, target_queue: "queue.Queue[str]") -> None:
        """Initialize the handler.

        Args:
            target_queue (queue.Queue[str]): GUI log target queue.
        """
        super().__init__()
        self._target_queue = target_queue

    def emit(self, record: logging.LogRecord) -> None:
        """Emit one formatted log record into the queue.

        Args:
            record (logging.LogRecord): Log record.
        """
        try:
            self._target_queue.put_nowait(self.format(record))
        except Exception:
            self.handleError(record)


@dataclass(slots=True)
class GuiResult:
    """Store the result of one GUI-triggered export run.

    Attributes:
        ok (bool): ``True`` on success.
        message (str): Summary message for dialogs and status updates.
        payload (Optional[dict[str, Any]]): Export result payload on success.
    """

    ok: bool
    message: str
    payload: Optional[dict[str, Any]] = None


class ChatExportGui:
    """Render and control the Tkinter export launcher."""

    def __init__(self, root: tk.Tk) -> None:
        """Initialize the GUI.

        Args:
            root (tk.Tk): Tk root window.
        """
        self.root = root
        self.root.title(f"ChatExportPDF {__version__}")
        self.root.minsize(880, 720)

        self._log_queue: queue.Queue[str] = queue.Queue()
        self._result_queue: queue.Queue[GuiResult] = queue.Queue()
        self._log_handler = QueueLogHandler(self._log_queue)
        self._running = False
        self._auto_out_dir = True
        self._last_auto_out_dir = ""
        self._updating_out_dir = False
        self._last_output_dir: Optional[str] = None

        self._build_variables()
        self._build_layout()
        self._bind_events()
        self._refresh_source_fields()
        self._sync_auto_output_dir()
        self.root.after(100, self._poll_queues)

    def _build_variables(self) -> None:
        """Create Tkinter state variables."""
        self.source_var = tk.StringVar(value=DEFAULT_SOURCE_APP)
        self.input_path_var = tk.StringVar()
        self.out_dir_var = tk.StringVar()
        self.external_folder_var = tk.StringVar()
        self.chat_text_name_var = tk.StringVar()
        self.tz_var = tk.StringVar(value=DEFAULT_TIMEZONE)
        self.export_media_var = tk.BooleanVar(value=True)
        self.export_image_previews_var = tk.BooleanVar(value=True)
        self.max_media_bytes_var = tk.StringVar(value="0")
        self.limit_conversations_var = tk.StringVar(value="0")
        self.limit_messages_var = tk.StringVar(value="0")
        self.log_level_var = tk.StringVar(value="INFO")
        self.log_file_var = tk.StringVar()
        self.show_advanced_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Ready")
        self.source_hint_var = tk.StringVar()

    def _build_layout(self) -> None:
        """Build the window layout."""
        outer = ttk.Frame(self.root, padding=12)
        outer.grid(row=0, column=0, sticky="nsew")
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        outer.columnconfigure(0, weight=1)
        outer.rowconfigure(3, weight=1)

        basic = ttk.LabelFrame(outer, text="Basic")
        basic.grid(row=0, column=0, sticky="ew")
        basic.columnconfigure(1, weight=1)

        ttk.Label(basic, text="Source").grid(row=0, column=0, sticky="w", padx=(8, 8), pady=(8, 6))
        self.source_combo = ttk.Combobox(
            basic,
            textvariable=self.source_var,
            values=SOURCE_APPS,
            state="readonly",
        )
        self.source_combo.grid(row=0, column=1, sticky="ew", padx=(0, 8), pady=(8, 6))

        self.input_label = ttk.Label(basic, text="Input")
        self.input_label.grid(row=1, column=0, sticky="w", padx=(8, 8), pady=6)
        self.input_entry = ttk.Entry(basic, textvariable=self.input_path_var)
        self.input_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8), pady=6)
        self.input_browse_button = ttk.Button(basic, text="Browse...", command=self._browse_input_path)
        self.input_browse_button.grid(
            row=1, column=2, sticky="ew", padx=(0, 8), pady=6
        )

        ttk.Label(basic, text="Output folder").grid(row=2, column=0, sticky="w", padx=(8, 8), pady=6)
        self.out_dir_entry = ttk.Entry(basic, textvariable=self.out_dir_var)
        self.out_dir_entry.grid(row=2, column=1, sticky="ew", padx=(0, 8), pady=6)
        self.output_browse_button = ttk.Button(basic, text="Browse...", command=self._browse_output_dir)
        self.output_browse_button.grid(
            row=2, column=2, sticky="ew", padx=(0, 8), pady=6
        )

        self.external_label = ttk.Label(basic, text="External folder")
        self.external_entry = ttk.Entry(basic, textvariable=self.external_folder_var)
        self.external_button = ttk.Button(basic, text="Browse...", command=self._browse_external_folder)

        options_row = ttk.Frame(basic)
        options_row.grid(row=4, column=0, columnspan=3, sticky="w", padx=8, pady=(2, 8))
        self.export_media_check = ttk.Checkbutton(
            options_row,
            text="Export media",
            variable=self.export_media_var,
        )
        self.export_media_check.grid(row=0, column=0, sticky="w", padx=(0, 16))
        self.image_preview_check = ttk.Checkbutton(
            options_row,
            text="Image previews",
            variable=self.export_image_previews_var,
        )
        self.image_preview_check.grid(row=0, column=1, sticky="w")

        ttk.Label(
            basic,
            textvariable=self.source_hint_var,
            foreground="#555555",
        ).grid(row=5, column=0, columnspan=3, sticky="w", padx=8, pady=(0, 8))

        controls = ttk.Frame(outer)
        controls.grid(row=1, column=0, sticky="ew", pady=(10, 10))
        controls.columnconfigure(1, weight=1)
        self.advanced_button = ttk.Button(
            controls,
            text="Show advanced options",
            command=self._toggle_advanced,
        )
        self.advanced_button.grid(row=0, column=0, sticky="w")
        ttk.Label(controls, textvariable=self.status_var).grid(row=0, column=1, sticky="w", padx=(16, 0))
        self.open_output_button = ttk.Button(
            controls,
            text="Open output folder",
            command=self._open_output_folder,
            state="disabled",
        )
        self.open_output_button.grid(row=0, column=2, sticky="e", padx=(8, 8))
        self.run_button = ttk.Button(controls, text="Start export", command=self._start_export)
        self.run_button.grid(row=0, column=3, sticky="e")

        self.advanced_frame = ttk.LabelFrame(outer, text="Advanced")
        self.advanced_frame.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        self.advanced_frame.columnconfigure(1, weight=1)

        self.chat_text_label = ttk.Label(self.advanced_frame, text="WhatsApp chat text name")
        self.chat_text_entry = ttk.Entry(self.advanced_frame, textvariable=self.chat_text_name_var)
        self.chat_text_label.grid(row=0, column=0, sticky="w", padx=(8, 8), pady=(8, 6))
        self.chat_text_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=(8, 6))

        ttk.Label(self.advanced_frame, text="Timezone").grid(row=1, column=0, sticky="w", padx=(8, 8), pady=6)
        ttk.Entry(self.advanced_frame, textvariable=self.tz_var).grid(
            row=1, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=6
        )

        ttk.Label(self.advanced_frame, text="Max media bytes").grid(row=2, column=0, sticky="w", padx=(8, 8), pady=6)
        ttk.Entry(self.advanced_frame, textvariable=self.max_media_bytes_var).grid(
            row=2, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=6
        )

        ttk.Label(self.advanced_frame, text="Limit conversations").grid(
            row=3, column=0, sticky="w", padx=(8, 8), pady=6
        )
        ttk.Entry(self.advanced_frame, textvariable=self.limit_conversations_var).grid(
            row=3, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=6
        )

        ttk.Label(self.advanced_frame, text="Limit messages").grid(
            row=4, column=0, sticky="w", padx=(8, 8), pady=6
        )
        ttk.Entry(self.advanced_frame, textvariable=self.limit_messages_var).grid(
            row=4, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=6
        )

        ttk.Label(self.advanced_frame, text="Log level").grid(row=5, column=0, sticky="w", padx=(8, 8), pady=6)
        ttk.Combobox(
            self.advanced_frame,
            textvariable=self.log_level_var,
            values=LOG_LEVELS,
            state="readonly",
        ).grid(row=5, column=1, columnspan=2, sticky="ew", padx=(0, 8), pady=6)

        ttk.Label(self.advanced_frame, text="Log file").grid(row=6, column=0, sticky="w", padx=(8, 8), pady=(6, 8))
        ttk.Entry(self.advanced_frame, textvariable=self.log_file_var).grid(
            row=6, column=1, sticky="ew", padx=(0, 8), pady=(6, 8)
        )
        self.log_file_browse_button = ttk.Button(self.advanced_frame, text="Browse...", command=self._browse_log_file)
        self.log_file_browse_button.grid(
            row=6, column=2, sticky="ew", padx=(0, 8), pady=(6, 8)
        )
        self.advanced_frame.grid_remove()

        log_frame = ttk.LabelFrame(outer, text="Log")
        log_frame.grid(row=3, column=0, sticky="nsew")
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)
        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap="word",
            height=18,
            state="disabled",
            font=("Consolas", 9),
        )
        self.log_text.grid(row=0, column=0, sticky="nsew", padx=8, pady=8)

    def _bind_events(self) -> None:
        """Bind variable and widget events."""
        self.source_var.trace_add("write", self._on_source_changed)
        self.input_path_var.trace_add("write", self._on_input_path_changed)
        self.out_dir_var.trace_add("write", self._on_out_dir_changed)

    def _on_source_changed(self, *_args: object) -> None:
        """React to source changes."""
        self._refresh_source_fields()
        self._sync_auto_output_dir()

    def _on_input_path_changed(self, *_args: object) -> None:
        """React to input path changes."""
        self._sync_auto_output_dir()

    def _on_out_dir_changed(self, *_args: object) -> None:
        """Track whether the output path is still auto-managed."""
        if self._updating_out_dir:
            return
        current = self.out_dir_var.get().strip()
        self._auto_out_dir = not current or current == self._last_auto_out_dir

    def _refresh_source_fields(self) -> None:
        """Update source-specific labels and field visibility."""
        source = self.source_var.get()
        if source == SOURCE_APP_THREEMA:
            self.input_label.configure(text="Threema SQLite DB")
            self.source_hint_var.set("Threema: select ThreemaData.sqlite. _EXTERNAL_DATA is optional but recommended.")
            self.external_label.grid(row=3, column=0, sticky="w", padx=(8, 8), pady=6)
            self.external_entry.grid(row=3, column=1, sticky="ew", padx=(0, 8), pady=6)
            self.external_button.grid(row=3, column=2, sticky="ew", padx=(0, 8), pady=6)
            self.chat_text_label.grid_remove()
            self.chat_text_entry.grid_remove()
        else:
            self.input_label.configure(text="WhatsApp ZIP")
            self.source_hint_var.set("WhatsApp: select the exported ZIP. Chat text name is only needed if the ZIP is ambiguous.")
            self.external_label.grid_remove()
            self.external_entry.grid_remove()
            self.external_button.grid_remove()
            self.chat_text_label.grid()
            self.chat_text_entry.grid()

    def _toggle_advanced(self) -> None:
        """Show or hide the advanced options frame."""
        visible = self.show_advanced_var.get()
        if visible:
            self.show_advanced_var.set(False)
            self.advanced_frame.grid_remove()
            self.advanced_button.configure(text="Show advanced options")
        else:
            self.show_advanced_var.set(True)
            self.advanced_frame.grid()
            self.advanced_button.configure(text="Hide advanced options")

    def _browse_input_path(self) -> None:
        """Open the source-specific file picker."""
        source = self.source_var.get()
        if source == SOURCE_APP_THREEMA:
            filetypes = [
                ("SQLite database", "*.sqlite"),
                ("All files", "*.*"),
            ]
        else:
            filetypes = [
                ("ZIP archive", "*.zip"),
                ("All files", "*.*"),
            ]
        selected = filedialog.askopenfilename(
            title="Select input file",
            filetypes=filetypes,
        )
        if selected:
            self.input_path_var.set(selected)

    def _browse_output_dir(self) -> None:
        """Open the output directory picker."""
        initial = self.out_dir_var.get().strip() or self._input_parent_dir()
        selected = filedialog.askdirectory(
            title="Select output folder",
            initialdir=initial or None,
            mustexist=False,
        )
        if selected:
            self._set_output_dir(selected, auto_managed=False)

    def _browse_external_folder(self) -> None:
        """Open the Threema external folder picker."""
        initial = self.external_folder_var.get().strip() or self._input_parent_dir()
        selected = filedialog.askdirectory(
            title="Select external folder",
            initialdir=initial or None,
            mustexist=True,
        )
        if selected:
            self.external_folder_var.set(selected)

    def _browse_log_file(self) -> None:
        """Open the optional log file picker."""
        initial_dir = self._input_parent_dir() or os.getcwd()
        selected = filedialog.asksaveasfilename(
            title="Select log file",
            initialdir=initial_dir,
            defaultextension=".log",
            filetypes=[("Log file", "*.log"), ("All files", "*.*")],
        )
        if selected:
            self.log_file_var.set(selected)

    def _input_parent_dir(self) -> str:
        """Return the current input file parent directory.

        Returns:
            str: Input parent directory or an empty string.
        """
        input_path = self.input_path_var.get().strip()
        if not input_path:
            return ""
        return str(Path(input_path).expanduser().resolve().parent)

    def _default_output_dir(self) -> str:
        """Compute the default output directory from the current input path.

        Returns:
            str: Default output directory path or an empty string.
        """
        raw_input = self.input_path_var.get().strip()
        if not raw_input:
            return ""
        input_path = Path(raw_input).expanduser()
        if not input_path.name:
            return ""
        return str(input_path.with_name(f"{input_path.stem}_export"))

    def _set_output_dir(self, path: str, *, auto_managed: bool) -> None:
        """Update the output directory field.

        Args:
            path (str): Output directory path.
            auto_managed (bool): Whether the path remains auto-managed.
        """
        self._updating_out_dir = True
        self.out_dir_var.set(path)
        self._updating_out_dir = False
        self._last_auto_out_dir = path if auto_managed else self._last_auto_out_dir
        self._auto_out_dir = auto_managed

    def _sync_auto_output_dir(self) -> None:
        """Refresh the default output directory if auto mode is active."""
        auto_path = self._default_output_dir()
        if not auto_path:
            return
        current = self.out_dir_var.get().strip()
        if self._auto_out_dir or not current or current == self._last_auto_out_dir:
            self._last_auto_out_dir = auto_path
            self._set_output_dir(auto_path, auto_managed=True)

    def _append_log_line(self, line: str) -> None:
        """Append one line to the GUI log widget.

        Args:
            line (str): Log line.
        """
        self.log_text.configure(state="normal")
        self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_queues(self) -> None:
        """Poll log and result queues from the worker thread."""
        while True:
            try:
                line = self._log_queue.get_nowait()
            except queue.Empty:
                break
            self._append_log_line(line)

        while True:
            try:
                result = self._result_queue.get_nowait()
            except queue.Empty:
                break
            self._handle_result(result)

        self.root.after(100, self._poll_queues)

    def _build_config(self) -> ExportConfig:
        """Build one export configuration from GUI state.

        Returns:
            ExportConfig: Export configuration.

        Raises:
            ValueError: If required fields are missing or invalid.
        """
        source = self.source_var.get().strip()
        input_path = self.input_path_var.get().strip()
        out_dir = self.out_dir_var.get().strip()
        if not source:
            raise ValueError("Source must not be empty.")
        if not input_path:
            raise ValueError("Input path must not be empty.")
        if not out_dir:
            raise ValueError("Output folder must not be empty.")

        return build_export_config(
            out_dir=out_dir,
            source_app=source,
            input_path=input_path,
            chat_text_name=self.chat_text_name_var.get(),
            external_folder=self.external_folder_var.get(),
            tz_name=self.tz_var.get(),
            export_media=self.export_media_var.get(),
            export_image_previews=self.export_image_previews_var.get(),
            max_media_bytes=parse_non_negative_int(
                self.max_media_bytes_var.get(),
                "Max media bytes",
            ),
            limit_conversations=parse_non_negative_int(
                self.limit_conversations_var.get(),
                "Limit conversations",
            ),
            limit_messages=parse_non_negative_int(
                self.limit_messages_var.get(),
                "Limit messages",
            ),
            log_level=self.log_level_var.get(),
            log_file=self.log_file_var.get(),
        )

    def _set_running(self, running: bool) -> None:
        """Enable or disable controls during export execution.

        Args:
            running (bool): Running state.
        """
        self._running = running
        state = "disabled" if running else "normal"
        for widget in (
            self.source_combo,
            self.input_entry,
            self.input_browse_button,
            self.out_dir_entry,
            self.output_browse_button,
            self.external_entry,
            self.external_button,
            self.chat_text_entry,
            self.export_media_check,
            self.image_preview_check,
            self.log_file_browse_button,
            self.run_button,
            self.advanced_button,
        ):
            try:
                widget.configure(state=state)
            except tk.TclError:
                pass

        if not running:
            self.source_combo.configure(state="readonly")
            self.run_button.configure(state="normal")
            self.advanced_button.configure(state="normal")

    def _run_export_worker(self, cfg: ExportConfig) -> None:
        """Run the export in a worker thread.

        Args:
            cfg (ExportConfig): Export configuration.
        """
        try:
            setup_logging(
                cfg.log_level,
                cfg.log_file,
                console=False,
                extra_handlers=[self._log_handler],
                replace_existing=True,
            )
            result = export_all_conversations(cfg)
        except Exception as exc:
            logging.getLogger("chat_export.gui").exception("GUI export failed")
            self._result_queue.put(
                GuiResult(
                    ok=False,
                    message=str(exc) or exc.__class__.__name__,
                    payload=None,
                )
            )
            return

        self._result_queue.put(
            GuiResult(
                ok=True,
                message=f"Export completed. Conversations: {len(result['exported'])}",
                payload=result,
            )
        )

    def _start_export(self) -> None:
        """Validate GUI fields and start the export worker."""
        if self._running:
            return
        try:
            cfg = self._build_config()
        except ValueError as exc:
            messagebox.showerror("Invalid input", str(exc), parent=self.root)
            return

        self.status_var.set("Running export...")
        self._last_output_dir = cfg.out_dir
        self.open_output_button.configure(state="disabled")
        self.log_text.configure(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.configure(state="disabled")
        self._append_log_line(f"Starting export for source={cfg.source_app}")
        self._set_running(True)

        worker = threading.Thread(
            target=self._run_export_worker,
            args=(cfg,),
            name="chat-export-gui-worker",
            daemon=True,
        )
        worker.start()

    def _handle_result(self, result: GuiResult) -> None:
        """Handle completion of one worker-thread export.

        Args:
            result (GuiResult): Export result.
        """
        self._set_running(False)
        if result.ok:
            self.status_var.set("Export completed")
            self.open_output_button.configure(state="normal")
            messagebox.showinfo("Export completed", result.message, parent=self.root)
        else:
            self.status_var.set("Export failed")
            messagebox.showerror("Export failed", result.message, parent=self.root)

    def _open_output_folder(self) -> None:
        """Open the last output folder in Explorer."""
        if not self._last_output_dir:
            return
        if not os.path.isdir(self._last_output_dir):
            messagebox.showerror(
                "Output folder missing",
                f"Output folder does not exist:\n{self._last_output_dir}",
                parent=self.root,
            )
            return
        if not hasattr(os, "startfile"):
            messagebox.showerror(
                "Unsupported platform",
                "Opening the output folder from the GUI is only supported on Windows.",
                parent=self.root,
            )
            return
        os.startfile(self._last_output_dir)


def main() -> int:
    """Run the GUI entry point.

    Returns:
        int: Process exit code.
    """
    root = tk.Tk()
    ChatExportGui(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
