from __future__ import annotations

from PIL import Image, ImageTk


class PosterMixin:
    def _load_poster_thumbnail(self, poster_path, label) -> None:
        if not poster_path:
            return
        target = self.poster_cache.path_for(poster_path)
        cache_key = str(target)

        def apply_thumbnail(path) -> None:
            if not label.winfo_exists() or not path:
                return
            try:
                with Image.open(path) as image:
                    image.thumbnail((82, 116))
                    thumbnail = ImageTk.PhotoImage(image.copy())
            except Exception:
                return
            self._poster_images[cache_key] = thumbnail
            label.configure(image=thumbnail, text="")

        if cache_key in self._poster_images:
            label.configure(image=self._poster_images[cache_key], text="")
        elif target.exists():
            apply_thumbnail(target)
        elif poster_path not in self._poster_loading:
            self._poster_loading.add(poster_path)
            future = self.executor.submit(lambda: self.poster_cache.fetch(poster_path))

            def poll() -> None:
                if not future.done():
                    self.after(80, poll)
                    return
                self._poster_loading.discard(poster_path)
                try:
                    apply_thumbnail(future.result())
                except Exception:
                    pass

            self.after(80, poll)
