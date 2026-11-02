from __future__ import annotations

from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

from ttkbootstrap.constants import BOTH, END, LEFT

from normastore.ui.formatting import vnd


class PromotionsPageMixin:
    def promotions_page(self, page) -> None:
        self._heading(page, "Combo / Voucher", "Ưu đãi áp theo Combo → Premium → Voucher, trần 50%")
        notebook = ttk.Notebook(page)
        notebook.pack(fill=BOTH, expand=True)
        combo, voucher = ttk.Frame(notebook, padding=15), ttk.Frame(notebook, padding=15)
        notebook.add(combo, text="Combo")
        notebook.add(voucher, text="Voucher")
        ttk.Label(
            combo,
            text="Combo cố định giảm giá khi giỏ có đủ toàn bộ item. Nhập ID phim/tập, phân cách bằng dấu phẩy.",
            justify=LEFT,
        ).pack(anchor="nw")

        def create_combo():
            name = simpledialog.askstring("Combo", "Tên combo:", parent=self)
            item_text = (
                simpledialog.askstring("Combo", "ID phim/tập:", parent=self) if name else None
            )
            discount = (
                simpledialog.askstring("Combo", "Số tiền giảm:", parent=self) if item_text else None
            )
            if not discount:
                return
            try:
                ids = [int(value.strip()) for value in item_text.split(",")]
                self.store.create_fixed_combo(name, ids, Decimal(discount), self.account.employee_id)
                messagebox.showinfo(
                    "Combo", "Đã tạo combo. Combo sẽ xuất hiện trong màn lập phiếu.", parent=self
                )
                refresh_promotions()
            except Exception as exc:
                messagebox.showerror("Combo", str(exc), parent=self)

        management_state = "normal" if self._can_manage() else "disabled"
        ttk.Button(
            combo,
            text="Tạo combo cố định",
            command=create_combo,
            bootstyle="primary",
            state=management_state,
        ).pack(anchor="w", pady=(10, 0))

        def create_episode_combo():
            name = simpledialog.askstring("Combo tập phim", "Tên combo:", parent=self)
            show_id = (
                simpledialog.askinteger("Combo tập phim", "ID bộ phim (Show):", parent=self)
                if name
                else None
            )
            count = (
                simpledialog.askinteger("Combo tập phim", "Số tập tối thiểu:", parent=self)
                if show_id
                else None
            )
            discount = (
                simpledialog.askstring("Combo tập phim", "Số tiền giảm:", parent=self)
                if count
                else None
            )
            if not discount:
                return
            try:
                self.store.create_show_episode_combo(name, show_id, count, Decimal(discount), self.account.employee_id)
                messagebox.showinfo(
                    "Combo tập phim", "Đã tạo combo theo số tập cùng bộ.", parent=self
                )
                refresh_promotions()
            except Exception as exc:
                messagebox.showerror("Combo tập phim", str(exc), parent=self)

        ttk.Button(
            combo,
            text="Tạo combo N tập cùng bộ",
            command=create_episode_combo,
            bootstyle="secondary",
            state=management_state,
        ).pack(anchor="w", pady=(6, 0))
        combo_tree = self._create_treeview(
            combo,
            columns=("rule", "scope", "required", "discount", "state"),
            show="tree headings",
            height=12,
        )
        for key, title in [
            ("#0", "Tên combo"),
            ("rule", "Quy tắc"),
            ("scope", "Áp dụng"),
            ("required", "Số tập"),
            ("discount", "Giảm"),
            ("state", "Trạng thái"),
        ]:
            combo_tree.heading(key, text=title)
        combo_tree.column("scope", width=250)
        combo_tree.pack(fill=BOTH, expand=True, pady=(10, 0))
        tree = self._create_treeview(
            voucher,
            columns=("description", "starts", "ends", "state"),
            show="tree headings",
            height=12,
        )
        for key, title in [
            ("#0", "Mã"),
            ("description", "Ưu đãi"),
            ("starts", "Bắt đầu"),
            ("ends", "Kết thúc"),
            ("state", "Trạng thái"),
        ]:
            tree.heading(key, text=title)
        tree.pack(fill=BOTH, expand=True)

        def refresh_promotions():
            combo_tree.delete(*combo_tree.get_children())
            for item in self.store.list_combos(include_inactive=True):
                combo_tree.insert(
                    "",
                    END,
                    iid=str(item.combo_id),
                    text=item.name,
                    values=(
                        "Cố định" if item.rule_type == "FIXED" else "Theo bộ",
                        item.scope,
                        item.required_count or "—",
                        vnd(item.discount_amount),
                        "Hoạt động" if item.active else "Đã tắt",
                    ),
                )
            tree.delete(*tree.get_children())
            for item in self.store.list_vouchers():
                tree.insert(
                    "",
                    END,
                    iid=str(item.voucher_id),
                    text=item.code,
                    values=(
                        item.description,
                        item.starts_on or "—",
                        item.ends_on or "—",
                        item.effective_state,
                    ),
                )

        def create_voucher():
            code = simpledialog.askstring("Voucher", "Mã voucher:", parent=self)
            if not code:
                return
            value = simpledialog.askstring(
                "Voucher", "Nhập phần trăm (vd 10) hoặc số tiền kèm 'd' (vd 20000d):", parent=self
            )
            if not value:
                return
            try:
                self.store.create_voucher_from_text(code, value, self.account.employee_id)
                refresh_promotions()
            except Exception as exc:
                messagebox.showerror("Voucher", str(exc), parent=self)

        ttk.Button(
            voucher,
            text="Tạo voucher",
            command=create_voucher,
            bootstyle="primary",
            state=management_state,
        ).pack(anchor="e", pady=(8, 0))
        ttk.Button(combo, text="Làm mới", command=refresh_promotions, bootstyle="secondary").pack(
            anchor="e", pady=(6, 0)
        )
        ttk.Button(voucher, text="Làm mới", command=refresh_promotions, bootstyle="secondary").pack(
            anchor="w", pady=(8, 0)
        )
        page.refresh = refresh_promotions
