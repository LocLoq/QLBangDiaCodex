from __future__ import annotations

import tkinter as tk
from decimal import Decimal, InvalidOperation
from tkinter import messagebox, simpledialog, ttk

from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X, Y

from normastore.application.contracts import CatalogFilters, PageRequest
from normastore.ui.formatting import vnd


class PromotionsPageMixin:
    def promotions_page(self, page) -> None:
        self._heading(page, "Combo / Voucher", "Ưu đãi áp theo Khám phá → Combo → Premium → Voucher, trần 50%")
        notebook = ttk.Notebook(page)
        notebook.pack(fill=BOTH, expand=True)
        combo, voucher = ttk.Frame(notebook, padding=15), ttk.Frame(notebook, padding=15)
        notebook.add(combo, text="Combo")
        notebook.add(voucher, text="Voucher")
        ttk.Label(
            combo,
            text="Combo cố định giảm giá khi giỏ có đủ toàn bộ phim hoặc tập đã chọn.",
            justify=LEFT,
        ).pack(anchor="nw")

        def combo_form(title, width, height):
            dialog = self._dialog(title, width, height)
            form = ttk.Frame(dialog, padding=12)
            form.pack(fill=BOTH, expand=True)
            name, discount = tk.StringVar(), tk.StringVar()
            for label, variable in (("Tên combo:", name), ("Số tiền giảm (đ):", discount)):
                ttk.Label(form, text=label).pack(anchor="w")
                ttk.Entry(form, textvariable=variable).pack(fill=X, pady=(0, 6))
            return dialog, form, name, discount

        def read_discount(variable):
            try:
                amount = Decimal(variable.get().strip())
            except InvalidOperation as exc:
                raise ValueError("Nhập số tiền giảm hợp lệ.") from exc
            if not amount.is_finite() or amount <= 0:
                raise ValueError("Số tiền giảm phải lớn hơn 0.")
            return amount

        def create_combo():
            dialog, form, name, discount = combo_form("Tạo combo cố định", 940, 610)
            footer = ttk.Frame(form)
            footer.pack(side="bottom", fill=X)
            search_row = ttk.Frame(form)
            search_row.pack(fill=X, pady=(2, 8))
            search = tk.StringVar()
            ttk.Label(search_row, text="Tìm phim hoặc tập:").pack(side=LEFT, padx=(0, 6))
            search_entry = ttk.Entry(search_row, textvariable=search)
            search_entry.pack(side=LEFT, fill=X, expand=True)
            lists = ttk.Frame(form)
            lists.pack(fill=BOTH, expand=True, pady=(0, 8))
            results_panel = ttk.Frame(lists)
            results_panel.pack(side=LEFT, fill=BOTH, expand=True, padx=(0, 6))
            chosen_panel = ttk.Frame(lists)
            chosen_panel.pack(side=LEFT, fill=BOTH, expand=True, padx=(6, 0))
            page_number = tk.IntVar(value=1)

            def item_list(panel, heading):
                ttk.Label(panel, text=heading).pack(anchor="w")
                area = ttk.Frame(panel)
                area.pack(fill=BOTH, expand=True)
                tree = self._create_treeview(
                    area, columns=("detail",), show="tree headings", height=8, selectmode="extended",
                )
                tree.heading("#0", text="Phim / tập")
                tree.heading("detail", text="Bộ phim / mùa / tập")
                tree.column("#0", width=130, minwidth=85)
                tree.column("detail", width=225, minwidth=85)
                scroll = ttk.Scrollbar(area, command=tree.yview)
                tree.configure(yscrollcommand=scroll.set)
                scroll.pack(side=RIGHT, fill=Y)
                tree.pack(side=LEFT, fill=BOTH, expand=True)
                return tree

            results = item_list(results_panel, "Kết quả tìm kiếm")
            chosen = item_list(chosen_panel, "Đã chọn cho combo")
            search_term = ""

            def load_results():
                try:
                    page = self.store.query_catalog(CatalogFilters(text=search_term), PageRequest(page_number.get(), 40))
                except Exception as exc:
                    messagebox.showerror("Combo", str(exc), parent=dialog)
                    return
                results.delete(*results.get_children())
                for item in page.items:
                    detail = item.show_title or (str(item.release_date.year) if item.release_date else "Phim lẻ")
                    if item.season_number is not None and item.episode_number is not None:
                        detail += f" • Mùa {item.season_number}, tập {item.episode_number}"
                    results.insert("", END, iid=str(item.item_id), text=item.title, values=(detail,))
                update_pager(page)

            def find(_event=None):
                nonlocal search_term
                search_term = search.get().strip()
                page_number.set(1)
                load_results()

            def add_selected():
                for row in results.selection():
                    if not chosen.exists(row):
                        chosen.insert("", END, iid=row, text=results.item(row, "text"),
                                      values=results.item(row, "values"))

            def remove_selected():
                chosen.delete(*chosen.selection())

            def save():
                try:
                    ids = [int(row) for row in chosen.get_children()]
                    self.store.create_fixed_combo(name.get(), ids, read_discount(discount), self.account.employee_id)
                except Exception as exc:
                    messagebox.showerror("Combo", str(exc), parent=dialog)
                    return
                dialog.destroy()
                refresh_promotions()
                messagebox.showinfo("Combo", "Đã tạo combo.", parent=self)

            ttk.Button(search_row, text="Tìm", command=find).pack(side=LEFT, padx=(6, 0))
            search_entry.bind("<Return>", find)
            ttk.Button(results_panel, text="Thêm vào combo", command=add_selected).pack(anchor="w", pady=(6, 0))
            ttk.Button(chosen_panel, text="Bỏ khỏi combo", command=remove_selected).pack(anchor="w", pady=(6, 0))
            update_pager = self._create_pager(results_panel, page_number, load_results)
            ttk.Button(footer, text="Lưu combo", command=save, bootstyle="primary").pack(side=RIGHT)
            load_results()

        management_state = "normal" if self._can_manage() else "disabled"
        ttk.Button(
            combo,
            text="Tạo combo cố định",
            command=create_combo,
            bootstyle="primary",
            state=management_state,
        ).pack(anchor="w", pady=(10, 0))

        def create_episode_combo():
            shows = self.store.list_shows()
            if not shows:
                messagebox.showinfo("Combo tập phim", "Chưa có phim bộ để chọn.", parent=self)
                return
            dialog, form, name, discount = combo_form("Tạo combo N tập cùng bộ", 620, 440)
            show_var, count = tk.StringVar(), tk.StringVar(value="2")
            show_ids = self._searchable_show_picker(form, shows, show_var)
            ttk.Label(form, text="Số tập tối thiểu:").pack(anchor="w", pady=(6, 0))
            ttk.Entry(form, textvariable=count).pack(fill=X, pady=(0, 6))

            def save():
                try:
                    show_id = show_ids.get(show_var.get())
                    if show_id is None:
                        raise ValueError("Hãy chọn một bộ phim.")
                    try:
                        required = int(count.get())
                    except ValueError as exc:
                        raise ValueError("Số tập tối thiểu phải là số nguyên.") from exc
                    self.store.create_show_episode_combo(name.get(), show_id, required, read_discount(discount),
                                                         self.account.employee_id)
                except Exception as exc:
                    messagebox.showerror("Combo tập phim", str(exc), parent=dialog)
                    return
                dialog.destroy()
                refresh_promotions()
                messagebox.showinfo("Combo tập phim", "Đã tạo combo theo số tập cùng bộ.", parent=self)

            ttk.Button(form, text="Lưu combo", command=save, bootstyle="primary").pack(anchor="e", pady=(6, 0))

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
            value = simpledialog.askstring(
                "Voucher", "Nhập phần trăm (vd 10) hoặc số tiền kèm 'd' (vd 20000d):", parent=self
            )
            if not value:
                return
            try:
                self.store.create_voucher_from_text(None, value, self.account.employee_id)
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
