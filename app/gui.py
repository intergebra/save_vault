import threading
import time
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

from . import theme
from .config import load_config, save_config, new_profile
from .crypto_utils import generate_key_hex, key_from_hex
from .network import ReceiverServer, send_backup, AuthError
from .scheduler import BackupScheduler

ctk.set_appearance_mode("dark")


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Save Vault — Game Save Backup")
        self.geometry("980x620")
        self.minsize(860, 560)
        self.configure(fg_color=theme.BG_DARKEST)

        self.cfg = load_config()
        self.receiver_server: ReceiverServer | None = None

        self._build_layout()
        self.show_library()

        self.scheduler = BackupScheduler(
            get_profiles=lambda: self.cfg["profiles"],
            run_backup=self._run_backup_for_profile,
            log=self.log,
        )
        self.scheduler.start()

        if self.cfg.get("receiver", {}).get("enabled") and self.cfg["receiver"].get("dest_folder"):
            self._start_receiver(silent=True)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ------------------------------------------------------------------ layout
    def _build_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Sidebar
        sidebar = ctk.CTkFrame(self, width=190, fg_color=theme.BG_PANEL, corner_radius=0)
        sidebar.grid(row=0, column=0, rowspan=2, sticky="ns")
        sidebar.grid_propagate(False)

        ctk.CTkLabel(
            sidebar, text="SAVE VAULT", font=(theme.FONT_FAMILY, 20, "bold"),
            text_color=theme.ACCENT,
        ).pack(pady=(28, 30), padx=20, anchor="w")

        self.nav_buttons = {}
        for key, label in [("library", "🎮  Library"), ("receiver", "📥  Receiver"), ("settings", "⚙  Settings")]:
            btn = ctk.CTkButton(
                sidebar, text=label, anchor="w", height=42,
                fg_color="transparent", hover_color=theme.BG_CARD_HOVER,
                text_color=theme.TEXT, font=(theme.FONT_FAMILY, 14),
                command=lambda k=key: self._nav(k),
            )
            btn.pack(fill="x", padx=10, pady=2)
            self.nav_buttons[key] = btn

        # Main content area
        self.content = ctk.CTkFrame(self, fg_color=theme.BG_DARK, corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")

        # Log console at bottom
        log_frame = ctk.CTkFrame(self, fg_color=theme.BG_PANEL, corner_radius=0, height=140)
        log_frame.grid(row=1, column=1, sticky="ew")
        log_frame.grid_propagate(False)
        ctk.CTkLabel(
            log_frame, text="ACTIVITY LOG", font=(theme.FONT_FAMILY, 11, "bold"),
            text_color=theme.TEXT_DIM,
        ).pack(anchor="w", padx=14, pady=(8, 0))
        self.log_box = ctk.CTkTextbox(
            log_frame, fg_color=theme.BG_DARKEST, text_color=theme.TEXT,
            font=("Consolas", 11), corner_radius=6,
        )
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(2, 10))
        self.log_box.configure(state="disabled")

    def _nav(self, key):
        for k, btn in self.nav_buttons.items():
            btn.configure(fg_color=theme.BG_CARD if k == key else "transparent")
        {"library": self.show_library, "receiver": self.show_receiver, "settings": self.show_settings}[key]()

    def _clear_content(self):
        for widget in self.content.winfo_children():
            widget.destroy()

    # ------------------------------------------------------------------ logging
    def log(self, message: str):
        def _write():
            self.log_box.configure(state="normal")
            ts = datetime.now().strftime("%H:%M:%S")
            self.log_box.insert("end", f"[{ts}] {message}\n")
            self.log_box.see("end")
            self.log_box.configure(state="disabled")
        self.after(0, _write)

    # ------------------------------------------------------------------ LIBRARY VIEW
    def show_library(self):
        self._nav_highlight("library")
        self._clear_content()

        header = ctk.CTkFrame(self.content, fg_color="transparent")
        header.pack(fill="x", padx=24, pady=(22, 10))
        ctk.CTkLabel(header, text="My Games", font=(theme.FONT_FAMILY, 22, "bold"),
                     text_color=theme.TEXT_BRIGHT).pack(side="left")
        ctk.CTkButton(header, text="+ Add Game", fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      text_color=theme.BG_DARKEST, font=(theme.FONT_FAMILY, 13, "bold"),
                      command=self._open_profile_dialog).pack(side="right")

        self.library_scroll = ctk.CTkScrollableFrame(self.content, fg_color="transparent")
        self.library_scroll.pack(fill="both", expand=True, padx=24, pady=(0, 10))
        self._refresh_library()

    def _refresh_library(self):
        for widget in self.library_scroll.winfo_children():
            widget.destroy()

        if not self.cfg["profiles"]:
            ctk.CTkLabel(
                self.library_scroll, text="No games configured yet. Click \"+ Add Game\" to get started.",
                text_color=theme.TEXT_DIM, font=(theme.FONT_FAMILY, 13),
            ).pack(pady=40)
            return

        for profile in self.cfg["profiles"]:
            self._build_profile_card(profile)

    def _build_profile_card(self, profile):
        card = ctk.CTkFrame(self.library_scroll, fg_color=theme.BG_PANEL, corner_radius=10)
        card.pack(fill="x", pady=6)

        left = ctk.CTkFrame(card, fg_color="transparent")
        left.pack(side="left", fill="both", expand=True, padx=16, pady=12)

        ctk.CTkLabel(left, text=profile["name"], font=(theme.FONT_FAMILY, 16, "bold"),
                     text_color=theme.TEXT_BRIGHT).pack(anchor="w")
        ctk.CTkLabel(left, text=f"Save path: {profile['save_path']}", font=(theme.FONT_FAMILY, 11),
                     text_color=theme.TEXT_DIM).pack(anchor="w")
        ctk.CTkLabel(left, text=f"Target: {profile['remote_host']}:{profile['remote_port']}",
                     font=(theme.FONT_FAMILY, 11), text_color=theme.TEXT_DIM).pack(anchor="w")
        status_color = theme.GREEN if profile.get("last_status") == "Success" else theme.TEXT_DIM
        last = profile.get("last_backup") or "never"
        ctk.CTkLabel(left, text=f"Last backup: {last}  •  {profile.get('last_status', '')}",
                     font=(theme.FONT_FAMILY, 11), text_color=status_color).pack(anchor="w", pady=(4, 0))

        right = ctk.CTkFrame(card, fg_color="transparent")
        right.pack(side="right", padx=16, pady=12)

        auto_var = ctk.BooleanVar(value=profile.get("auto_enabled", False))

        def toggle_auto():
            profile["auto_enabled"] = auto_var.get()
            save_config(self.cfg)
            self.log(f"Automatic backup for '{profile['name']}' "
                      f"{'enabled (every ' + str(profile['interval_minutes']) + ' min)' if auto_var.get() else 'disabled'}.")

        ctk.CTkSwitch(right, text="Auto", variable=auto_var, command=toggle_auto,
                      progress_color=theme.ACCENT, text_color=theme.TEXT).pack(anchor="e", pady=(0, 8))

        btn_row = ctk.CTkFrame(right, fg_color="transparent")
        btn_row.pack(anchor="e")
        ctk.CTkButton(btn_row, text="Backup Now", width=100, fg_color=theme.ACCENT,
                      hover_color=theme.ACCENT_HOVER, text_color=theme.BG_DARKEST,
                      command=lambda p=profile: self._backup_now(p)).pack(side="left", padx=3)
        ctk.CTkButton(btn_row, text="Edit", width=60, fg_color=theme.BG_CARD,
                      hover_color=theme.BG_CARD_HOVER, text_color=theme.TEXT,
                      command=lambda p=profile: self._open_profile_dialog(p)).pack(side="left", padx=3)
        ctk.CTkButton(btn_row, text="Delete", width=70, fg_color=theme.RED,
                      hover_color="#b23c3c", text_color=theme.TEXT_BRIGHT,
                      command=lambda p=profile: self._delete_profile(p)).pack(side="left", padx=3)

    def _delete_profile(self, profile):
        if messagebox.askyesno("Delete Game", f"Remove '{profile['name']}' from Save Vault?"):
            self.cfg["profiles"] = [p for p in self.cfg["profiles"] if p["id"] != profile["id"]]
            save_config(self.cfg)
            self._refresh_library()

    def _backup_now(self, profile):
        threading.Thread(target=self._run_backup_for_profile, args=(profile,), daemon=True).start()

    def _run_backup_for_profile(self, profile):
        key_hex = self.cfg.get("key_hex", "")
        if not key_hex:
            self.log("No 256-bit key configured. Set one in Settings first.")
            profile["last_status"] = "No key configured"
            save_config(self.cfg)
            return
        try:
            key = key_from_hex(key_hex)
            send_backup(
                profile["remote_host"], int(profile["remote_port"]), key,
                profile["name"], profile["save_path"], log=self.log,
            )
            profile["last_status"] = "Success"
        except AuthError as exc:
            profile["last_status"] = "Auth failed"
            self.log(f"[{profile['name']}] {exc}")
        except Exception as exc:
            profile["last_status"] = f"Failed: {exc}"
            self.log(f"[{profile['name']}] Backup failed: {exc}")
        finally:
            profile["last_backup"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            save_config(self.cfg)
            self.after(0, self._safe_refresh_library)

    def _safe_refresh_library(self):
        if hasattr(self, "library_scroll") and self.library_scroll.winfo_exists():
            self._refresh_library()

    def _open_profile_dialog(self, profile=None):
        dialog = ProfileDialog(self, profile)
        self.wait_window(dialog)
        self._refresh_library()

    # ------------------------------------------------------------------ RECEIVER VIEW
    def show_receiver(self):
        self._nav_highlight("receiver")
        self._clear_content()

        wrap = ctk.CTkFrame(self.content, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=24, pady=22)

        ctk.CTkLabel(wrap, text="Receiver (this computer)", font=(theme.FONT_FAMILY, 22, "bold"),
                     text_color=theme.TEXT_BRIGHT).pack(anchor="w")
        ctk.CTkLabel(
            wrap, text="Run this on the destination computer to accept incoming encrypted backups.",
            text_color=theme.TEXT_DIM, font=(theme.FONT_FAMILY, 12),
        ).pack(anchor="w", pady=(2, 18))

        panel = ctk.CTkFrame(wrap, fg_color=theme.BG_PANEL, corner_radius=10)
        panel.pack(fill="x")

        r = self.cfg["receiver"]

        row1 = ctk.CTkFrame(panel, fg_color="transparent")
        row1.pack(fill="x", padx=20, pady=(20, 8))
        ctk.CTkLabel(row1, text="Listen Port", width=140, anchor="w", text_color=theme.TEXT).pack(side="left")
        self.port_entry = ctk.CTkEntry(row1, fg_color=theme.BG_DARKEST, text_color=theme.TEXT_BRIGHT)
        self.port_entry.insert(0, str(r.get("port", 5001)))
        self.port_entry.pack(side="left", fill="x", expand=True)

        row2 = ctk.CTkFrame(panel, fg_color="transparent")
        row2.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(row2, text="Destination Folder", width=140, anchor="w", text_color=theme.TEXT).pack(side="left")
        self.dest_entry = ctk.CTkEntry(row2, fg_color=theme.BG_DARKEST, text_color=theme.TEXT_BRIGHT)
        self.dest_entry.insert(0, r.get("dest_folder", ""))
        self.dest_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(row2, text="Browse", width=80, fg_color=theme.BG_CARD, hover_color=theme.BG_CARD_HOVER,
                      command=self._browse_dest).pack(side="left", padx=(8, 0))

        row3 = ctk.CTkFrame(panel, fg_color="transparent")
        row3.pack(fill="x", padx=20, pady=8)
        ctk.CTkLabel(row3, text="Keep Last N Backups", width=140, anchor="w", text_color=theme.TEXT).pack(side="left")
        self.keep_entry = ctk.CTkEntry(row3, fg_color=theme.BG_DARKEST, text_color=theme.TEXT_BRIGHT)
        self.keep_entry.insert(0, str(r.get("keep_last_n", 10)))
        self.keep_entry.pack(side="left", fill="x", expand=True)

        row4 = ctk.CTkFrame(panel, fg_color="transparent")
        row4.pack(fill="x", padx=20, pady=(12, 20))
        self.receiver_status = ctk.CTkLabel(
            row4, text=("● Running" if self._receiver_running() else "● Stopped"),
            text_color=(theme.GREEN if self._receiver_running() else theme.TEXT_DIM),
            font=(theme.FONT_FAMILY, 13, "bold"),
        )
        self.receiver_status.pack(side="left")
        self.receiver_toggle_btn = ctk.CTkButton(
            row4, text=("Stop Receiver" if self._receiver_running() else "Start Receiver"),
            fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER, text_color=theme.BG_DARKEST,
            command=self._toggle_receiver,
        )
        self.receiver_toggle_btn.pack(side="right")

    def _receiver_running(self):
        return bool(self.receiver_server and self.receiver_server.running)

    def _browse_dest(self):
        folder = filedialog.askdirectory(title="Choose destination folder for backups")
        if folder:
            self.dest_entry.delete(0, "end")
            self.dest_entry.insert(0, folder)

    def _toggle_receiver(self):
        if self._receiver_running():
            self.receiver_server.stop()
            self.cfg["receiver"]["enabled"] = False
            save_config(self.cfg)
            self.receiver_status.configure(text="● Stopped", text_color=theme.TEXT_DIM)
            self.receiver_toggle_btn.configure(text="Start Receiver")
        else:
            self._start_receiver()

    def _start_receiver(self, silent=False):
        try:
            port = int(self.port_entry.get()) if hasattr(self, "port_entry") else self.cfg["receiver"]["port"]
            dest = self.dest_entry.get() if hasattr(self, "dest_entry") else self.cfg["receiver"]["dest_folder"]
            keep = int(self.keep_entry.get()) if hasattr(self, "keep_entry") else self.cfg["receiver"].get("keep_last_n", 10)
            key_hex = self.cfg.get("key_hex", "")
            if not key_hex:
                if not silent:
                    messagebox.showerror("No Key", "Set a 256-bit shared key in Settings before starting the receiver.")
                return
            if not dest:
                if not silent:
                    messagebox.showerror("No Folder", "Choose a destination folder first.")
                return
            key = key_from_hex(key_hex)
            self.cfg["receiver"] = {"port": port, "dest_folder": dest, "keep_last_n": keep, "enabled": True}
            save_config(self.cfg)

            self.receiver_server = ReceiverServer(
                port=port, key=key, dest_folder=dest, keep_last_n=keep,
                log=self.log, on_event=lambda game, path: self.log(f"New backup for '{game}' saved."),
            )
            self.receiver_server.start()
            if hasattr(self, "receiver_status"):
                self.receiver_status.configure(text="● Running", text_color=theme.GREEN)
                self.receiver_toggle_btn.configure(text="Stop Receiver")
        except Exception as exc:
            self.log(f"Failed to start receiver: {exc}")
            if not silent:
                messagebox.showerror("Error", str(exc))

    # ------------------------------------------------------------------ SETTINGS VIEW
    def show_settings(self):
        self._nav_highlight("settings")
        self._clear_content()

        wrap = ctk.CTkFrame(self.content, fg_color="transparent")
        wrap.pack(fill="both", expand=True, padx=24, pady=22)

        ctk.CTkLabel(wrap, text="Settings", font=(theme.FONT_FAMILY, 22, "bold"),
                     text_color=theme.TEXT_BRIGHT).pack(anchor="w")
        ctk.CTkLabel(
            wrap, text="This 256-bit key must be identical on both computers. Generate it once, "
                       "then copy/paste it into Save Vault on the other machine.",
            text_color=theme.TEXT_DIM, font=(theme.FONT_FAMILY, 12), wraplength=760, justify="left",
        ).pack(anchor="w", pady=(2, 18))

        panel = ctk.CTkFrame(wrap, fg_color=theme.BG_PANEL, corner_radius=10)
        panel.pack(fill="x")

        row = ctk.CTkFrame(panel, fg_color="transparent")
        row.pack(fill="x", padx=20, pady=20)
        ctk.CTkLabel(row, text="Shared Key (hex)", width=140, anchor="w", text_color=theme.TEXT).pack(side="left")
        self.key_entry = ctk.CTkEntry(row, fg_color=theme.BG_DARKEST, text_color=theme.TEXT_BRIGHT, show="•")
        self.key_entry.insert(0, self.cfg.get("key_hex", ""))
        self.key_entry.pack(side="left", fill="x", expand=True)

        def toggle_show():
            self.key_entry.configure(show="" if self.key_entry.cget("show") == "•" else "•")

        ctk.CTkButton(row, text="Show", width=60, fg_color=theme.BG_CARD, hover_color=theme.BG_CARD_HOVER,
                      command=toggle_show).pack(side="left", padx=(8, 0))

        btn_row = ctk.CTkFrame(panel, fg_color="transparent")
        btn_row.pack(fill="x", padx=20, pady=(0, 20))
        ctk.CTkButton(btn_row, text="Generate New Key", fg_color=theme.BG_CARD, hover_color=theme.BG_CARD_HOVER,
                      command=self._generate_key).pack(side="left")
        ctk.CTkButton(btn_row, text="Copy to Clipboard", fg_color=theme.BG_CARD, hover_color=theme.BG_CARD_HOVER,
                      command=self._copy_key).pack(side="left", padx=8)
        ctk.CTkButton(btn_row, text="Save Key", fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      text_color=theme.BG_DARKEST, command=self._save_key).pack(side="right")

        note = ctk.CTkLabel(
            wrap, text="Tip: for backups over the internet (not just your LAN), pair this with a VPN "
                       "such as Tailscale/WireGuard, or forward the receiver's port on your router.",
            text_color=theme.TEXT_DIM, font=(theme.FONT_FAMILY, 11), wraplength=760, justify="left",
        )
        note.pack(anchor="w", pady=(16, 0))

    def _generate_key(self):
        new_key = generate_key_hex()
        self.key_entry.delete(0, "end")
        self.key_entry.insert(0, new_key)
        self.log("Generated a new 256-bit key. Remember to copy it to the other computer and Save.")

    def _copy_key(self):
        self.clipboard_clear()
        self.clipboard_append(self.key_entry.get().strip())
        self.log("Key copied to clipboard.")

    def _save_key(self):
        key_hex = self.key_entry.get().strip()
        try:
            key_from_hex(key_hex)  # validates length/format
        except Exception as exc:
            messagebox.showerror("Invalid Key", str(exc))
            return
        self.cfg["key_hex"] = key_hex
        save_config(self.cfg)
        self.log("Shared key saved.")
        messagebox.showinfo("Saved", "Key saved. Make sure the other computer uses the exact same key.")

    def _nav_highlight(self, key):
        for k, btn in self.nav_buttons.items():
            btn.configure(fg_color=theme.BG_CARD if k == key else "transparent")

    # ------------------------------------------------------------------ shutdown
    def _on_close(self):
        self.scheduler.stop()
        if self.receiver_server:
            self.receiver_server.stop()
        self.destroy()


class ProfileDialog(ctk.CTkToplevel):
    def __init__(self, app: App, profile=None):
        super().__init__(app)
        self.app = app
        self.profile = profile
        self.title("Edit Game" if profile else "Add Game")
        self.geometry("460x420")
        self.configure(fg_color=theme.BG_PANEL)
        self.resizable(False, False)
        self.transient(app)
        self.grab_set()

        pad = {"padx": 20, "pady": (14, 4)}

        ctk.CTkLabel(self, text="Game Name", text_color=theme.TEXT).pack(anchor="w", **pad)
        self.name_entry = ctk.CTkEntry(self, fg_color=theme.BG_DARKEST, text_color=theme.TEXT_BRIGHT)
        self.name_entry.pack(fill="x", padx=20)

        ctk.CTkLabel(self, text="Save Folder / File", text_color=theme.TEXT).pack(anchor="w", **pad)
        path_row = ctk.CTkFrame(self, fg_color="transparent")
        path_row.pack(fill="x", padx=20)
        self.path_entry = ctk.CTkEntry(path_row, fg_color=theme.BG_DARKEST, text_color=theme.TEXT_BRIGHT)
        self.path_entry.pack(side="left", fill="x", expand=True)
        ctk.CTkButton(path_row, text="Browse", width=80, fg_color=theme.BG_CARD, hover_color=theme.BG_CARD_HOVER,
                      command=self._browse_path).pack(side="left", padx=(8, 0))

        host_row = ctk.CTkFrame(self, fg_color="transparent")
        host_row.pack(fill="x", padx=20, pady=(14, 4))
        ctk.CTkLabel(host_row, text="Remote Host", text_color=theme.TEXT).pack(anchor="w")
        self.host_entry = ctk.CTkEntry(self, fg_color=theme.BG_DARKEST, text_color=theme.TEXT_BRIGHT)
        self.host_entry.pack(fill="x", padx=20)

        port_row = ctk.CTkFrame(self, fg_color="transparent")
        port_row.pack(fill="x", padx=20, pady=(14, 4))
        ctk.CTkLabel(port_row, text="Remote Port", text_color=theme.TEXT).pack(anchor="w")
        self.port_entry = ctk.CTkEntry(self, fg_color=theme.BG_DARKEST, text_color=theme.TEXT_BRIGHT)
        self.port_entry.pack(fill="x", padx=20)
        self.port_entry.insert(0, "5001")

        ctk.CTkLabel(self, text="Auto-backup Interval (minutes)", text_color=theme.TEXT).pack(anchor="w", **pad)
        self.interval_entry = ctk.CTkEntry(self, fg_color=theme.BG_DARKEST, text_color=theme.TEXT_BRIGHT)
        self.interval_entry.pack(fill="x", padx=20)
        self.interval_entry.insert(0, "30")

        if profile:
            self.name_entry.insert(0, profile["name"])
            self.path_entry.insert(0, profile["save_path"])
            self.host_entry.insert(0, profile["remote_host"])
            self.port_entry.delete(0, "end")
            self.port_entry.insert(0, str(profile["remote_port"]))
            self.interval_entry.delete(0, "end")
            self.interval_entry.insert(0, str(profile["interval_minutes"]))

        ctk.CTkButton(self, text="Save Game", fg_color=theme.ACCENT, hover_color=theme.ACCENT_HOVER,
                      text_color=theme.BG_DARKEST, command=self._save).pack(fill="x", padx=20, pady=(20, 20))

    def _browse_path(self):
        folder = filedialog.askdirectory(title="Select the save folder")
        if folder:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, folder)
            return
        file = filedialog.askopenfilename(title="...or select a single save file")
        if file:
            self.path_entry.delete(0, "end")
            self.path_entry.insert(0, file)

    def _save(self):
        name = self.name_entry.get().strip()
        path = self.path_entry.get().strip()
        host = self.host_entry.get().strip()
        port = self.port_entry.get().strip()
        interval = self.interval_entry.get().strip()

        if not name or not path or not host or not port:
            messagebox.showerror("Missing Info", "Please fill in name, save path, host, and port.")
            return
        if not Path(path).exists():
            if not messagebox.askyesno("Path Not Found", "That path doesn't exist yet. Save anyway?"):
                return
        try:
            port = int(port)
            interval = int(interval) if interval else 30
        except ValueError:
            messagebox.showerror("Invalid Number", "Port and interval must be numbers.")
            return

        if self.profile:
            self.profile.update({
                "name": name, "save_path": path, "remote_host": host,
                "remote_port": port, "interval_minutes": interval,
            })
        else:
            self.app.cfg["profiles"].append(new_profile(name, path, host, port, interval))

        save_config(self.app.cfg)
        self.destroy()


def run():
    app = App()
    app.mainloop()
