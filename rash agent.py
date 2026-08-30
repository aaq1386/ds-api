"""
DeepSeek Agent CLI - نسخه نهایی پایدار (v1.0 - Redesign)
- رفع خطای TclError در سایدبار
- نام‌گذاری هوشمند فایل‌های ذخیره‌شده
- نمایش (نه ذخیره) اسکریپت‌های bash/cmd/shell
- بازطراحی کامل ظاهر: تم رنگی یکپارچه، فونت‌های بهتر، فاصله‌گذاری و گوشه‌های گرد
"""

import customtkinter as ctk
import threading
import os
import re
import sqlite3
import subprocess
import sys
import shutil
from datetime import datetime
from tkinter import filedialog
import unicodedata

try:
    import arabic_reshaper
    from bidi.algorithm import get_display
    HAS_BIDI = True
except ImportError:
    HAS_BIDI = False

# ==================== API ====================
try:
    from DeepSeek.api import DeepSeekAPI
except ImportError:
    class DeepSeekAPI:
        def __init__(self, token): pass
        def create_chat_session(self): return "mock-chat-id"
        def chat_completion(self, *args, **kwargs):
            yield {"type": "text", "content": "خطا: ماژول API پیدا نشد."}

# ==================== تنظیمات ====================
TOKEN = ""
DB_PATH = "deepseek_agent.db"
IGNORE_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", ".idea", ".vscode"}
IGNORE_EXTS = {".pyc", ".pyo", ".exe", ".dll", ".so", ".dylib"}

NO_SAVE_LANGS = {"bash", "sh", "shell", "cmd", "bat", "powershell", "ps1", "zsh", "fish"}

# ==================== تم رنگی (Tokyo-Night Inspired) ====================
class Theme:
    # Backgrounds
    BG_APP        = "#0f1019"
    BG_TITLEBAR   = "#14151f"
    BG_SIDEBAR    = "#14151f"
    BG_PANEL      = "#181926"
    BG_TERMINAL   = "#0d0e17"
    BG_INPUTBAR   = "#161726"
    BG_STATUSBAR  = "#101119"
    BG_ENTRY      = "#0d0e17"
    BG_CODE       = "#171826"
    BG_SHELL      = "#1c1730"
    BG_HOVER      = "#232438"
    BG_SCROLL     = "#0d0e17"

    # Borders
    BORDER        = "#262838"
    BORDER_SOFT   = "#1f2030"

    # Text
    TEXT_PRIMARY  = "#c9cbe0"
    TEXT_BOT      = "#8fd6a8"
    TEXT_MUTED    = "#6b6f8f"
    TEXT_CODE     = "#e5e7f5"

    # Accents
    BLUE          = "#7aa2f7"
    BLUE_HOVER    = "#9ab8ff"
    PURPLE        = "#c398f7"
    PURPLE_HOVER  = "#d6b4ff"
    GREEN         = "#8fd6a8"
    GREEN_HOVER   = "#a6e6bc"
    GREEN_STRONG  = "#3fd97a"
    ORANGE        = "#f2b880"
    ORANGE_HOVER  = "#ffcb9c"
    RED           = "#f78ca2"
    RED_HOVER     = "#ff9fb4"
    YELLOW        = "#f5d38a"

    # Semantic buttons
    BTN_NEUTRAL   = "#22233a"
    BTN_NEUTRAL_H = "#2c2d48"

FONT_FAMILY_UI   = "Segoe UI"
FONT_FAMILY_MONO = "Cascadia Code"
FONT_FAMILY_FALLBACK_MONO = "Consolas"

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def sanitize_text(text):
    if text is None:
        return ""
    if not isinstance(text, str):
        text = str(text)
    return "".join(ch for ch in text if unicodedata.category(ch)[0] != "C" or ch in "\n\t\r")


def fix_text(text):
    text = sanitize_text(text)
    if not HAS_BIDI or not text:
        return text
    try:
        if any("\u0600" <= c <= "\u06FF" for c in text):
            return get_display(arabic_reshaper.reshape(text))
    except Exception:
        pass
    return text


