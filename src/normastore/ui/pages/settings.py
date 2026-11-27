from __future__ import annotations

import tkinter as tk
from datetime import date, timedelta
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

from ttkbootstrap.constants import LEFT, X

from normastore.application.contracts import MockSeedRequest


class SettingsPageMixin:
    def settings_page(self, page) -> None:
        self._heading(page, "Cài đặt & Giới thiệu", "Kết nối, khóa truy cập và thông tin nguồn")
        ttk.Label(
            page,
            text=f"Database: {self.settings.database_url}\n\nTMDB/Gemini/SMTP không được hard-code. Đặt biến môi trường NORMASTORE_* hoặc lưu secret bằng Windows Credential Manager.\n\nThis product uses the TMDB API but is not endorsed or certified by TMDB.",
            justify=LEFT,
            wraplength=850,
        ).pack(anchor="w", pady=12)
        ttk.Label(
            page,
            text="Khóa API đã từng gửi qua chat cần được đổi trước khi import dữ liệu thật.",
            bootstyle="danger",
        ).pack(anchor="w")
        gemini_box = ttk.Labelframe(page, text="Gemini", padding=12)
        gemini_box.pack(fill=X, pady=(14, 0))
        source = self.store.gemini_key_source()
        ttk.Label(
            gemini_box, text=f"Nguồn key hiện tại: {source}. Key không được hiển thị lại."
        ).pack(anchor="w")
        gemini_actions = ttk.Frame(gemini_box)
        gemini_actions.pack(fill=X, pady=(8, 0))

        def save_gemini():
            value = simpledialog.askstring(
                "Gemini API key",
                "Nhập Gemini API key để lưu trong Windows Credential Manager:",
                show="•",
                parent=self,
            )
            if not value:
                return
            try:
                self.store.save_gemini_key(value)
                messagebox.showinfo(
                    "Gemini", "Đã lưu key trong Windows Credential Manager.", parent=self
                )
            except Exception as exc:
                messagebox.showerror("Gemini", str(exc), parent=self)

        def delete_gemini():
            if not messagebox.askyesno(
                "Gemini", "Xóa Gemini key đã lưu trong Credential Manager?", parent=self
            ):
                return
            try:
                self.store.delete_gemini_key()
            except Exception as exc:
                return messagebox.showerror("Gemini", str(exc), parent=self)
            messagebox.showinfo("Gemini", "Đã xóa key lưu cục bộ.", parent=self)

        def test_gemini():
            if not self.store.has_gemini_key():
                return messagebox.showerror("Gemini", "Chưa có Gemini API key.", parent=self)
            test_button.configure(state="disabled", text="Đang kiểm tra…")

            def done(response):
                test_button.configure(state="normal", text="Kiểm tra Gemini")
                messagebox.showinfo(
                    "Gemini",
                    "Gemini sẵn sàng."
                    if response.mode == "GEMINI"
                    else (response.warning or "Đang dùng fallback nội bộ."),
                    parent=self,
                )

            def failed(_exc):
                test_button.configure(state="normal", text="Kiểm tra Gemini")
                messagebox.showerror(
                    "Gemini",
                    "Không thể kết nối Gemini; ứng dụng vẫn dùng fallback nội bộ.",
                    parent=self,
                )

            self._run_async(lambda: self.store.search_by_description_response('phim gia đình'), done, failed)

        ttk.Button(gemini_actions, text="Lưu key", command=save_gemini, bootstyle="secondary").pack(
            side=LEFT
        )
        ttk.Button(
            gemini_actions, text="Xóa key", command=delete_gemini, bootstyle="secondary"
        ).pack(side=LEFT, padx=6)
        test_button = ttk.Button(
            gemini_actions, text="Kiểm tra Gemini", command=test_gemini, bootstyle="primary"
        )
        test_button.pack(side=LEFT)

        if self._can_manage():
            premium_box = ttk.Labelframe(page, text="Hội viên Premium", padding=12)
            premium_box.pack(fill=X, pady=(14, 0))
            settings = self.store.premium_settings()
            merchandise = tk.StringVar(value=str(settings.merchandise_percent))
            deposit_discount = tk.StringVar(value=str(settings.deposit_percent))
            ttk.Label(premium_box, text="Giảm tiền hàng (%)").grid(row=0, column=0, sticky="w")
            ttk.Entry(premium_box, textvariable=merchandise, width=9).grid(row=0, column=1, padx=5)
            ttk.Label(premium_box, text="Giảm tiền cọc (%)").grid(row=0, column=2, padx=(10, 0))
            ttk.Entry(premium_box, textvariable=deposit_discount, width=9).grid(row=0, column=3, padx=5)

            def save_benefits():
                try:
                    self.store.save_premium_settings(Decimal(merchandise.get().replace(",", ".")),
                                                     Decimal(deposit_discount.get().replace(",", ".")),
                                                     self.account.employee_id)
                    messagebox.showinfo("Hội viên", "Đã lưu ưu đãi.", parent=self)
                except Exception as exc:
                    messagebox.showerror("Hội viên", str(exc), parent=self)

            ttk.Button(premium_box, text="Lưu ưu đãi", command=save_benefits).grid(row=0, column=4, padx=6)
            plans = self._create_treeview(premium_box, columns=("price", "active"), show="tree headings", height=3)
            plans.heading("#0", text="Kỳ hạn (ngày)")
            plans.heading("price", text="Giá (đồng)")
            plans.heading("active", text="Đang bán")
            plans.grid(row=1, column=0, columnspan=5, sticky="ew", pady=6)

            def refresh_plans():
                plans.delete(*plans.get_children())
                for plan in self.store.premium_plans(True):
                    plans.insert("", "end", iid=str(plan.days), text=str(plan.days),
                                 values=(str(plan.price), "Có" if plan.active else "Không"))

            def edit_plan():
                selected = plans.selection()
                current = next((plan for plan in self.store.premium_plans(True)
                                if selected and plan.days == int(selected[0])), None)
                days = simpledialog.askinteger("Gói hội viên", "Kỳ hạn (ngày)", initialvalue=current.days if current else 30, parent=self)
                if days is None:
                    return
                price = simpledialog.askstring("Gói hội viên", "Giá (đồng)", initialvalue=str(current.price) if current else "59000", parent=self)
                if price is None:
                    return
                try:
                    if (not current or current.days != days) and any(plan.days == days for plan in self.store.premium_plans(True)):
                        raise ValueError("Kỳ hạn đã tồn tại. Hãy chọn gói để sửa.")
                    self.store.save_premium_plan(days, Decimal(price), current.active if current else True,
                                                 self.account.employee_id, current.days if current else None)
                    refresh_plans()
                except Exception as exc:
                    messagebox.showerror("Gói hội viên", str(exc), parent=self)

            def toggle_plan():
                selected = plans.selection()
                if not selected:
                    return
                plan = next(plan for plan in self.store.premium_plans(True) if plan.days == int(selected[0]))
                try:
                    self.store.save_premium_plan(plan.days, plan.price, not plan.active, self.account.employee_id)
                    refresh_plans()
                except Exception as exc:
                    messagebox.showerror("Gói hội viên", str(exc), parent=self)

            ttk.Button(premium_box, text="Thêm / sửa gói", command=edit_plan).grid(row=2, column=0, sticky="w")
            ttk.Button(premium_box, text="Bật / ngừng bán", command=toggle_plan).grid(row=2, column=1, columnspan=2, sticky="w")
            refresh_plans()
            deposit_box = ttk.Labelframe(page, text="Tỷ lệ tiền cọc", padding=12)
            deposit_box.pack(fill=X, pady=(14, 0))
            deposit_percent = tk.StringVar(value=str(self.store.deposit_percent()))
            ttk.Label(deposit_box, text="% giá bán của đĩa (trước khuyến mãi)").pack(side=LEFT)
            ttk.Entry(deposit_box, textvariable=deposit_percent, width=10).pack(side=LEFT, padx=8)

            def save_deposit_percent():
                try:
                    value = Decimal(deposit_percent.get().strip().replace(",", "."))
                    self.store.save_deposit_percent(value, self.account.employee_id)
                    messagebox.showinfo("Tiền cọc", "Đã lưu tỷ lệ cọc.", parent=self)
                except Exception as exc:
                    messagebox.showerror("Tiền cọc", str(exc), parent=self)

            ttk.Button(deposit_box, text="Lưu", command=save_deposit_percent).pack(side=LEFT)
            mock_box = ttk.Labelframe(page, text="Dữ liệu mock", padding=12)
            mock_box.pack(fill=X, pady=(14, 0))
            ttk.Label(
                mock_box,
                text="Tạo tối đa 250 phiếu/ngày, 31 ngày/lần. Ngày đã chạy sẽ tự bỏ qua.",
                bootstyle="secondary",
            ).pack(anchor="w")
            mock_status = tk.StringVar(value="Chưa chạy dữ liệu mock.")
            ttk.Label(mock_box, textvariable=mock_status, bootstyle="secondary").pack(
                anchor="w", pady=(4, 0)
            )

            def run_mock():
                default_start = (date.today() - timedelta(days=19)).isoformat()
                start_text = simpledialog.askstring(
                    "Dữ liệu mock", "Từ ngày (YYYY-MM-DD):", initialvalue=default_start, parent=self
                )
                end_text = (
                    simpledialog.askstring(
                        "Dữ liệu mock",
                        "Đến ngày (YYYY-MM-DD):",
                        initialvalue=date.today().isoformat(),
                        parent=self,
                    )
                    if start_text
                    else None
                )
                if not end_text:
                    return
                try:
                    start_on, end_on = date.fromisoformat(start_text), date.fromisoformat(end_text)
                except ValueError:
                    return messagebox.showerror(
                        "Dữ liệu mock", "Ngày phải theo YYYY-MM-DD.", parent=self
                    )
                if not messagebox.askyesno(
                    "Dữ liệu mock",
                    f"Tạo tối đa {(end_on - start_on).days + 1} × 250 phiếu?",
                    parent=self,
                ):
                    return
                mock_button.configure(state="disabled", text="Đang tạo mock…")
                mock_status.set("Đang chuẩn bị fixture Combo, Voucher và Premium…")

                def done(result):
                    mock_button.configure(state="normal", text="Cập nhật dữ liệu mock")
                    summary = (
                        f"Đã tạo {result.orders_created} phiếu trên {result.created_days} ngày; bỏ qua {result.skipped_days} ngày.\n"
                        f"Fixture mới: {result.combos_created} Combo, {result.vouchers_created} Voucher, {result.memberships_created} Premium."
                    )
                    if result.failed_on:
                        summary += f"\nDừng tại {result.failed_on}: {result.error}"
                        mock_status.set(f"Ngày {result.failed_on} chưa được ghi, có thể chạy lại.")
                    else:
                        mock_status.set("Hoàn tất; ngày đã tạo sẽ được tự bỏ qua khi chạy lại.")
                    for name in ("Combo / Voucher", "Lập phiếu", "Thống kê"):
                        refresh = getattr(self.pages.get(name), "refresh", None)
                        if refresh:
                            refresh()
                    messagebox.showinfo("Dữ liệu mock", summary, parent=self)

                def failed(exc):
                    mock_button.configure(state="normal", text="Cập nhật dữ liệu mock")
                    mock_status.set("Không thể tạo fixture mock.")
                    messagebox.showerror("Dữ liệu mock", str(exc), parent=self)

                def progress(completed, total):
                    self.after(0, lambda: mock_status.set(f"Đang xử lý ngày {completed}/{total}…"))

                self._run_async(
                    lambda: self.store.run_mock_seed(
                        MockSeedRequest(start_on, end_on, self.account.employee_id),
                        progress,
                    ),
                    done,
                    failed,
                )

            mock_button = ttk.Button(
                mock_box, text="Cập nhật dữ liệu mock", command=run_mock, bootstyle="warning"
            )
            mock_button.pack(anchor="w", pady=(8, 0))

        def test_smtp():
            settings = self.settings
            def send():
                try:
                    self.store.send_test_email()
                except Exception as exc:
                    error_message = str(exc)
                    self.after(0, lambda: messagebox.showerror("SMTP", error_message, parent=self))
                else:
                    self.after(
                        0,
                        lambda: messagebox.showinfo(
                            "SMTP", f"Đã gửi email kiểm tra đến {settings.smtp_from}.", parent=self
                        ),
                    )

            self.executor.submit(send)

        ttk.Button(page, text="Gửi email kiểm tra", command=test_smtp, bootstyle="secondary").pack(
            anchor="w", pady=(14, 0)
        )
