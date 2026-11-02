from __future__ import annotations

from tkinter import ttk

from ttkbootstrap.constants import BOTH, END, LEFT, X

from normastore.ui.formatting import vnd


class DashboardPageMixin:
    def dashboard_page(self, page) -> None:
        self._heading(page, "Tổng quan", "Tình hình cửa hàng hôm nay")
        cards = ttk.Frame(page)
        cards.pack(fill=X)
        fields = [
            ("available", "Có sẵn", "success"),
            ("rented", "Đang thuê", "primary"),
            ("overdue", "Quá hạn", "danger"),
            ("reservations", "Đặt trước", "warning"),
        ]
        labels = {}
        for key, title, style in fields:
            card = ttk.Labelframe(cards, text=title, padding=15, bootstyle=style)
            card.pack(side=LEFT, fill=X, expand=True, padx=4)
            labels[key] = ttk.Label(card, text="—", font=("Segoe UI", 20, "bold"))
            labels[key].pack()
        revenue = ttk.Label(page, text="", font=("Segoe UI", 13, "bold"), bootstyle="primary")
        revenue.pack(anchor="w", padx=5, pady=16)
        quick = ttk.Labelframe(page, text="Thao tác nhanh", padding=12)
        quick.pack(fill=X, padx=4)
        ttk.Button(quick, text="Mở ca", command=self._open_shift, bootstyle="success").pack(
            side=LEFT, padx=4
        )
        ttk.Button(
            quick,
            text="Lập phiếu",
            command=lambda: self.show_page("Lập phiếu", self.checkout_page),
            bootstyle="primary",
        ).pack(side=LEFT, padx=4)
        ttk.Button(
            quick,
            text="Nhập phim/tập",
            command=lambda: self.show_page("Phim & tập", self.catalog_page),
        ).pack(side=LEFT, padx=4)
        recommendation_box = ttk.Labelframe(page, text="Đề cử hôm nay", padding=10)
        recommendation_box.pack(fill=BOTH, expand=True, padx=4, pady=(14, 0))
        recommendation_tree = self._create_treeview(
            recommendation_box, columns=("reason",), show="tree headings", height=7
        )
        recommendation_tree.heading("#0", text="Phim / tập")
        recommendation_tree.heading("reason", text="Lý do")
        recommendation_tree.pack(fill=BOTH, expand=True)

        def refresh():
            stats = self.call(lambda s: s.dashboard())
            for key in labels:
                labels[key].configure(text=str(stats[key]))
            revenue.configure(text=f"Dòng tiền thuần (gồm cọc): {vnd(stats['cash_flow'])}")
            recommendation_tree.delete(*recommendation_tree.get_children())
            for recommendation in self.call(lambda s: s.today_recommendations(), True):
                recommendation_tree.insert(
                    "",
                    END,
                    iid=str(recommendation.item_id),
                    text=recommendation.title,
                    values=(recommendation.reason,),
                )
            self._refresh_status()

        page.refresh = refresh
