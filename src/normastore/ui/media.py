from __future__ import annotations

import hashlib
import shutil
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, ttk
from platformdirs import user_data_dir
from PIL import Image, ImageTk


class PosterMixin:
    def _poster_editor(self, parent, initial: str | None):
        frame = ttk.LabelFrame(parent, text="Ảnh bìa", padding=6)
        frame.pack(fill="x", pady=5)
        value = tk.StringVar(value=initial or "")
        ttk.Entry(frame, textvariable=value).pack(fill="x")
        row = ttk.Frame(frame)
        row.pack(fill="x", pady=4)
        preview = ttk.Label(row, text="Chưa chọn ảnh")
        preview.pack(side="right")
        def choose():
            path = filedialog.askopenfilename(parent=parent, title="Chọn ảnh bìa", filetypes=[("Ảnh", "*.jpg *.jpeg *.png *.webp *.gif *.bmp")])
            if path:
                value.set(path)
                self._load_poster_thumbnail(path, preview)
        ttk.Button(row, text="Chọn ảnh cục bộ", command=choose).pack(side="left")
        ttk.Button(row, text="Xem trước", command=lambda: self._load_poster_thumbnail(value.get(), preview)).pack(side="left", padx=4)
        def clear():
            value.set("")
            preview._poster_request = None
            preview.configure(image="", text="Chưa chọn ảnh")
        ttk.Button(row, text="Xóa ảnh", command=clear).pack(side="left")
        if initial:
            self._load_poster_thumbnail(initial, preview)
        def prepare():
            source = value.get().strip()
            if len(source) > 500:
                raise ValueError("Đường dẫn ảnh không được dài quá 500 ký tự.")
            if source == (initial or ""):
                return source or None
            if source.startswith(("https://", "http://")):
                try:
                    cached = self.poster_cache.fetch(source)
                    with Image.open(cached) as image:
                        image.verify()
                except Exception as exc:
                    cached_path = self.poster_cache.path_for(source)
                    cached_path.unlink(missing_ok=True)
                    raise ValueError("Không thể tải ảnh hợp lệ từ liên kết.") from exc
                return source
            if not source:
                return source or None
            path = Path(source)
            if not path.is_file():
                raise ValueError("Không tìm thấy ảnh bìa.")
            with Image.open(path) as image:
                image.verify()
            folder = Path(user_data_dir("NormaStore")) / "posters"
            folder.mkdir(parents=True, exist_ok=True)
            digest = hashlib.sha256(path.read_bytes()).hexdigest()
            target = folder / f"{digest}{path.suffix.lower()}"
            if not target.exists():
                shutil.copyfile(path, target)
            return str(target)
        return prepare

    def _load_poster_thumbnail(self, poster_path, label, *, size: tuple[int, int] = (82, 116)) -> None:
        if not poster_path:
            return
        target = self.poster_cache.path_for(poster_path)
        cache_key = f"{target}|{size[0]}x{size[1]}"
        label._poster_request = cache_key

        def apply_thumbnail(path) -> None:
            if not label.winfo_exists() or not path or getattr(label, "_poster_request", None) != cache_key:
                return
            try:
                with Image.open(path) as image:
                    image.thumbnail(size)
                    thumbnail = ImageTk.PhotoImage(image.copy())
            except Exception:
                return
            self._poster_images[cache_key] = thumbnail
            label.configure(image=thumbnail, text="")

        if cache_key in self._poster_images:
            label.configure(image=self._poster_images[cache_key], text="")
        elif target.exists():
            apply_thumbnail(target)
        else:
            future = self.executor.submit(lambda: self.poster_cache.fetch(poster_path))

            def poll() -> None:
                if not future.done():
                    self.after(80, poll)
                    return
                try:
                    apply_thumbnail(future.result())
                except Exception:
                    if label.winfo_exists() and getattr(label, "_poster_request", None) == cache_key:
                        label.configure(image="", text="Không tải được ảnh")

            self.after(80, poll)
