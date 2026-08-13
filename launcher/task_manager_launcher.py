"""A small Windows GUI for starting the local Task Manager server."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from pathlib import Path
from tkinter import filedialog, messagebox


APP_URL = "http://localhost:8000"
WINDOWS_NO_CONSOLE = getattr(subprocess, "CREATE_NO_WINDOW", 0)
BG = "#0a1020"
PANEL = "#151e35"
PANEL_ALT = "#10182b"
TEXT = "#edf3ff"
MUTED = "#96a6c9"
ACCENT = "#78aaff"
SUCCESS = "#58d6a1"
TUNNEL_STATUS_FILE = Path(os.getenv("TASK_MANAGER_DATA_DIR", "D:/TaskManagerData")) / "cloudflare-tunnel.json"
WEBVIEW_STORAGE = Path(os.getenv("TASK_MANAGER_DATA_DIR", "D:/TaskManagerData")) / "desktop-webview"
AI_SETTINGS_FILE = Path(os.getenv("TASK_MANAGER_DATA_DIR", "D:/TaskManagerData")) / "ai-settings.json"
DEFAULT_AI_MODELS_DIR = Path(os.getenv("TASK_MANAGER_DATA_DIR", "D:/TaskManagerData")) / "OllamaModels"
OLLAMA_MODELS = {
    "qwen3:0.6b": "Экономный — Qwen3 0.6B (для очень слабого ПК)",
    "qwen3:1.7b": "Рекомендуемый — Qwen3 1.7B (голосовые команды и задачи)",
    "qwen3:4b": "Улучшенный — Qwen3 4B (нужен более мощный ПК)",
}


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        # Installed builds keep the launcher beside docker-compose.yml.
        installed_root = Path(sys.executable).resolve().parent
        return installed_root if (installed_root / "docker-compose.yml").exists() else installed_root.parent
    return Path(__file__).resolve().parent.parent


def docker_executable() -> str | None:
    candidates = [
        Path("D:/DevTools/Docker/resources/bin/docker.exe"),
        Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / "docker.exe"
        if candidate.exists():
            return str(candidate)
    return None


def cloudflared_executable() -> str | None:
    for candidate in (Path("D:/DevTools/cloudflared/cloudflared.exe"), Path("C:/Program Files (x86)/cloudflared/cloudflared.exe")):
        if candidate.exists():
            return str(candidate)
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / "cloudflared.exe"
        if candidate.exists():
            return str(candidate)
    return None


def ollama_executable() -> str | None:
    candidates = [
        Path("D:/DevTools/Ollama/ollama.exe"),
        Path(os.environ.get("LOCALAPPDATA", "")) / "Programs" / "Ollama" / "ollama.exe",
        Path("C:/Program Files/Ollama/ollama.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    for folder in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(folder) / "ollama.exe"
        if candidate.exists():
            return str(candidate)
    return None


class DesktopServerApi:
    """Methods exposed only to the local desktop WebView."""

    tunnel_process: subprocess.Popen[str] | None = None
    tunnel_url: str | None = None
    ai_installing = False
    ai_selected_model: str | None = None
    ai_install_error: str | None = None
    ai_progress = 0
    ai_stage = ""

    @staticmethod
    def ai_models_dir() -> Path:
        try:
            configured = json.loads(AI_SETTINGS_FILE.read_text(encoding="utf-8")).get("models_dir")
            if configured:
                return Path(configured)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            pass
        return DEFAULT_AI_MODELS_DIR

    @staticmethod
    def save_ai_models_dir(folder: Path) -> None:
        AI_SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
        AI_SETTINGS_FILE.write_text(json.dumps({"models_dir": str(folder)}), encoding="utf-8")

    @staticmethod
    def choose_ai_models_folder() -> dict[str, object]:
        selected = filedialog.askdirectory(initialdir=str(DesktopServerApi.ai_models_dir()), title="Папка для моделей локального ИИ")
        if not selected:
            return {"ok": False, "message": "Folder selection cancelled"}
        folder = Path(selected).resolve()
        folder.mkdir(parents=True, exist_ok=True)
        DesktopServerApi.save_ai_models_dir(folder)
        return {"ok": True, "folder": str(folder)}

    @staticmethod
    def _saved_tunnel() -> dict[str, object] | None:
        try:
            data = json.loads(TUNNEL_STATUS_FILE.read_text(encoding="utf-8"))
            os.kill(int(data["pid"]), 0)
            return data
        except (OSError, ValueError, KeyError, json.JSONDecodeError, FileNotFoundError):
            TUNNEL_STATUS_FILE.unlink(missing_ok=True)
            return None

    @staticmethod
    def _save_tunnel(process: subprocess.Popen[str], url: str) -> None:
        TUNNEL_STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TUNNEL_STATUS_FILE.write_text(json.dumps({"pid": process.pid, "url": url}), encoding="utf-8")

    @staticmethod
    def _read_tunnel_output(process: subprocess.Popen[str]) -> None:
        if process.stdout is None:
            return
        for line in process.stdout:
            match = re.search(r"https://[-a-z0-9]+\.trycloudflare\.com", line, re.I)
            if match:
                DesktopServerApi.tunnel_url = match.group(0)
                DesktopServerApi._save_tunnel(process, DesktopServerApi.tunnel_url)
                return

    @staticmethod
    def server_status() -> dict[str, bool]:
        return {"running": Launcher.server_is_ready()}

    @staticmethod
    def start_server() -> dict[str, object]:
        return DesktopServerApi._run_compose("up")

    @staticmethod
    def stop_server() -> dict[str, object]:
        return DesktopServerApi._run_compose("down")

    @staticmethod
    def tunnel_status() -> dict[str, object]:
        process = DesktopServerApi.tunnel_process
        running = process is not None and process.poll() is None
        if running:
            return {"available": cloudflared_executable() is not None, "running": True, "url": DesktopServerApi.tunnel_url}
        saved = DesktopServerApi._saved_tunnel()
        return {"available": cloudflared_executable() is not None, "running": saved is not None, "url": saved.get("url") if saved else None}

    @staticmethod
    def start_tunnel() -> dict[str, object]:
        existing = DesktopServerApi.tunnel_status()
        if existing["running"]:
            return {"ok": True, **existing}
        executable = cloudflared_executable()
        if executable is None:
            return {"ok": False, "message": "Cloudflare Tunnel is not installed yet"}
        if not Launcher.server_is_ready():
            return {"ok": False, "message": "Start the server first"}
        try:
            process = subprocess.Popen([executable, "tunnel", "--url", APP_URL], stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, creationflags=WINDOWS_NO_CONSOLE)
            DesktopServerApi.tunnel_process = process
            DesktopServerApi.tunnel_url = None
            threading.Thread(target=DesktopServerApi._read_tunnel_output, args=(process,), daemon=True).start()
            return {"ok": True, "running": True, "url": None, "message": "Cloudflare Tunnel is starting"}
        except OSError:
            return {"ok": False, "message": "Cloudflare Tunnel could not be started"}

    @staticmethod
    def stop_tunnel() -> dict[str, object]:
        process = DesktopServerApi.tunnel_process
        if process is not None and process.poll() is None:
            process.terminate()
        else:
            saved = DesktopServerApi._saved_tunnel()
            if saved:
                subprocess.run(["taskkill", "/PID", str(saved["pid"]), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=WINDOWS_NO_CONSOLE)
        DesktopServerApi.tunnel_process = None
        DesktopServerApi.tunnel_url = None
        TUNNEL_STATUS_FILE.unlink(missing_ok=True)
        return {"ok": True, "running": False}

    @staticmethod
    def ai_status() -> dict[str, object]:
        executable = ollama_executable()
        models: list[str] = []
        if executable:
            try:
                result = subprocess.run([executable, "list"], capture_output=True, text=True, timeout=8, creationflags=WINDOWS_NO_CONSOLE)
                models = [line.split()[0] for line in result.stdout.splitlines()[1:] if line.strip()]
            except (OSError, subprocess.SubprocessError):
                pass
        return {
            "available": executable is not None,
            "models": models,
            "installing": DesktopServerApi.ai_installing,
            "selected_model": DesktopServerApi.ai_selected_model,
            "error": DesktopServerApi.ai_install_error,
            "progress": DesktopServerApi.ai_progress,
            "stage": DesktopServerApi.ai_stage,
            "models_dir": str(DesktopServerApi.ai_models_dir()),
        }

    @staticmethod
    def install_ai_model(model: str, models_dir: str | None = None) -> dict[str, object]:
        if model not in OLLAMA_MODELS:
            return {"ok": False, "message": "Unknown AI model"}
        if DesktopServerApi.ai_installing:
            return {"ok": False, "message": "Installation is already running"}

        try:
            models_folder = Path(models_dir).expanduser().resolve() if models_dir else DesktopServerApi.ai_models_dir()
            models_folder.mkdir(parents=True, exist_ok=True)
            DesktopServerApi.save_ai_models_dir(models_folder)
        except OSError:
            return {"ok": False, "message": "The selected folder is unavailable"}

        def install() -> None:
            DesktopServerApi.ai_installing = True
            DesktopServerApi.ai_selected_model = model
            DesktopServerApi.ai_install_error = None
            DesktopServerApi.ai_progress = 1
            DesktopServerApi.ai_stage = "Устанавливаю локальный ИИ-движок…"
            try:
                executable = ollama_executable()
                if executable is None:
                    subprocess.run(["winget", "install", "--id", "Ollama.Ollama", "-e", "--accept-package-agreements", "--accept-source-agreements"], check=True, creationflags=WINDOWS_NO_CONSOLE)
                    for _ in range(30):
                        executable = ollama_executable()
                        if executable:
                            break
                        time.sleep(1)
                if executable is None:
                    raise RuntimeError("Ollama installation did not finish")
                # Models are the large part. Persist the location and run the
                # local service with the same setting so C: stays mostly free.
                os.environ["OLLAMA_MODELS"] = str(models_folder)
                subprocess.run(["setx", "OLLAMA_MODELS", str(models_folder)], check=False, creationflags=WINDOWS_NO_CONSOLE)
                subprocess.run(["taskkill", "/IM", "ollama.exe", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=WINDOWS_NO_CONSOLE)
                serve_env = os.environ.copy()
                serve_env["OLLAMA_MODELS"] = str(models_folder)
                subprocess.Popen([executable, "serve"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, env=serve_env, creationflags=WINDOWS_NO_CONSOLE)
                time.sleep(2)
                DesktopServerApi.ai_progress = 5
                DesktopServerApi.ai_stage = "Скачиваю выбранную модель…"
                process = subprocess.Popen(
                    [executable, "pull", model],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    creationflags=WINDOWS_NO_CONSOLE,
                )
                if process.stdout is not None:
                    for line in process.stdout:
                        percentage = re.search(r"(\d{1,3})%", line)
                        if percentage:
                            DesktopServerApi.ai_progress = max(5, min(99, int(percentage.group(1))))
                        DesktopServerApi.ai_stage = line.strip() or "Скачиваю выбранную модель…"
                if process.wait() != 0:
                    raise RuntimeError("Model download failed")
                DesktopServerApi.ai_progress = 100
                DesktopServerApi.ai_stage = "Модель установлена и готова."
            except (OSError, subprocess.SubprocessError, RuntimeError) as error:
                DesktopServerApi.ai_install_error = str(error)
                DesktopServerApi.ai_stage = "Не удалось завершить установку."
            finally:
                DesktopServerApi.ai_installing = False

        threading.Thread(target=install, daemon=True).start()
        return {"ok": True, "message": "Downloading model"}

    @staticmethod
    def _run_compose(command: str) -> dict[str, object]:
        docker = docker_executable()
        if docker is None:
            return {"ok": False, "message": "Docker Desktop is not available"}
        try:
            args = ["up", "--build", "--detach"] if command == "up" else ["down"]
            subprocess.run([docker, "compose", *args], cwd=project_root(), check=True, creationflags=WINDOWS_NO_CONSOLE)
            if command == "up":
                for _ in range(20):
                    if Launcher.server_is_ready():
                        break
                    time.sleep(1)
            return {"ok": True, "running": Launcher.server_is_ready()}
        except subprocess.CalledProcessError:
            return {"ok": False, "message": "Docker command failed"}


class Launcher(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Task Manager Launcher")
        self.geometry("620x430")
        self.minsize(620, 430)
        self.configure(bg=BG)

        root = tk.Frame(self, bg=BG, padx=28, pady=25)
        root.pack(fill="both", expand=True)
        tk.Label(root, text="TASK MANAGER", font=("Segoe UI", 10, "bold"), fg=ACCENT, bg=BG).pack(anchor="w")
        tk.Label(root, text="\u041b\u043e\u043a\u0430\u043b\u044c\u043d\u044b\u0439 \u0441\u0435\u0440\u0432\u0435\u0440", font=("Segoe UI", 25, "bold"), fg=TEXT, bg=BG).pack(anchor="w", pady=(2, 3))
        tk.Label(root, text="\u0423\u043f\u0440\u0430\u0432\u043b\u044f\u0439\u0442\u0435 \u0441\u0435\u0440\u0432\u0435\u0440\u043e\u043c \u0434\u043b\u044f \u0441\u0432\u043e\u0435\u0439 \u043a\u043e\u043c\u0430\u043d\u0434\u044b \u0431\u0435\u0437 \u043a\u043e\u043d\u0441\u043e\u043b\u0438.", font=("Segoe UI", 10), fg=MUTED, bg=BG).pack(anchor="w")

        status_card = tk.Frame(root, bg=PANEL, padx=18, pady=16)
        status_card.pack(fill="x", pady=(22, 14))
        tk.Label(status_card, text="\u0421\u041e\u0421\u0422\u041e\u042f\u041d\u0418\u0415", font=("Segoe UI", 9, "bold"), fg=MUTED, bg=PANEL).pack(anchor="w")
        self.status = tk.Label(status_card, text="\u041f\u0440\u043e\u0432\u0435\u0440\u043a\u0430 \u0441\u043e\u0441\u0442\u043e\u044f\u043d\u0438\u044f...", font=("Segoe UI", 15, "bold"), fg=MUTED, bg=PANEL)
        self.status.pack(anchor="w", pady=(5, 0))
        self.status_detail = tk.Label(status_card, text=APP_URL, font=("Segoe UI", 9), fg=MUTED, bg=PANEL)
        self.status_detail.pack(anchor="w", pady=(4, 0))

        actions = tk.Frame(root, bg=BG)
        actions.pack(fill="x", pady=(2, 16))
        self.start_button = self.make_button(actions, "\u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u0441\u0435\u0440\u0432\u0435\u0440", self.start_server, ACCENT, "#07142d")
        self.start_button.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.open_button = self.make_button(actions, "\u041e\u0442\u043a\u0440\u044b\u0442\u044c \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435", self.open_desktop_app, "#253756", TEXT)
        self.open_button.pack(side="left", fill="x", expand=True, padx=6)
        self.stop_button = self.make_button(actions, "\u041e\u0441\u0442\u0430\u043d\u043e\u0432\u0438\u0442\u044c", self.stop_server, "#253756", TEXT)
        self.stop_button.pack(side="left", fill="x", expand=True, padx=(6, 0))

        hint = tk.Frame(root, bg=PANEL_ALT, padx=16, pady=14)
        hint.pack(fill="x")
        tk.Label(hint, text="\u0427\u0442\u043e \u0434\u0430\u043b\u044c\u0448\u0435", font=("Segoe UI", 10, "bold"), fg=TEXT, bg=PANEL_ALT).pack(anchor="w")
        tk.Label(hint, text="\u041f\u043e\u0441\u043b\u0435 \u0437\u0430\u043f\u0443\u0441\u043a\u0430 \u043e\u0442\u043a\u0440\u043e\u0439\u0442\u0435 \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435, \u0437\u0430\u0442\u0435\u043c \u0432\u044b\u0431\u0435\u0440\u0438\u0442\u0435 \u00ab\u041c\u043e\u0439 \u0441\u0435\u0440\u0432\u0435\u0440\u00bb \u0434\u043b\u044f QR-\u043a\u043e\u0434\u0430 \u0438 \u043d\u0430\u0441\u0442\u0440\u043e\u0435\u043a.", wraplength=540, justify="left", font=("Segoe UI", 10), fg=MUTED, bg=PANEL_ALT).pack(anchor="w", pady=(5, 0))
        self.refresh_status()
        self.after(700, self.open_when_ready)

    def open_when_ready(self) -> None:
        if self.server_is_ready():
            self.open_desktop_app()

    @staticmethod
    def make_button(parent: tk.Widget, text: str, command: object, background: str, foreground: str) -> tk.Button:
        return tk.Button(parent, text=text, command=command, bg=background, fg=foreground, activebackground=background, activeforeground=foreground, disabledforeground="#71809e", font=("Segoe UI", 10, "bold"), relief="flat", bd=0, cursor="hand2", pady=12)

    def set_status(self, text: str, color: str, detail: str = APP_URL) -> None:
        self.status.configure(text=text, fg=color)
        self.status_detail.configure(text=detail)

    @staticmethod
    def server_is_ready() -> bool:
        try:
            with urllib.request.urlopen(f"{APP_URL}/health", timeout=1.5) as response:
                return response.status == 200
        except OSError:
            return False

    def refresh_status(self) -> None:
        ready = self.server_is_ready()
        if ready:
            self.set_status("● \u0421\u0435\u0440\u0432\u0435\u0440 \u0437\u0430\u043f\u0443\u0449\u0435\u043d", SUCCESS, "\u0413\u043e\u0442\u043e\u0432 \u043a \u043f\u043e\u0434\u043a\u043b\u044e\u0447\u0435\u043d\u0438\u044e \u043f\u043e \u0430\u0434\u0440\u0435\u0441\u0443 " + APP_URL)
        else:
            self.set_status("○ \u0421\u0435\u0440\u0432\u0435\u0440 \u043e\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d", MUTED, "\u041d\u0430\u0436\u043c\u0438\u0442\u0435 \u00ab\u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u044c \u0441\u0435\u0440\u0432\u0435\u0440\u00bb, \u0447\u0442\u043e\u0431\u044b \u043e\u043d \u0441\u0442\u0430\u043b \u0434\u043e\u0441\u0442\u0443\u043f\u0435\u043d.")
        self.start_button.configure(state="disabled" if ready else "normal")
        self.stop_button.configure(state="normal" if ready else "disabled")
        self.open_button.configure(state="normal" if ready else "disabled")
        self.after(2500, self.refresh_status)

    def run_compose(self, command: str) -> None:
        docker = docker_executable()
        if docker is None:
            self.after(0, lambda: messagebox.showerror("Docker \u043d\u0435 \u043d\u0430\u0439\u0434\u0435\u043d", "\u0417\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u0435 Docker Desktop, \u0437\u0430\u0442\u0435\u043c \u043f\u043e\u0432\u0442\u043e\u0440\u0438\u0442\u0435."))
            return
        try:
            args = ["up", "--build", "--detach"] if command == "up" else ["down"]
            subprocess.run([docker, "compose", *args], cwd=project_root(), check=True, creationflags=WINDOWS_NO_CONSOLE)
            if command == "up":
                for _ in range(20):
                    time.sleep(1)
                    if self.server_is_ready():
                        break
            self.after(0, self.open_desktop_app if command == "up" else self.refresh_status)
        except subprocess.CalledProcessError:
            self.after(0, lambda: messagebox.showerror("\u041e\u0448\u0438\u0431\u043a\u0430 \u0437\u0430\u043f\u0443\u0441\u043a\u0430", "\u041f\u0440\u043e\u0432\u0435\u0440\u044c\u0442\u0435, \u0447\u0442\u043e Docker Desktop \u0437\u0430\u043f\u0443\u0449\u0435\u043d."))

    def start_server(self) -> None:
        self.set_status("\u0417\u0430\u043f\u0443\u0441\u043a\u0430\u044e \u0441\u0435\u0440\u0432\u0435\u0440...", ACCENT)
        threading.Thread(target=self.run_compose, args=("up",), daemon=True).start()

    def stop_server(self) -> None:
        self.set_status("\u041e\u0441\u0442\u0430\u043d\u0430\u0432\u043b\u0438\u0432\u0430\u044e \u0441\u0435\u0440\u0432\u0435\u0440...", MUTED)
        threading.Thread(target=self.run_compose, args=("down",), daemon=True).start()

    def open_desktop_app(self) -> None:
        if not self.server_is_ready():
            messagebox.showinfo("\u0421\u0435\u0440\u0432\u0435\u0440 \u043e\u0441\u0442\u0430\u043d\u043e\u0432\u043b\u0435\u043d", "\u0421\u043d\u0430\u0447\u0430\u043b\u0430 \u0437\u0430\u043f\u0443\u0441\u0442\u0438\u0442\u0435 \u0441\u0435\u0440\u0432\u0435\u0440.")
            return
        try:
            import webview

            self.destroy()
            webview.create_window("Task Manager", APP_URL, width=1180, height=800, min_size=(900, 620), background_color=BG, js_api=DesktopServerApi())
            WEBVIEW_STORAGE.mkdir(parents=True, exist_ok=True)
            webview.start(private_mode=False, storage_path=str(WEBVIEW_STORAGE))
        except Exception as error:
            messagebox.showerror("\u041d\u0435 \u0443\u0434\u0430\u043b\u043e\u0441\u044c \u043e\u0442\u043a\u0440\u044b\u0442\u044c \u043f\u0440\u0438\u043b\u043e\u0436\u0435\u043d\u0438\u0435", str(error))


if __name__ == "__main__":
    Launcher().mainloop()
    tunnel_process: subprocess.Popen[str] | None = None
    tunnel_url: str | None = None
