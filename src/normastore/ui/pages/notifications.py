from __future__ import annotations

from tkinter import ttk

from ttkbootstrap.constants import BOTH, END, LEFT


class NotificationsPageMixin:
    def notifications_page(self, page) -> None:
        self._heading(page, "Thông báo", "Email SMTP thật • SMS mock • Gửi bù khi mở app")
        ttk.Label(
            page,
            text="Worker kiểm tra mỗi 5 phút khi ứng dụng mở. SMS là mock; Email chỉ gửi khi SMTP và Windows Credential Manager được cấu hình.",
            wraplength=850,
            justify=LEFT,
        ).pack(anchor="w", pady=(0, 10))
        tree = self._create_treeview(
            page,
            columns=("customer", "channel", "event", "scheduled", "status", "attempts", "error"),
            show="headings",
        )
        for key, title in [
            ("customer", "Khách hàng"),
            ("channel", "Kênh"),
            ("event", "Sự kiện"),
            ("scheduled", "Lịch gửi"),
            ("status", "Trạng thái"),
            ("attempts", "Lần thử"),
            ("error", "Lỗi"),
        ]:
            tree.heading(key, text=title)
        tree.column("error", width=260)
        tree.pack(fill=BOTH, expand=True)

        def refresh():
            tree.delete(*tree.get_children())
            for notification in self.store.list_notifications():
                tree.insert(
                    "",
                    END,
                    iid=str(notification.notification_id),
                    values=(
                        notification.customer_name,
                        notification.channel,
                        notification.event,
                        notification.scheduled_for.strftime("%d/%m/%Y %H:%M"),
                        notification.status,
                        notification.attempts,
                        notification.error or "—",
                    ),
                )

        ttk.Button(page, text="Làm mới", command=refresh, bootstyle="secondary").pack(
            anchor="e", pady=(8, 0)
        )
        page.refresh = refresh
