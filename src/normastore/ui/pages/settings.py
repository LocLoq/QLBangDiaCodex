from __future__ import annotations

import os
import tkinter as tk
from datetime import date, timedelta
from decimal import Decimal
from tkinter import messagebox, simpledialog, ttk

import keyring
from ttkbootstrap.constants import LEFT, X

from normastore.application.services import (
    MockSeedRequest,
    run_mock_seed,
)
from normastore.infrastructure.external import SmtpSender


class SettingsPageMixin:
    def settings_page(self, page) -> None:
        self._heading(page, "Cài đặt & About", "Kết nối, secret và attribution")
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
        source = (
            "biến môi trường"
            if os.environ.get("NORMASTORE_GEMINI_API_KEY")
            else (
                "Windows Credential Manager"
                if keyring.get_password("normastore", "gemini")
                else "chưa cấu hình"
            )
        )
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
                keyring.set_password("normastore", "gemini", value.strip())
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
                keyring.delete_password("normastore", "gemini")
            except keyring.errors.PasswordDeleteError:
                pass
            except Exception as exc:
                return messagebox.showerror("Gemini", str(exc), parent=self)
            messagebox.showinfo("Gemini", "Đã xóa key lưu cục bộ.", parent=self)

        def test_gemini():
            if not self._gemini_api_key():
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

            self.call_async(
                lambda s: s.search_by_description_response("phim gia đình"), done, failed
            )

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
            deposit_box = ttk.Labelframe(page, text="Tiền cọc mặc định theo định dạng", padding=12)
            deposit_box.pack(fill=X, pady=(14, 0))
            defaults = self.call(lambda s: s.deposit_defaults())
            values = {
                name: tk.StringVar(value=str(defaults[name]))
                for name in ("VHS", "VCD", "DVD", "Blu-ray")
            }
            for column, name in enumerate(values):
                ttk.Label(deposit_box, text=name).grid(row=0, column=column, padx=5, sticky="w")
                ttk.Entry(deposit_box, textvariable=values[name], width=13).grid(
                    row=1, column=column, padx=5, sticky="ew"
                )
                deposit_box.columnconfigure(column, weight=1)
            deposit_actions = ttk.Frame(deposit_box)
            deposit_actions.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))

            def parsed_defaults():
                return {
                    name: Decimal(variable.get().replace(".", "").replace(",", "."))
                    for name, variable in values.items()
                }

            def save_defaults():
                try:
                    self.call(
                        lambda s: s.save_deposit_defaults(
                            parsed_defaults(), self.account.employee_id
                        ),
                        True,
                    )
                    messagebox.showinfo("Tiền cọc", "Đã lưu mức cọc theo định dạng.", parent=self)
                except Exception as exc:
                    messagebox.showerror("Tiền cọc", str(exc), parent=self)

            def apply_defaults():
                if not messagebox.askyesno(
                    "Tiền cọc",
                    "Ghi đè cọc override của toàn bộ đĩa? Phiếu đã lập không thay đổi.",
                    parent=self,
                ):
                    return
                try:
                    self.call(
                        lambda s: s.save_deposit_defaults(
                            parsed_defaults(), self.account.employee_id
                        ),
                        True,
                    )
                    count = self.call(
                        lambda s: s.apply_deposit_defaults_to_inventory(self.account.employee_id),
                        True,
                    )
                    messagebox.showinfo("Tiền cọc", f"Đã áp dụng cho {count} bản đĩa.", parent=self)
                except Exception as exc:
                    messagebox.showerror("Tiền cọc", str(exc), parent=self)

            ttk.Button(
                deposit_actions, text="Lưu mức cọc", command=save_defaults, bootstyle="secondary"
            ).pack(side=LEFT)
            ttk.Button(
                deposit_actions,
                text="Áp dụng toàn kho",
                command=apply_defaults,
                bootstyle="warning",
            ).pack(side=LEFT, padx=6)
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
                    lambda: run_mock_seed(
                        self.factory,
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
            password = keyring.get_password("normastore", "smtp")
            if not (
                settings.smtp_host and settings.smtp_username and settings.smtp_from and password
            ):
                return messagebox.showerror(
                    "SMTP",
                    "Cần host, username, email gửi và App Password trong Windows Credential Manager.",
                    parent=self,
                )

            def send():
                try:
                    SmtpSender(
                        settings.smtp_host,
                        settings.smtp_port,
                        settings.smtp_username,
                        password,
                        settings.smtp_starttls,
                    ).send(
                        settings.smtp_from,
                        settings.smtp_from,
                        "NormaStore SMTP test",
                        "SMTP NormaStore đã cấu hình thành công.",
                    )
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
