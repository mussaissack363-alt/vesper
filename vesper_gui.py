import tkinter as tk
from tkinter import scrolledtext
import threading

from groq_brain_v3 import (think, DEVICE_TYPE, handle_phone_command,
                           handle_pc_command, handle_memory_command, migrate_firebase_once)


def process_input(user_input):
    mem_result = handle_memory_command(user_input)
    if mem_result:
        append_text(f"Vesper: {mem_result}\n\n")
        return

    if DEVICE_TYPE == 'mobile':
        result = handle_phone_command(user_input)
        if result:
            append_text(f"Vesper: {result}\n\n")
            return

    if DEVICE_TYPE == 'pc':
        result = handle_pc_command(user_input)
        if result:
            append_text(f"Vesper: {result}\n\n")
            return

    reply = think(user_input)
    append_text(f"Vesper: {reply}\n\n")


def send_message(event=None):
    user_input = entry.get().strip()
    if not user_input:
        return
    entry.delete(0, tk.END)
    append_text(f"You: {user_input}\n")
    threading.Thread(target=process_input, args=(user_input,), daemon=True).start()


def append_text(text):
    output.config(state='normal')
    output.insert(tk.END, text)
    output.config(state='disabled')
    output.see(tk.END)


root = tk.Tk()
root.title(f"Vesper ({DEVICE_TYPE.upper()})")
root.geometry("520x620")
root.configure(bg="#1e1e1e")

output = scrolledtext.ScrolledText(
    root, wrap=tk.WORD, bg="#2b2b2b", fg="#e0e0e0",
    font=("Consolas", 11), state='disabled', borderwidth=0
)
output.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)

entry_frame = tk.Frame(root, bg="#1e1e1e")
entry_frame.pack(padx=10, pady=(0, 10), fill=tk.X)

entry = tk.Entry(
    entry_frame, font=("Consolas", 11), bg="#2b2b2b", fg="#e0e0e0",
    insertbackground="#e0e0e0", relief=tk.FLAT
)
entry.pack(side=tk.LEFT, fill=tk.X, expand=True, ipady=8, padx=(0, 8))
entry.bind("<Return>", send_message)
entry.focus()

send_btn = tk.Button(
    entry_frame, text="Send", command=send_message,
    bg="#3a3a3a", fg="#e0e0e0", relief=tk.FLAT, padx=18, activebackground="#4a4a4a"
)
send_btn.pack(side=tk.RIGHT)

append_text(f"Vesper online ({DEVICE_TYPE.upper()}).\n\n")

migrate_firebase_once()
mem_count_result = handle_memory_command("what do you remember")
if mem_count_result:
    append_text(mem_count_result + "\n\n")

root.mainloop()