class DeepSeekCLI(ctk.CTk):
    def __init__(self):
        super().__init__()

        try:
            self.iconbitmap("icon.ico")
        except Exception:
            pass

        self.title("DeepSeek • Terminal Pro  v1.0")
        self.geometry("1320x800")
        self.minsize(1040, 660)
        self.configure(fg_color=Theme.BG_APP)

        # State
        self.input_var = ctk.StringVar()
        self.is_processing = False
        self.use_thinking = True
        self.use_web_search = False
        self.chat_id = None
        self.parent_message_id = 0
        self.session_id = None
        self.current_dir = os.getcwd()
        self.command_popup = None
        self.temp_context = None
        self.attached_files = []
        self.auto_code_counter = 1
        self.file_list_cache = []
        self.command_history = []
        self.history_index = -1
        self._cursor_visible = True
        self._sidebar_refreshing = False

        self.api = DeepSeekAPI(TOKEN)

        # Fonts
        self.font_mono = ctk.CTkFont(family=FONT_FAMILY_MONO, size=13)
        self.font_mono_bold = ctk.CTkFont(family=FONT_FAMILY_MONO, size=13, weight="bold")
        self.font_small = ctk.CTkFont(family=FONT_FAMILY_MONO, size=11)
        self.font_prompt = ctk.CTkFont(family=FONT_FAMILY_MONO, size=15, weight="bold")
        self.font_title = ctk.CTkFont(family=FONT_FAMILY_UI, size=12, weight="bold")
        self.font_heading = ctk.CTkFont(family=FONT_FAMILY_UI, size=13, weight="bold")
        self.font_label = ctk.CTkFont(family=FONT_FAMILY_UI, size=11)

        self.init_db()
        self.setup_ui()
        self.setup_bindings()
        self.load_or_create_session()
        self._refresh_file_list()
        self.print_welcome()
        self._blink_cursor()
        self.after(100, self.refresh_sidebar)

    # ==================== دیتابیس ====================
    def init_db(self):
        try:
            self.conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            self.cursor = self.conn.cursor()
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    chat_id TEXT UNIQUE NOT NULL,
                    parent_message_id INTEGER DEFAULT 0,
                    title TEXT,
                    created_at TEXT,
                    updated_at TEXT
                )
            """)
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id INTEGER,
                    role TEXT,
                    content TEXT,
                    timestamp TEXT,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
            """)
            self.conn.commit()
            self.cursor.execute("PRAGMA table_info(sessions)")
            columns = [row[1] for row in self.cursor.fetchall()]
            if "parent_message_id" not in columns:
                self.cursor.execute("ALTER TABLE sessions ADD COLUMN parent_message_id INTEGER DEFAULT 0")
                self.conn.commit()
        except Exception as e:
            print(f"DB Init Error: {e}")

    def save_message_to_db(self, role, content):
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self.cursor.execute(
                "INSERT INTO messages (session_id, role, content, timestamp) VALUES (?, ?, ?, ?)",
                (self.session_id, role, content, now)
            )
            self.conn.commit()
        except Exception:
            pass

    def load_or_create_session(self):
        try:
            self.cursor.execute(
                "SELECT id, chat_id, parent_message_id, title FROM sessions ORDER BY updated_at DESC LIMIT 1"
            )
            row = self.cursor.fetchone()
            if row:
                self.session_id, self.chat_id, self.parent_message_id, title = row
                self.parent_message_id = self.parent_message_id or 0
                self.write(f"📂 سشن بارگذاری شد → [{self.session_id}] {title}", "system")
            else:
                self._create_new_session("سشن اول")
        except Exception:
            self._create_new_session("سشن اضطراری")
        self.update_status()

    def _create_new_session(self, title="گفتگوی جدید"):
        try:
            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            new_chat_id = self.api.create_chat_session()
            self.cursor.execute(
                "INSERT INTO sessions (chat_id, parent_message_id, title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (new_chat_id, 0, title, now, now)
            )
            self.conn.commit()
            self.session_id = self.cursor.lastrowid
            self.chat_id = new_chat_id
            self.parent_message_id = 0
            self.write(f"✅ سشن جدید ساخته شد → ID: {self.session_id}", "system")
            self.update_status()
            self.after(50, self.refresh_sidebar)
        except Exception as e:
            self.write(f"خطا در ساخت سشن: {e}", "error")

    def bump_parent_message_id(self):
        if not self.session_id:
            return
        self.parent_message_id += 2
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        try:
            self.cursor.execute(
                "UPDATE sessions SET parent_message_id = ?, updated_at = ? WHERE id = ?",
                (self.parent_message_id, now, self.session_id)
            )
            self.conn.commit()
        except Exception:
            pass

    def list_sessions(self):
        try:
            self.cursor.execute("SELECT id, title, updated_at FROM sessions ORDER BY updated_at DESC")
            rows = self.cursor.fetchall()
            if not rows:
                self.write("هیچ سشنی وجود ندارد.", "system")
                return
            self.write("──────── سشن‌ها ────────", "system")
            for r in rows:
                mark = "→" if r[0] == self.session_id else " "
                self.write(f"{mark} [{r[0]}] {r[1]}   ({r[2]})", "bot")
        except Exception as e:
            self.write(f"خطا: {e}", "error")

    def load_session(self, sid):
        try:
            sid = int(sid)
            self.cursor.execute("SELECT chat_id, parent_message_id, title FROM sessions WHERE id=?", (sid,))
            row = self.cursor.fetchone()
            if not row:
                self.write("سشن یافت نشد.", "error")
                return
            self.session_id = sid
            self.chat_id, self.parent_message_id, title = row
            self.parent_message_id = self.parent_message_id or 0
            self.write(f"✅ سشن بارگذاری شد → [{sid}] {title}", "bot")
            self.update_status()
            self.after(50, self.refresh_sidebar)
        except Exception as e:
            self.write(f"خطا: {e}", "error")

    def delete_session(self, sid):
        try:
            sid = int(sid)
            self.cursor.execute("DELETE FROM sessions WHERE id=?", (sid,))
            self.cursor.execute("DELETE FROM messages WHERE session_id=?", (sid,))
            self.conn.commit()
            self.write(f"✅ سشن {sid} حذف شد.", "bot")
            if self.session_id == sid:
                self._create_new_session()
            self.update_status()
            self.after(50, self.refresh_sidebar)
        except Exception as e:
            self.write(f"خطا: {e}", "error")

    # ==================== UI ====================
    def setup_ui(self):
        # Title bar
        titlebar = ctk.CTkFrame(self, fg_color=Theme.BG_TITLEBAR, height=38, corner_radius=0)
        titlebar.pack(fill="x", side="top")
        titlebar.pack_propagate(False)

        bottom_line = ctk.CTkFrame(titlebar, fg_color=Theme.BORDER, height=1, corner_radius=0)
        bottom_line.place(relx=0, rely=1.0, relwidth=1, anchor="sw")

        dots = ctk.CTkFrame(titlebar, fg_color="transparent")
        dots.pack(side="left", padx=16)
        for color in (Theme.RED, Theme.YELLOW, Theme.GREEN_STRONG):
            ctk.CTkLabel(dots, text="●", text_color=color, font=ctk.CTkFont(size=13), width=14).pack(side="left", padx=3)

        ctk.CTkLabel(
            titlebar, text="✦", font=ctk.CTkFont(size=14), text_color=Theme.PURPLE
        ).pack(side="left", padx=(6, 0))

        self.title_label = ctk.CTkLabel(
            titlebar, text="deepseek@pro  ·  v1.0",
            font=self.font_title, text_color=Theme.TEXT_MUTED
        )
        self.title_label.pack(side="right", padx=18)

        # Main container
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True)

        # ---------- Sidebar ----------
        self.sidebar = ctk.CTkFrame(main, width=270, fg_color=Theme.BG_SIDEBAR, corner_radius=0)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        sidebar_divider = ctk.CTkFrame(main, fg_color=Theme.BORDER, width=1)
        sidebar_divider.pack(side="left", fill="y")

        header_sessions = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        header_sessions.pack(fill="x", padx=14, pady=(18, 6))
        ctk.CTkLabel(header_sessions, text="◈  SESSIONS", font=self.font_heading, text_color=Theme.BLUE).pack(anchor="w")

        self.session_list = ctk.CTkScrollableFrame(
            self.sidebar, fg_color=Theme.BG_PANEL, height=190, corner_radius=10,
            scrollbar_button_color=Theme.BORDER, scrollbar_button_hover_color=Theme.BLUE
        )
        self.session_list.pack(fill="x", padx=12, pady=4)

        btn_new = ctk.CTkButton(
            self.sidebar, text="＋  New Session", height=32, font=self.font_label,
            corner_radius=8, fg_color=Theme.GREEN_STRONG, hover_color=Theme.GREEN_HOVER,
            text_color="#0a1a10", command=lambda: self._create_new_session()
        )
        btn_new.pack(fill="x", padx=12, pady=(6, 4))

        header_files = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        header_files.pack(fill="x", padx=14, pady=(18, 6))
        ctk.CTkLabel(header_files, text="◈  FILES", font=self.font_heading, text_color=Theme.GREEN).pack(anchor="w")

        self.file_list_frame = ctk.CTkScrollableFrame(
            self.sidebar, fg_color=Theme.BG_PANEL, corner_radius=10,
            scrollbar_button_color=Theme.BORDER, scrollbar_button_hover_color=Theme.GREEN
        )
        self.file_list_frame.pack(fill="both", expand=True, padx=12, pady=4)

        attach_wrap = ctk.CTkFrame(self.sidebar, fg_color=Theme.BG_PANEL, corner_radius=8)
        attach_wrap.pack(fill="x", padx=12, pady=(10, 14))
        self.attach_label = ctk.CTkLabel(
            attach_wrap, text="📎  Attachments: 0", font=self.font_label, text_color=Theme.PURPLE
        )
        self.attach_label.pack(pady=8, padx=10, anchor="w")

        # ---------- Terminal area ----------
        right = ctk.CTkFrame(main, fg_color="transparent")
        right.pack(side="right", fill="both", expand=True)

        terminal_wrap = ctk.CTkFrame(right, fg_color=Theme.BG_TERMINAL, corner_radius=0)
        terminal_wrap.pack(fill="both", expand=True, padx=0, pady=0)

        self.terminal = ctk.CTkTextbox(
            terminal_wrap, font=self.font_mono, fg_color=Theme.BG_TERMINAL, text_color=Theme.TEXT_BOT,
            wrap="word", corner_radius=0, border_width=0, activate_scrollbars=True,
            scrollbar_button_color=Theme.BORDER, scrollbar_button_hover_color=Theme.BLUE
        )
        self.terminal.pack(fill="both", expand=True, padx=18, pady=14)

        tb = self.terminal._textbox
        tb.configure(spacing1=2, spacing3=4, selectbackground=Theme.BLUE, selectforeground="#0a0b12")
        tb.tag_configure("right", justify="right")
        tb.tag_configure("user", foreground=Theme.BLUE, justify="right", font=(FONT_FAMILY_MONO, 13, "bold"))
        tb.tag_configure("bot", foreground=Theme.TEXT_BOT, justify="right")
        tb.tag_configure("system", foreground=Theme.TEXT_MUTED, justify="right")
        tb.tag_configure("error", foreground=Theme.RED, justify="right", font=(FONT_FAMILY_MONO, 13, "bold"))
        tb.tag_configure("prompt", foreground=Theme.ORANGE, justify="right", font=(FONT_FAMILY_MONO, 13, "bold"))
        tb.tag_configure("code", foreground=Theme.TEXT_CODE, background=Theme.BG_CODE, justify="left")
        tb.tag_configure("accent", foreground=Theme.PURPLE, justify="right")
        tb.tag_configure("success", foreground=Theme.GREEN_STRONG, justify="right", font=(FONT_FAMILY_MONO, 13, "bold"))
        tb.tag_configure("shell", foreground=Theme.ORANGE, background=Theme.BG_SHELL, justify="left")
        self.terminal.configure(state="disabled")

        # Input bar
        input_frame = ctk.CTkFrame(right, fg_color=Theme.BG_INPUTBAR, height=54, corner_radius=0)
        input_frame.pack(fill="x", side="bottom")
        input_frame.pack_propagate(False)

        top_line = ctk.CTkFrame(input_frame, fg_color=Theme.BORDER, height=1, corner_radius=0)
        top_line.place(relx=0, rely=0, relwidth=1, anchor="nw")

        self.cursor_label = ctk.CTkLabel(input_frame, text="▌", font=self.font_prompt, text_color=Theme.GREEN_STRONG, width=16)
        self.cursor_label.pack(side="right", padx=(2, 10), pady=10)
        ctk.CTkLabel(input_frame, text="❯", font=self.font_prompt, text_color=Theme.ORANGE, width=22).pack(side="right", padx=(4, 2), pady=10)

        self.entry = ctk.CTkEntry(
            input_frame, textvariable=self.input_var, font=self.font_mono,
            fg_color=Theme.BG_ENTRY, text_color=Theme.BLUE, border_width=1,
            border_color=Theme.BORDER, corner_radius=8,
            placeholder_text="پیام، دستور یا /attach فایل...",
            placeholder_text_color=Theme.TEXT_MUTED, justify="right"
        )
        self.entry.pack(side="right", fill="x", expand=True, padx=(12, 4), pady=10)
        self.entry.focus_set()

        # Status bar
        status_frame = ctk.CTkFrame(right, fg_color=Theme.BG_STATUSBAR, height=38, corner_radius=0)
        status_frame.pack(fill="x", side="bottom")
        status_frame.pack_propagate(False)

        status_top_line = ctk.CTkFrame(status_frame, fg_color=Theme.BORDER, height=1, corner_radius=0)
        status_top_line.place(relx=0, rely=0, relwidth=1, anchor="nw")

        self.btn_folder = ctk.CTkButton(
            status_frame, text="📁 Folder", width=96, height=24, font=self.font_small,
            corner_radius=6, fg_color=Theme.BTN_NEUTRAL, hover_color=Theme.BTN_NEUTRAL_H,
            text_color=Theme.TEXT_PRIMARY, command=self.select_folder
        )
        self.btn_folder.pack(side="left", padx=(10, 4), pady=6)

        self.btn_attach = ctk.CTkButton(
            status_frame, text="📎 Attach", width=96, height=24, font=self.font_small,
            corner_radius=6, fg_color=Theme.PURPLE, hover_color=Theme.PURPLE_HOVER,
            text_color="#1a0e2e", command=self.attach_file_dialog
        )
        self.btn_attach.pack(side="left", padx=4, pady=6)

        self.btn_thinking = ctk.CTkButton(
            status_frame, text="🧠 THINKING: ON", width=128, height=24, font=self.font_small,
            corner_radius=6, fg_color=Theme.GREEN_STRONG, hover_color=Theme.GREEN_HOVER,
            text_color="#0a1a10", command=self.toggle_thinking
        )
        self.btn_thinking.pack(side="left", padx=4, pady=6)

        self.btn_web = ctk.CTkButton(
            status_frame, text="🌐 WEB: OFF", width=104, height=24, font=self.font_small,
            corner_radius=6, fg_color=Theme.BTN_NEUTRAL, hover_color=Theme.BTN_NEUTRAL_H,
            text_color=Theme.TEXT_PRIMARY, command=self.toggle_web
        )
        self.btn_web.pack(side="left", padx=4, pady=6)

        self.status = ctk.CTkLabel(status_frame, text="", font=self.font_small, text_color=Theme.TEXT_MUTED, anchor="e")
        self.status.pack(side="right", padx=14)

    def _safe_clear_frame(self, frame):
        """پاک کردن امن فرزندان فریم (رفع TclError)"""
        try:
            for widget in frame.winfo_children():
                try:
                    widget.destroy()
                except Exception:
                    pass
            frame.update_idletasks()
        except Exception:
            pass

    def refresh_sidebar(self):
        if self._sidebar_refreshing:
            return
        self._sidebar_refreshing = True

        def _do():
            try:
                # Sessions
                self._safe_clear_frame(self.session_list)
                self.cursor.execute("SELECT id, title FROM sessions ORDER BY updated_at DESC LIMIT 20")
                for sid, title in self.cursor.fetchall():
                    is_current = sid == self.session_id
                    btn = ctk.CTkButton(
                        self.session_list,
                        text=f"{'●  ' if is_current else '　  '}[{sid}] {title[:20]}",
                        height=28, font=self.font_small, anchor="w", corner_radius=6,
                        fg_color=Theme.BLUE if is_current else "transparent",
                        text_color="#0a0e1a" if is_current else Theme.TEXT_PRIMARY,
                        hover_color=Theme.BG_HOVER,
                        command=lambda s=sid: self.load_session(s)
                    )
                    btn.pack(fill="x", pady=2, padx=2)

                # Files
                self._safe_clear_frame(self.file_list_frame)
                try:
                    items = sorted(os.listdir(self.current_dir))
                    for item in items[:80]:
                        full = os.path.join(self.current_dir, item)
                        is_dir = os.path.isdir(full)
                        prefix = "📁 " if is_dir else "📄 "
                        color = Theme.BLUE if is_dir else Theme.TEXT_PRIMARY
                        btn = ctk.CTkButton(
                            self.file_list_frame, text=f"{prefix}{item[:26]}",
                            height=26, font=self.font_small, anchor="w", corner_radius=6,
                            fg_color="transparent", hover_color=Theme.BG_HOVER, text_color=color,
                            command=lambda f=item, d=is_dir: self._sidebar_file_click(f, d)
                        )
                        btn.pack(fill="x", pady=1, padx=2)
                except Exception:
                    pass

                self.attach_label.configure(text=f"📎  Attachments: {len(self.attached_files)}")
            except Exception:
                pass
            finally:
                self._sidebar_refreshing = False

        self.after(30, _do)

    def _sidebar_file_click(self, name, is_dir):
        if is_dir:
            self.cmd_cd(name)
        else:
            self.cmd_cat(name)

    def select_folder(self):
        folder = filedialog.askdirectory(initialdir=self.current_dir)
        if folder:
            self.current_dir = folder
            self._refresh_file_list()
            self.write(f"📂 پوشه تغییر کرد → {self.current_dir}", "accent")
            self.update_status()
            self.after(50, self.refresh_sidebar)

    def attach_file_dialog(self):
        paths = filedialog.askopenfilenames(
            initialdir=self.current_dir,
            title="انتخاب فایل برای پیوست به AI",
            filetypes=[("All files", "*.*"), ("Python", "*.py"), ("Text", "*.txt"), ("Markdown", "*.md")]
        )
        for p in paths:
            if p not in self.attached_files:
                self.attached_files.append(p)
                self.write(f"📎 پیوست شد: {os.path.basename(p)}", "accent")
        self.attach_label.configure(text=f"📎  Attachments: {len(self.attached_files)}")
        self.update_status()

    def _refresh_file_list(self):
        try:
            self.file_list_cache = [
                f for f in os.listdir(self.current_dir)
                if os.path.isfile(os.path.join(self.current_dir, f))
            ]
        except Exception:
            self.file_list_cache = []

    def toggle_thinking(self):
        self.use_thinking = not self.use_thinking
        text = "🧠 THINKING: ON" if self.use_thinking else "🧠 THINKING: OFF"
        color = Theme.GREEN_STRONG if self.use_thinking else Theme.BTN_NEUTRAL
        text_color = "#0a1a10" if self.use_thinking else Theme.TEXT_PRIMARY
        self.btn_thinking.configure(text=text, fg_color=color, text_color=text_color)

    def toggle_web(self):
        self.use_web_search = not self.use_web_search
        text = "🌐 WEB: ON" if self.use_web_search else "🌐 WEB: OFF"
        color = Theme.BLUE if self.use_web_search else Theme.BTN_NEUTRAL
        text_color = "#0a0e1a" if self.use_web_search else Theme.TEXT_PRIMARY
        self.btn_web.configure(text=text, fg_color=color, text_color=text_color)

    def setup_bindings(self):
        self.entry.bind("<Return>", self.on_enter)
        self.entry.bind("<KeyRelease>", self.on_key_release)
        self.entry.bind("<Up>", self.history_prev)
        self.entry.bind("<Down>", self.history_next)
        self.bind("<Control-l>", lambda e: self.clear_screen())
        self.bind("<Control-c>", lambda e: self.input_var.set(""))
        self.bind("<Escape>", lambda e: self.destroy())

    def _blink_cursor(self):
        self._cursor_visible = not self._cursor_visible
        self.cursor_label.configure(text="▌" if self._cursor_visible else " ")
        self.after(530, self._blink_cursor)

    def update_status(self):
        sid = self.session_id or "-"
        dir_name = os.path.basename(self.current_dir) or self.current_dir
        if len(dir_name) > 18:
            dir_name = "…" + dir_name[-15:]
        attach_info = f"   📎 {len(self.attached_files)}" if self.attached_files else ""
        self.status.configure(text=f"Session {sid}   ·   {dir_name}{attach_info}")

    def history_prev(self, event=None):
        if not self.command_history:
            return
        if self.history_index == -1:
            self.history_index = len(self.command_history) - 1
        elif self.history_index > 0:
            self.history_index -= 1
        self.input_var.set(self.command_history[self.history_index])
        self.entry.icursor("end")

    def history_next(self, event=None):
        if not self.command_history or self.history_index == -1:
            return
        if self.history_index < len(self.command_history) - 1:
            self.history_index += 1
            self.input_var.set(self.command_history[self.history_index])
        else:
            self.history_index = -1
            self.input_var.set("")
        self.entry.icursor("end")

    def write(self, text, tag="system", end="\n"):
        def _do():
            try:
                self.terminal.configure(state="normal")
                fixed = fix_text(text)
                self.terminal._textbox.insert("end", fixed + end, (tag, "right"))
                self.terminal._textbox.see("end")
                self.terminal.configure(state="disabled")
            except Exception:
                pass
        self.after(0, _do)

    def write_stream(self, text, tag="bot"):
        def _do():
            try:
                self.terminal.configure(state="normal")
                self.terminal._textbox.insert("end", sanitize_text(text), (tag, "right"))
                self.terminal._textbox.see("end")
                self.terminal.configure(state="disabled")
            except Exception:
                pass
        self.after(0, _do)

    def print_welcome(self):
        lines = [
            "╔══════════════════════════════════════════════════════════╗",
            "║        DeepSeek Agent  ·  Terminal Pro  ·  v1.0          ║",
            "╚══════════════════════════════════════════════════════════╝",
            "",
            "برای شروع /help را بزنید.",
            ""
        ]
        for line in lines:
            self.write(line, "system")

    # ==================== دستورات ====================
    COMMANDS = [
        ("/help", "راهنما"),
        ("/clear", "پاک کردن صفحه"),
        ("/new", "سشن جدید"),
        ("/sessions", "لیست سشن‌ها"),
        ("/load <id>", "بارگذاری سشن"),
        ("/delete <id>", "حذف سشن"),
        ("/ls", "لیست فایل‌ها"),
        ("/tree", "نمایش درختی"),
        ("/search <kw>", "جستجو در فایل‌ها"),
        ("/cat <file>", "خواندن فایل"),
        ("/edit <file>", "ویرایش فایل"),
        ("/refactor <file>", "بهینه‌سازی با AI"),
        ("/write <file>", "نوشتن فایل جدید"),
        ("/run <file>", "اجرای پایتون"),
        ("/cd <path>", "تغییر مسیر"),
        ("/pwd", "مسیر فعلی"),
        ("/mkdir <name>", "ساخت پوشه"),
        ("/rm <file>", "حذف فایل/پوشه"),
        ("/mv <src> <dst>", "جابجایی/تغییر نام"),
        ("/cp <src> <dst>", "کپی"),
        ("/touch <file>", "ساخت فایل خالی"),
        ("/attach <file>", "پیوست فایل به AI"),
        ("/detach <file>", "حذف پیوست"),
        ("/clearattach", "پاک کردن همه پیوست‌ها"),
        ("/context", "بارگذاری همه فایل‌ها به context"),
        ("/openfolder", "انتخاب پوشه"),
        ("/exit", "خروج"),
    ]

    def on_key_release(self, event):
        text = self.input_var.get()
        if text.startswith("/") and len(text) < 18:
            self.show_command_popup(text)
        else:
            self.hide_command_popup()

    def show_command_popup(self, current):
        self.hide_command_popup()
        matches = [c for c in self.COMMANDS if current.lower() in c[0].lower()]
        if not matches:
            return

        self.command_popup = ctk.CTkToplevel(self)
        self.command_popup.overrideredirect(True)
        self.command_popup.configure(fg_color=Theme.BORDER)
        self.command_popup.attributes("-topmost", True)

        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() - (min(len(matches), 12) * 30 + 14)
        if y < 0:
            y = 10
        self.command_popup.geometry(f"460x{min(len(matches), 12) * 30 + 12}+{x}+{y}")

        border = ctk.CTkFrame(self.command_popup, fg_color=Theme.BG_PANEL, corner_radius=10)
        border.pack(fill="both", expand=True, padx=1, pady=1)

        for cmd, desc in matches[:12]:
            row = ctk.CTkButton(
                border, text=f"{fix_text(desc)}    ›  {cmd}",
                font=self.font_small, fg_color="transparent", hover_color=Theme.BG_HOVER,
                text_color=Theme.TEXT_PRIMARY, anchor="e", height=28, corner_radius=6,
                command=lambda c=cmd: self.select_command(c)
            )
            row.pack(fill="x", padx=4, pady=1)

    def select_command(self, cmd):
        base = cmd.split()[0]
        self.input_var.set(base + (" " if "<" in cmd else ""))
        self.hide_command_popup()
        self.entry.focus_set()
        self.entry.icursor("end")

    def hide_command_popup(self):
        if self.command_popup:
            try:
                if self.command_popup.winfo_exists():
                    self.command_popup.destroy()
            except Exception:
                pass
        self.command_popup = None

    def on_enter(self, event=None):
        self.hide_command_popup()
        cmd = self.input_var.get().strip()
        if not cmd or self.is_processing:
            return
        self.input_var.set("")
        self.command_history.append(cmd)
        self.history_index = -1

        self.write(f"{fix_text(cmd)} ❯", "prompt")
        self.save_message_to_db("user", cmd)
        self.handle_command(cmd)

    def handle_command(self, cmd):
        if not cmd.startswith("/"):
            self.send_to_agent(cmd)
            return

        parts = cmd.split(maxsplit=1)
        command = parts[0].lower()
        arg = parts[1] if len(parts) > 1 else ""

        handlers = {
            "/exit": lambda: self.destroy(),
            "/quit": lambda: self.destroy(),
            "/clear": self.clear_screen,
            "/help": self.show_help,
            "/new": lambda: self._create_new_session(arg or "گفتگوی جدید"),
            "/sessions": self.list_sessions,
            "/load": lambda: self.load_session(arg),
            "/delete": lambda: self.delete_session(arg),
            "/ls": lambda: self.cmd_ls(arg),
            "/tree": lambda: self.cmd_tree(arg),
            "/search": lambda: self.cmd_search(arg),
            "/cat": lambda: self.cmd_cat(arg),
            "/edit": lambda: self.cmd_edit(arg),
            "/refactor": lambda: self.cmd_refactor(arg),
            "/write": lambda: self.cmd_write(arg),
            "/run": lambda: self.cmd_run(arg),
            "/cd": lambda: self.cmd_cd(arg),
            "/pwd": lambda: self.write(self.current_dir, "bot"),
            "/openfolder": self.select_folder,
            "/context": self.cmd_context,
            "/attach": lambda: self.cmd_attach(arg),
            "/detach": lambda: self.cmd_detach(arg),
            "/clearattach": self.cmd_clear_attach,
            "/mkdir": lambda: self.cmd_mkdir(arg),
            "/rm": lambda: self.cmd_rm(arg),
            "/mv": lambda: self.cmd_mv(arg),
            "/cp": lambda: self.cmd_cp(arg),
            "/touch": lambda: self.cmd_touch(arg),
        }

        if command in handlers:
            handlers[command]()
        else:
            self.write("دستور ناشناخته — /help را ببینید", "error")

    def clear_screen(self):
        self.terminal.configure(state="normal")
        self.terminal._textbox.delete("1.0", "end")
        self.terminal.configure(state="disabled")
        self.print_welcome()

    def show_help(self):
        help_text = """
──────────── راهنما ────────────
سشن:
  /new [عنوان]          ساخت سشن جدید
  /sessions             لیست سشن‌ها
  /load <id>            بارگذاری سشن
  /delete <id>          حذف سشن

فایل:
  /ls [path]            لیست فایل‌ها
  /tree [path]          ساختار درختی
  /search <kw>          جستجوی متن
  /cat <file>           نمایش محتوا
  /edit <file>          ویرایش
  /write <file>         نوشتن فایل جدید
  /run <file.py>        اجرای پایتون
  /refactor <file>      بهینه‌سازی با AI
  /mkdir <name>         ساخت پوشه
  /rm <path>            حذف
  /mv <src> <dst>       جابجایی
  /cp <src> <dst>       کپی
  /touch <file>         ساخت فایل خالی
  /cd <path>            تغییر مسیر
  /pwd                  مسیر فعلی
  /openfolder           انتخاب پوشه

پیوست به AI:
  /attach <file>        پیوست فایل
  /detach <file>        حذف پیوست
  /clearattach          پاک کردن همه پیوست‌ها
  /context              بارگذاری همه فایل‌های متنی

سایر:
  /clear                پاک کردن صفحه
  /exit                 خروج
"""
        self.write(help_text, "system")

    # ---------- دستورات فایل ----------
    def cmd_ls(self, path=""):
        target = os.path.join(self.current_dir, path) if path else self.current_dir
        try:
            items = sorted(os.listdir(target))
            if not items:
                self.write("(خالی است)", "system")
                return
            for item in items:
                full = os.path.join(target, item)
                is_dir = os.path.isdir(full)
                prefix = "📁 " if is_dir else "📄 "
                size = ""
                if not is_dir:
                    try:
                        s = os.path.getsize(full)
                        if s >= 1024 * 1024:
                            size = f" ({s // 1024 // 1024} MB)"
                        elif s >= 1024:
                            size = f" ({s // 1024} KB)"
                        else:
                            size = f" ({s} B)"
                    except Exception:
                        pass
                color = "accent" if is_dir else "bot"
                self.write(f"{prefix}{item}{size}", color)
        except Exception as e:
            self.write(f"خطا: {e}", "error")

    def cmd_tree(self, path=""):
        target = os.path.join(self.current_dir, path) if path else self.current_dir
        try:
            self.write(f"📂 Structure of: {os.path.basename(target) or target}", "accent")
            for root, dirs, files in os.walk(target):
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
                level = root.replace(target, "").count(os.sep)
                indent = "│   " * level
                self.write(f"{indent}📁 {os.path.basename(root)}/", "accent")
                sub = "│   " * (level + 1)
                for f in sorted(files):
                    if any(f.endswith(ext) for ext in IGNORE_EXTS):
                        continue
                    self.write(f"{sub}📄 {f}", "bot")
        except Exception as e:
            self.write(f"خطا: {e}", "error")

    def cmd_search(self, keyword):
        if not keyword:
            self.write("استفاده: /search <keyword>", "error")
            return
        self.write(f"🔍 Searching for '{keyword}' ...", "system")
        found = False
        try:
            for root, dirs, files in os.walk(self.current_dir):
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
                for f in files:
                    if not f.endswith((".py", ".js", ".ts", ".txt", ".md", ".html", ".css", ".json", ".yml", ".yaml", ".toml")):
                        continue
                    path = os.path.join(root, f)
                    try:
                        with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                            for i, line in enumerate(fh, 1):
                                if keyword.lower() in line.lower():
                                    rel = os.path.relpath(path, self.current_dir)
                                    self.write(f"📄 {rel}:{i} → {line.strip()[:120]}", "code")
                                    found = True
                    except Exception:
                        pass
            if not found:
                self.write("هیچ موردی یافت نشد.", "system")
        except Exception as e:
            self.write(f"خطا در جستجو: {e}", "error")

    def cmd_run(self, filename):
        if not filename:
            self.write("استفاده: /run <file.py>", "error")
            return
        path = os.path.join(self.current_dir, filename)
        if not os.path.exists(path):
            self.write("فایل وجود ندارد.", "error")
            return
        if not filename.endswith(".py"):
            self.write("فقط فایل‌های .py قابل اجرا هستند.", "error")
            return
        self.write(f"▶️ Running {filename} ...", "accent")
        try:
            result = subprocess.run(
                [sys.executable, path],
                capture_output=True, text=True, timeout=15, cwd=self.current_dir
            )
            if result.stdout:
                self.write(result.stdout, "code")
            if result.stderr:
                self.write(result.stderr, "error")
            if result.returncode == 0 and not result.stdout:
                self.write("(بدون خروجی)", "system")
        except subprocess.TimeoutExpired:
            self.write("⏱️ Timeout (۱۵ ثانیه)", "error")
        except Exception as e:
            self.write(f"خطا در اجرا: {e}", "error")

    def cmd_cat(self, filename):
        if not filename:
            self.write("استفاده: /cat <file>", "error")
            return
        path = os.path.join(self.current_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
            self.write(f"── {filename} ──", "system")
            self.write(content, "code")
        except Exception as e:
            self.write(f"خطا: {e}", "error")

    def cmd_edit(self, filename):
        if not filename:
            self.write("استفاده: /edit <file>", "error")
            return
        path = os.path.join(self.current_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            content = ""

        dialog = ctk.CTkToplevel(self)
        dialog.title(f"Editing: {filename}")
        dialog.geometry("740x500")
        dialog.configure(fg_color=Theme.BG_APP)
        dialog.transient(self)

        header = ctk.CTkLabel(
            dialog, text=f"✎  {filename}", font=self.font_heading, text_color=Theme.BLUE
        )
        header.pack(anchor="w", padx=16, pady=(14, 4))

        text_widget = ctk.CTkTextbox(
            dialog, font=self.font_mono, fg_color=Theme.BG_TERMINAL, text_color=Theme.TEXT_BOT,
            corner_radius=8, border_width=1, border_color=Theme.BORDER
        )
        text_widget.pack(fill="both", expand=True, padx=16, pady=8)
        text_widget.insert("1.0", content)

        def save():
            try:
                with open(path, "w", encoding="utf-8") as f:
                    f.write(text_widget.get("1.0", "end-1c"))
                self.write(f"✅ Saved {filename}", "success")
                self._refresh_file_list()
                self.after(50, self.refresh_sidebar)
                dialog.destroy()
            except Exception as e:
                self.write(f"Save Error: {e}", "error")

        fr = ctk.CTkFrame(dialog, fg_color="transparent")
        fr.pack(fill="x", pady=12, padx=16)
        ctk.CTkButton(
            fr, text="💾  Save", width=110, height=32, corner_radius=8, font=self.font_label,
            fg_color=Theme.GREEN_STRONG, hover_color=Theme.GREEN_HOVER, text_color="#0a1a10", command=save
        ).pack(side="right", padx=6)
        ctk.CTkButton(
            fr, text="✕  Cancel", width=100, height=32, corner_radius=8, font=self.font_label,
            fg_color=Theme.RED, hover_color=Theme.RED_HOVER, text_color="#2a0a10", command=dialog.destroy
        ).pack(side="right")

    def cmd_refactor(self, filename):
        if not filename:
            self.write("استفاده: /refactor <file>", "error")
            return
        path = os.path.join(self.current_dir, filename)
        if not os.path.exists(path):
            self.write("فایل وجود ندارد.", "error")
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                code_content = f.read()
        except Exception as e:
            self.write(f"خطا در خواندن: {e}", "error")
            return

        self.write(f"🤖 در حال تحلیل و بهینه‌سازی {filename} ...", "accent")
        prompt = f"""Please refactor the following code to be cleaner, more efficient, and follow best practices.
Keep the same functionality. Return ONLY the refactored code inside a single markdown code block.

File: {filename}
Code:
{code_content}
"""
        threading.Thread(target=self._process_refactor, args=(prompt, filename), daemon=True).start()

    def _process_refactor(self, prompt, original_filename):
        try:
            full_response = ""
            stream = self.api.chat_completion(
                self.chat_id, prompt,
                thinking_enabled=False, search_enabled=False
            )
            for chunk in stream:
                if chunk.get("type") == "text":
                    content = chunk.get("content", "")
                    if content:
                        full_response += content

            pattern = r"```(?:\w+\n)?(.*?)```"
            matches = re.findall(pattern, full_response, re.DOTALL)
            new_code = None
            if matches:
                new_code = matches[0].strip()
            else:
                lines = full_response.split("\n")
                code_lines = []
                skip = True
                for line in lines:
                    if skip and (line.strip().startswith(("import", "from", "class", "def", "#"))):
                        skip = False
                    if not skip:
                        code_lines.append(line)
                new_code = "\n".join(code_lines).strip() if code_lines else full_response.strip()

            if new_code:
                new_code = new_code.strip("`").strip()
                lines = new_code.splitlines()
                if lines and lines[0].strip().startswith("```"):
                    lines.pop(0)
                if lines and lines[-1].strip() == "```":
                    lines.pop()
                new_code = "\n".join(lines).strip()

            if new_code and len(new_code) > 10:
                # اگر bash/shell باشد فقط نمایش بده
                lower_name = original_filename.lower()
                if any(x in lower_name for x in (".sh", ".bash", ".cmd", ".bat", ".ps1")):
                    self.after(0, lambda: self.write("── Refactored Shell Script ──", "system"))
                    self.after(0, lambda: self.write(new_code, "shell"))
                else:
                    new_path = os.path.join(self.current_dir, original_filename)
                    with open(new_path, "w", encoding="utf-8") as f:
                        f.write(new_code)
                    self.after(0, lambda: self.write(f"✅ فایل بهینه شده ذخیره شد: {original_filename}", "success"))
                    self.after(0, self._refresh_file_list)
                    self.after(50, self.refresh_sidebar)
            else:
                self.after(0, lambda: self.write("❌ کد معتبری یافت نشد.", "error"))
        except Exception as e:
            self.after(0, lambda: self.write(f"خطا در Refactor: {e}", "error"))

    def cmd_write(self, filename):
        if not filename:
            self.write("استفاده: /write <file>", "error")
            return
        content = self._ask_multiline(f"محتوای فایل {filename}")
        if content is None:
            return
        path = os.path.join(self.current_dir, filename)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            self._refresh_file_list()
            self.after(50, self.refresh_sidebar)
            self.write(f"✅ ذخیره شد → {filename}", "bot")
        except Exception as e:
            self.write(f"خطا: {e}", "error")

    def cmd_cd(self, path):
        if not path:
            self.write("استفاده: /cd <path>", "error")
            return
        new_path = os.path.abspath(os.path.join(self.current_dir, path))
        if os.path.isdir(new_path):
            self.current_dir = new_path
            self._refresh_file_list()
            self.write(f"→ {self.current_dir}", "bot")
            self.update_status()
            self.after(50, self.refresh_sidebar)
        else:
            self.write("مسیر وجود ندارد", "error")

    def cmd_mkdir(self, name):
        if not name:
            self.write("استفاده: /mkdir <name>", "error")
            return
        path = os.path.join(self.current_dir, name)
        try:
            os.makedirs(path, exist_ok=True)
            self.write(f"✅ پوشه ساخته شد: {name}", "success")
            self.after(50, self.refresh_sidebar)
        except Exception as e:
            self.write(f"خطا: {e}", "error")

    def cmd_rm(self, path):
        if not path:
            self.write("استفاده: /rm <file|dir>", "error")
            return
        full = os.path.join(self.current_dir, path)
        try:
            if os.path.isdir(full):
                shutil.rmtree(full)
            else:
                os.remove(full)
            self.write(f"✅ حذف شد: {path}", "success")
            self._refresh_file_list()
            self.after(50, self.refresh_sidebar)
        except Exception as e:
            self.write(f"خطا: {e}", "error")

    def cmd_mv(self, arg):
        parts = arg.split(maxsplit=1)
        if len(parts) != 2:
            self.write("استفاده: /mv <src> <dst>", "error")
            return
        src = os.path.join(self.current_dir, parts[0])
        dst = os.path.join(self.current_dir, parts[1])
        try:
            shutil.move(src, dst)
            self.write(f"✅ جابجا شد: {parts[0]} → {parts[1]}", "success")
            self._refresh_file_list()
            self.after(50, self.refresh_sidebar)
        except Exception as e:
            self.write(f"خطا: {e}", "error")

    def cmd_cp(self, arg):
        parts = arg.split(maxsplit=1)
        if len(parts) != 2:
            self.write("استفاده: /cp <src> <dst>", "error")
            return
        src = os.path.join(self.current_dir, parts[0])
        dst = os.path.join(self.current_dir, parts[1])
        try:
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                shutil.copy2(src, dst)
            self.write(f"✅ کپی شد: {parts[0]} → {parts[1]}", "success")
            self._refresh_file_list()
            self.after(50, self.refresh_sidebar)
        except Exception as e:
            self.write(f"خطا: {e}", "error")

    def cmd_touch(self, filename):
        if not filename:
            self.write("استفاده: /touch <file>", "error")
            return
        path = os.path.join(self.current_dir, filename)
        try:
            open(path, "a").close()
            self.write(f"✅ فایل ساخته شد: {filename}", "success")
            self._refresh_file_list()
            self.after(50, self.refresh_sidebar)
        except Exception as e:
            self.write(f"خطا: {e}", "error")

    # ---------- Attach system ----------
    def cmd_attach(self, filename):
        if not filename:
            self.write("استفاده: /attach <file>   یا از دکمه 📎 Attach استفاده کنید", "error")
            return
        path = os.path.join(self.current_dir, filename)
        if not os.path.isfile(path):
            self.write("فایل یافت نشد.", "error")
            return
        if path not in self.attached_files:
            self.attached_files.append(path)
            self.write(f"📎 پیوست شد: {filename}", "accent")
        else:
            self.write("این فایل قبلاً پیوست شده.", "system")
        self.attach_label.configure(text=f"📎  Attachments: {len(self.attached_files)}")
        self.update_status()

    def cmd_detach(self, filename):
        if not filename:
            self.write("استفاده: /detach <file>", "error")
            return
        path = os.path.join(self.current_dir, filename)
        if path in self.attached_files:
            self.attached_files.remove(path)
            self.write(f"🗑 پیوست حذف شد: {filename}", "system")
        else:
            for p in list(self.attached_files):
                if os.path.basename(p) == filename:
                    self.attached_files.remove(p)
                    self.write(f"🗑 پیوست حذف شد: {filename}", "system")
                    break
            else:
                self.write("این فایل در لیست پیوست نیست.", "error")
        self.attach_label.configure(text=f"📎  Attachments: {len(self.attached_files)}")
        self.update_status()

    def cmd_clear_attach(self):
        self.attached_files.clear()
        self.write("🗑 همه پیوست‌ها پاک شدند.", "system")
        self.attach_label.configure(text="📎  Attachments: 0")
        self.update_status()

    def cmd_context(self):
        context = "📂 **فایل‌های موجود در پوشه:**\n\n"
        try:
            count = 0
            for f in os.listdir(self.current_dir):
                full = os.path.join(self.current_dir, f)
                if os.path.isfile(full) and f.endswith((".py", ".js", ".ts", ".txt", ".md", ".html", ".css", ".json")):
                    try:
                        with open(full, "r", encoding="utf-8", errors="ignore") as fh:
                            context += f"--- File: {f} ---\n{fh.read()}\n\n"
                        count += 1
                    except Exception:
                        pass
            self.temp_context = context
            self.write(f"✅ {count} فایل به context موقت اضافه شد.", "accent")
        except Exception as e:
            self.write(f"خطا: {e}", "error")

    def _ask_multiline(self, title):
        dialog = ctk.CTkToplevel(self)
        dialog.title(title)
        dialog.geometry("640x440")
        dialog.configure(fg_color=Theme.BG_APP)
        dialog.transient(self)
        dialog.grab_set()

        ctk.CTkLabel(
            dialog, text=f"✎  {title}", font=self.font_heading, text_color=Theme.BLUE
        ).pack(anchor="w", padx=16, pady=(14, 4))

        text_widget = ctk.CTkTextbox(
            dialog, font=self.font_mono, fg_color=Theme.BG_TERMINAL, text_color=Theme.TEXT_BOT,
            corner_radius=8, border_width=1, border_color=Theme.BORDER
        )
        text_widget.pack(fill="both", expand=True, padx=16, pady=8)

        result = {"value": None}

        def ok():
            result["value"] = text_widget.get("1.0", "end-1c")
            dialog.destroy()

        def cancel():
            dialog.destroy()

        fr = ctk.CTkFrame(dialog, fg_color="transparent")
        fr.pack(fill="x", pady=12, padx=16)
        ctk.CTkButton(
            fr, text="💾  ذخیره", width=110, height=32, corner_radius=8, font=self.font_label,
            fg_color=Theme.GREEN_STRONG, hover_color=Theme.GREEN_HOVER, text_color="#0a1a10", command=ok
        ).pack(side="right", padx=6)
        ctk.CTkButton(
            fr, text="✕  لغو", width=100, height=32, corner_radius=8, font=self.font_label,
            fg_color=Theme.RED, hover_color=Theme.RED_HOVER, text_color="#2a0a10", command=cancel
        ).pack(side="right")

        self.wait_window(dialog)
        return result["value"]

    # ==================== ذخیره کد هوشمند ====================
    def _lang_to_ext(self, lang):
        mapping = {
            "python": ".py", "py": ".py", "javascript": ".js", "js": ".js",
            "typescript": ".ts", "ts": ".ts", "html": ".html", "css": ".css",
            "java": ".java", "c": ".c", "cpp": ".cpp", "go": ".go",
            "rust": ".rs", "php": ".php", "bash": ".sh", "sh": ".sh",
            "shell": ".sh", "sql": ".sql", "json": ".json", "md": ".md",
            "yaml": ".yml", "toml": ".toml", "powershell": ".ps1", "ps1": ".ps1",
            "bat": ".bat", "cmd": ".cmd"
        }
        return mapping.get(lang.lower().strip(), ".txt")

    def _extract_suggested_filename(self, lang, code):
        """استخراج هوشمند اسم فایل از ابتدای کد (مثل خروجی هوش مصنوعی)"""
        if not code:
            return None

        # چند خط اول کد را بررسی می‌کنیم
        first_lines = "\n".join(code.strip().splitlines()[:6])

        patterns = [
            # <!-- index.html -->
            r"<!--\s*([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)\s*-->",
            
            # /* style.css */  یا  /* filename: style.css */
            r"/\*\s*(?:filename\s*[:=]\s*)?([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)\s*\*/",
            
            # // script.js  یا  // filename: script.js
            r"//\s*(?:filename\s*[:=]\s*)?([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)",
            
            # # main.py  یا  # filename: main.py
            r"#\s*(?:filename\s*[:=]\s*)?([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)",
            
            # -- query.sql
            r"--\s*(?:filename\s*[:=]\s*)?([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)",
            
            # فایل: index.html   یا  File: index.html
            r"(?:فایل|file|filename)\s*[:=]\s*([a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+)",
        ]

        for pat in patterns:
            m = re.search(pat, first_lines, re.IGNORECASE)
            if m:
                name = m.group(1).strip()
                # فقط اسم‌های معتبر
                if re.match(r"^[a-zA-Z0-9_\-\.]+\.[a-zA-Z0-9]+$", name):
                    return name

        return None


    def _save_code_block(self, lang, code):
        lang = (lang or "text").lower().strip()

        # bash / shell / cmd را ذخیره نکن
        if lang in NO_SAVE_LANGS:
            self.write("── Shell / Bash Script ──", "system")
            self.write(code, "shell")
            return

        # اول سعی کن اسم را از داخل کد استخراج کنی
        suggested = self._extract_suggested_filename(lang, code)

        if suggested:
            filename = suggested
        else:
            # اگر اسم پیدا نشد، از زبان + شمارنده استفاده کن
            ext = self._lang_to_ext(lang)
            filename = f"{lang}_{self.auto_code_counter}{ext}"
            self.auto_code_counter += 1

        # جلوگیری از بازنویسی فایل موجود
        base, ext = os.path.splitext(filename)
        counter = 1
        final_name = filename
        while os.path.exists(os.path.join(self.current_dir, final_name)):
            final_name = f"{base}_{counter}{ext}"
            counter += 1

        path = os.path.join(self.current_dir, final_name)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(code)
            self._refresh_file_list()
            self.after(50, self.refresh_sidebar)
            self.write(f"💾 ذخیره شد → {final_name}", "accent")
        except Exception as e:
            self.write(f"خطا در ذخیره‌سازی: {e}", "error")

    def extract_and_save_codes(self, text):
        # پشتیبانی از ```lang و ```lang:filename
        pattern = r"```(\w*)(?::([^\n]+))?\n(.*?)```"
        matches = re.findall(pattern, text, re.DOTALL)
        for lang, maybe_name, code in matches:
            code = code.strip()
            if len(code) < 8:
                continue
            if maybe_name and maybe_name.strip():
                # اگر اسم فایل داخل بلاک آمده باشد
                filename = maybe_name.strip()
                path = os.path.join(self.current_dir, filename)
                try:
                    with open(path, "w", encoding="utf-8") as f:
                        f.write(code)
                    self._refresh_file_list()
                    self.after(50, self.refresh_sidebar)
                    self.write(f"💾 ذخیره شد → {filename}", "accent")
                except Exception as e:
                    self.write(f"خطا: {e}", "error")
            else:
                self._save_code_block(lang or "text", code)

    # ==================== ارسال به AI ====================
    def send_to_agent(self, question):
        if not self.chat_id:
            self.write("خطا: chat_id موجود نیست!", "error")
            return

        self.is_processing = True
        self.entry.configure(state="disabled")
        self.write("⏳ در حال فکر کردن...", "system")

        threading.Thread(target=self._get_response, args=(question,), daemon=True).start()

    def _get_response(self, question):
        try:
            full_response = ""
            thinking_removed = False

            final_question = question

            # فایل‌های attach شده
            if self.attached_files:
                attach_block = "\n\n========== ATTACHED FILES ==========\n"
                for path in self.attached_files:
                    try:
                        with open(path, "r", encoding="utf-8", errors="ignore") as f:
                            content = f.read()
                        name = os.path.basename(path)
                        attach_block += f"\n--- File: {name} ---\n{content}\n"
                    except Exception as e:
                        attach_block += f"\n--- File: {os.path.basename(path)} (error: {e}) ---\n"
                attach_block += "\n====================================\n\n"
                final_question = attach_block + final_question

            if self.temp_context:
                final_question = self.temp_context + "\n\nUser Question: " + final_question
                self.temp_context = None

            kwargs = {
                "thinking_enabled": self.use_thinking,
                "search_enabled": self.use_web_search
            }
            if self.parent_message_id > 0:
                kwargs["parent_message_id"] = self.parent_message_id

            stream = self.api.chat_completion(self.chat_id, final_question, **kwargs)

            for chunk in stream:
                if chunk.get("type") == "text":
                    content = chunk.get("content", "")
                    if content:
                        if not thinking_removed:
                            self.after(0, self._remove_thinking)
                            thinking_removed = True
                        full_response += content
                        self.write_stream(content, "bot")

            if not thinking_removed:
                self.after(0, self._remove_thinking)

            if full_response:
                self.write("", "bot")
                self.extract_and_save_codes(full_response)
                self.bump_parent_message_id()
                self.save_message_to_db("bot", full_response)
                self.after(0, self.update_status)
            else:
                self.write("پاسخ خالی دریافت شد", "error")

        except Exception as e:
            self.after(0, self._remove_thinking)
            self.write(f"خطا: {str(e)[:200]}", "error")

        self.is_processing = False
        self.after(0, lambda: self.entry.configure(state="normal"))
        self.after(0, lambda: self.entry.focus_set())

    def _remove_thinking(self):
        try:
            self.terminal.configure(state="normal")
            self.terminal._textbox.delete("end-1l", "end")
            self.terminal.configure(state="disabled")
        except Exception:
            pass


def main():
    if TOKEN in ("token", "YOUR_DEEPSEEK_TOKEN_HERE", "YOUR_AUTH_TOKEN_HERE", ""):
        print("⚠️  لطفاً توکن DeepSeek را در متغیر TOKEN قرار دهید")
        return

    app = DeepSeekCLI()
    app.mainloop()


if __name__ == "__main__":
    main()