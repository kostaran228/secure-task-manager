"""Windows desktop launcher for the local Task Manager server."""

from __future__ import annotations

import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
import webbrowser
from pathlib import Path
from tkinter import messagebox


APP_URL = "http://localhost:8000"
WINDOWS_NO_CONSOLE = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def project_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent.parent
    return Path(__file__).resolve().parent.parent


def docker_executable() -> str | None:
    candidates = [
        Path("D:/DevTools/Docker/resources/bin/docker.exe"),
        Path("C:/Program Files/Docker/Docker/resources/bin/docker.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    for directory in os.environ.get("PATH", "").split(os.pathsep):
        candidate = Path(directory) / "docker.exe"
        if candidate.exists():
            return str(candidate)
    return None


class Launcher(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("Task Manager — Local Server")
        self.geometry("470x280")
        self.resizable(False, False)
        self.configure(bg="#0b1020")

        frame = tk.Frame(self, bg="#151d35", padx=24, pady=22)
        frame.pack(fill="both", expand=True, padx=16, pady=16)
        tk.Label(frame, text="Локальный сервер Task Manager", font=("Segoe UI", 17, "bold"), fg="#eef3ff", bg="#151d35").pack(anchor="w")
        tk.Label(frame, text="Запускайте сервер для своей команды без консоли.", font=("Segoe UI", 10), fg="#9aa7c7", bg="#151d35").pack(anchor="w", pady=(7, 14))
        self.status = tk.Label(frame, text="Проверка состояния…", font=("Segoe UI", 11, "bold"), fg="#9aa7c7", bg="#151d35")
        self.status.pack(anchor="w", pady=(0, 16))

        actions = tk.Frame(frame, bg="#151d35")
        actions.pack(anchor="w")
        self.start_button = tk.Button(actions, text="Запустить сервер", command=self.start_server, bg="#6ea8fe", fg="#06122b", activebackground="#8ab9ff", font=("Segoe UI", 10, "bold"), relief="flat", padx=14, pady=8)
        self.start_button.pack(side="left")
        self.stop_button = tk.Button(actions, text="Остановить", command=self.stop_server, bg="#263554", fg="#eef3ff", activebackground="#3c517d", font=("Segoe UI", 10, "bold"), relief="flat", padx=14, pady=8)
        self.stop_button.pack(side="left", padx=8)
        self.open_button = tk.Button(actions, text="Открыть приложение", command=lambda: webbrowser.open(APP_URL), bg="#263554", fg="#eef3ff", activebackground="#3c517d", font=("Segoe UI", 10, "bold"), relief="flat", padx=14, pady=8)
        self.open_button.pack(side="left")

        tk.Label(frame, text="После запуска открой «Мой сервер» в приложении для QR-кода и настроек.", wraplength=400, justify="left", font=("Segoe UI", 9), fg="#9aa7c7", bg="#151d35").pack(anchor="w", pady=(20, 0))
        self.refresh_status()

    def set_status(self, text: str, color: str = "#9aa7c7") -> None:
        self.status.configure(text=text, fg=color)

    @staticmethod
    def server_is_ready() -> bool:
        try:
            with urllib.request.urlopen(f"{APP_URL}/health", timeout=1.5) as response:
                return response.status == 200
        except OSError:
            return False

    def refresh_status(self) -> None:
        ready = self.server_is_ready()
        self.set_status("● Сервер запущен" if ready else "○ Сервер остановлен", "#55d6a1" if ready else "#9aa7c7")
        self.start_button.configure(state="disabled" if ready else "normal")
        self.stop_button.configure(state="normal" if ready else "disabled")
        self.after(3000, self.refresh_status)

    def run_compose(self, command: str) -> None:
        docker = docker_executable()
        if docker is None:
            self.after(0, lambda: messagebox.showerror("Docker не найден", "Установите и запустите Docker Desktop, затем повторите."))
            return
        try:
            compose_args = ["up", "--build", "--detach"] if command == "up" else ["down"]
            subprocess.run([docker, "compose", *compose_args], cwd=project_root(), check=True, creationflags=WINDOWS_NO_CONSOLE)
            if command == "up":
                for _ in range(20):
                    time.sleep(1)
                    if self.server_is_ready():
                        break
            self.after(0, self.refresh_status)
        except subprocess.CalledProcessError:
            self.after(0, lambda: messagebox.showerror("Не удалось выполнить команду", "Проверьте, что Docker Desktop запущен."))

    def start_server(self) -> None:
        self.set_status("Запускаю сервер…", "#6ea8fe")
        threading.Thread(target=self.run_compose, args=("up",), daemon=True).start()

    def stop_server(self) -> None:
        self.set_status("Останавливаю сервер…", "#9aa7c7")
        threading.Thread(target=self.run_compose, args=("down",), daemon=True).start()


if __name__ == "__main__":
    Launcher().mainloop()
