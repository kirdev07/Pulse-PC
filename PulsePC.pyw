"""Double-click to start Pulse PC (works without any .exe).

First run: creates the Python environment and installs packages, showing progress.
Next runs: starts the panel straight away.
"""
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import launcher  # noqa: E402

ARGS = [a for a in sys.argv[1:] if a in ("--minimized", "-m")]


def run_with_window():
    import tkinter as tk
    from tkinter import messagebox, scrolledtext

    root = tk.Tk()
    root.title("Pulse PC — подготовка")
    root.geometry("560x320")
    root.configure(bg="#05080C")
    tk.Label(root, text="Pulse PC: первая настройка", bg="#05080C", fg="#2A8CFF",
             font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
    tk.Label(root, text="Ставлю нужные пакеты Python. Это один раз, окно закроется само.", bg="#05080C",
             fg="#8A97A8", font=("Segoe UI", 10)).pack(anchor="w", padx=14)
    box = scrolledtext.ScrolledText(root, height=12, bg="#0D1319", fg="#B9C6D8", font=("Consolas", 9),
                                    borderwidth=0, highlightthickness=0)
    box.pack(fill="both", expand=True, padx=14, pady=12)
    lines, result = [], {}

    def log(text):
        lines.append(text)
        root.after(0, lambda: (box.insert("end", text + "\n"), box.see("end")))

    def work():
        try:
            result["env"] = launcher.prepare(log)
        except launcher.SetupError as exc:
            result["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001 - show anything to the user
            result["error"] = f"{type(exc).__name__}: {exc}"
        root.after(0, finish)

    def finish():
        if "env" in result:
            launcher.start(result["env"], ARGS)
            root.destroy()
            return
        (launcher.ROOT / "install.log").write_text("\n".join(lines + ["", result["error"]]), encoding="utf-8")
        messagebox.showerror("Pulse PC", result["error"] + "\n\nПодробности сохранены в install.log")
        root.destroy()

    threading.Thread(target=work, daemon=True).start()
    root.mainloop()


def main():
    env = launcher.find_ready_env()
    if env:
        launcher.start(env, ARGS)
        return
    run_with_window()


if __name__ == "__main__":
    main()
