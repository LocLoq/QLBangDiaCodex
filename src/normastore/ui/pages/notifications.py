from __future__ import annotations

from tkinter import ttk

from ttkbootstrap.constants import BOTH, END, LEFT

from normastore.domain.enums import NotificationStatus
from normastore.ui.formatting import format_datetime


STATUS_LABELS = {
    NotificationStatus.PENDING: "Chờ gửi",
    NotificationStatus.SENT: "Đã gửi",
    NotificationStatus.FAILED: "Gửi thất bại",
    NotificationStatus.SKIPPED: "Đã bỏ qua",
}
EVENT_LABELS = {
    "BEFORE_DUE": "Sắp đến hạn trả",
    "DUE_TODAY": "Đến hạn trả hôm nay",
    "OVERDUE_1": "Quá hạn 1 ngày",
    "OVERDUE_3": "Quá hạn 3 ngày",
    "OVERDUE_7": "Quá hạn 7 ngày",
}

class NotificationsPageMixin:
    def notifications_page(self, page) -> None:
        self._heading(page, "Thông báo", "Nhắc hạn trả và gửi bù khi mở ứng dụng")
        ttk.Label(
            page,
            text="Kiểm tra mỗi 5 phút khi ứng dụng mở. Tin nhắn SMS được mô phỏng; email cần cấu hình máy chủ gửi và thông tin đăng nhập Windows.",
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
                        EVENT_LABELS.get(notification.event, notification.event),
                        format_datetime(notification.scheduled_for),
                        STATUS_LABELS.get(notification.status, notification.status),
                        notification.attempts,
                        notification.error or "—",
                    ),
                )

        ttk.Button(page, text="Làm mới", command=refresh, bootstyle="secondary").pack(
            anchor="e", pady=(8, 0)
        )
        page.refresh = refresh
