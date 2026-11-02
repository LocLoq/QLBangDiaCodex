from __future__ import annotations

import csv
import tkinter as tk
from datetime import date
from tkinter import filedialog, messagebox, ttk

import ttkbootstrap as tb
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X

from normastore.application.services import (
    PageRequest,
    SortSpec,
)
from normastore.domain.enums import (
    CopyStatus,
)
from normastore.ui.formatting import vnd


class StatisticsPageMixin:
    def statistics_page(self, page) -> None:
        heading = self._heading(page, "Thống kê", "Doanh thu phát sinh tách hoàn toàn tiền cọc")
        period_var = tk.StringVar(value="Tháng này")
        start_var = tk.StringVar()
        end_var = tk.StringVar()
        ttk.Label(heading, text="Kỳ:").pack(side=LEFT)
        ttk.Combobox(
            heading,
            textvariable=period_var,
            values=("Tất cả", "Hôm nay", "Tháng này", "Quý này", "Năm nay", "Tùy chọn"),
            state="readonly",
            width=12,
        ).pack(side=LEFT, padx=(4, 8))
        ttk.Entry(heading, textvariable=start_var, width=11).pack(side=LEFT)
        ttk.Label(heading, text="đến").pack(side=LEFT, padx=3)
        ttk.Entry(heading, textvariable=end_var, width=11).pack(side=LEFT)
        stats = tk.StringVar()
        ttk.Label(page, textvariable=stats, font=("Segoe UI", 13), justify=LEFT).pack(
            anchor="w", pady=15
        )
        tables = ttk.PanedWindow(page, orient="horizontal")
        tables.pack(fill=BOTH, expand=True)
        top_frame = ttk.Frame(tables, padding=4)
        overdue_frame = ttk.Labelframe(tables, text="Khách hàng quá hạn", padding=8)
        stockout_frame = ttk.Labelframe(tables, text="Hết hàng & ETA", padding=8)
        tables.add(top_frame, weight=1)
        tables.add(overdue_frame, weight=1)
        tables.add(stockout_frame, weight=1)
        top_tabs = ttk.Notebook(top_frame)
        top_tabs.pack(fill=BOTH, expand=True)
        rental_tab, sale_tab, combo_tab, voucher_tab = (
            ttk.Frame(top_tabs, padding=6),
            ttk.Frame(top_tabs, padding=6),
            ttk.Frame(top_tabs, padding=6),
            ttk.Frame(top_tabs, padding=6),
        )
        top_tabs.add(rental_tab, text="Top thuê")
        top_tabs.add(sale_tab, text="Top bán")
        top_tabs.add(combo_tab, text="Top combo")
        top_tabs.add(voucher_tab, text="Top voucher")
        top_tree = self._create_treeview(
            rental_tab, columns=("count",), show="tree headings", height=11
        )
        top_tree.heading("#0", text="Phim / tập")
        top_tree.heading("count", text="Lượt thuê")
        top_tree.column("count", width=90, anchor="e")
        top_tree.pack(fill=BOTH, expand=True)
        sale_tree = self._create_treeview(
            sale_tab, columns=("count",), show="tree headings", height=11
        )
        sale_tree.heading("#0", text="Phim / tập")
        sale_tree.heading("count", text="Lượt bán")
        sale_tree.column("count", width=90, anchor="e")
        sale_tree.pack(fill=BOTH, expand=True)
        combo_tree = self._create_treeview(
            combo_tab, columns=("count",), show="tree headings", height=11
        )
        combo_tree.heading("#0", text="Combo")
        combo_tree.heading("count", text="Lượt dùng")
        combo_tree.column("count", width=90, anchor="e")
        combo_tree.pack(fill=BOTH, expand=True)
        voucher_tree = self._create_treeview(
            voucher_tab, columns=("count",), show="tree headings", height=11
        )
        voucher_tree.heading("#0", text="Voucher")
        voucher_tree.heading("count", text="Lượt dùng")
        voucher_tree.column("count", width=90, anchor="e")
        voucher_tree.pack(fill=BOTH, expand=True)
        overdue_tree = self._create_treeview(
            overdue_frame, columns=("count", "fee"), show="tree headings", height=11
        )
        overdue_tree.heading("#0", text="Khách hàng")
        overdue_tree.heading("count", text="Đĩa quá hạn")
        overdue_tree.heading("fee", text="Phạt hiện tại")
        overdue_tree.column("count", width=90, anchor="e")
        overdue_tree.column("fee", width=130, anchor="e")
        overdue_tree.pack(fill=BOTH, expand=True)
        stockout_tree = self._create_treeview(
            stockout_frame, columns=("eta",), show="tree headings", height=11
        )
        stockout_tree.heading("#0", text="Phim / tập")
        stockout_tree.heading("eta", text="ETA dự kiến")
        stockout_tree.column("eta", width=110, anchor="e")
        stockout_tree.pack(fill=BOTH, expand=True)
        chart_frame = ttk.Labelframe(page, text="Phân bổ tồn kho", padding=6)
        chart_frame.pack(fill=X, pady=(10, 0))
        figure = Figure(figsize=(7.8, 2.3), dpi=100)
        self._figures.append(figure)
        axis = figure.add_subplot(111)
        self._style_figure(figure)
        chart = FigureCanvasTkAgg(figure, master=chart_frame)
        chart.get_tk_widget().pack(fill=X)
        inventory_statuses = (
            CopyStatus.AVAILABLE,
            CopyStatus.RENTED,
            CopyStatus.INSPECTION,
            CopyStatus.REPAIR,
            CopyStatus.LOST,
            CopyStatus.RETIRED,
        )
        bar_statuses: dict[object, CopyStatus] = {}

        def open_inventory_drilldown(status: CopyStatus):
            dialog = tb.Toplevel(self)
            dialog.title(f"Kho: {status.value}")
            dialog.geometry("760x440")
            dialog.transient(self)
            label = ttk.Label(dialog, text="", font=self._font("section"))
            label.pack(anchor="w", padx=12, pady=(12, 6))
            tree = self._create_treeview(
                dialog, columns=("format", "condition", "rent", "buy"), show="tree headings"
            )
            tree.heading("#0", text="Barcode / phim")
            tree.heading("format", text="Định dạng")
            tree.heading("condition", text="Hiện trạng")
            tree.heading("rent", text="Cho thuê")
            tree.heading("buy", text="Cho mua")
            tree.column("#0", width=360)
            tree.pack(fill=BOTH, expand=True, padx=12, pady=(0, 12))
            copy_page = tk.IntVar(value=1)
            copy_sort: dict[str, object] = {"field": "barcode", "descending": False}

            def load_copies():
                tree.delete(*tree.get_children())
                result = self.call(
                    lambda s: s.query_inventory(
                        status,
                        PageRequest(copy_page.get(), 50),
                        SortSpec(str(copy_sort["field"]), bool(copy_sort["descending"])),
                    )
                )
                label.configure(
                    text=f"{result.total_items:,} bản đĩa trạng thái {status.value}".replace(
                        ",", "."
                    )
                )
                copy_pager(result)
                for copy in result.items:
                    tree.insert(
                        "",
                        END,
                        text=f"{copy.barcode} — {copy.title}",
                        values=(
                            copy.media_format,
                            copy.condition,
                            "Có" if copy.can_rent else "Không",
                            "Có" if copy.can_sell else "Không",
                        ),
                    )

            copy_pager = self._create_pager(dialog, copy_page, load_copies)
            self._install_sortable_headings(
                tree,
                {
                    "#0": "Barcode / phim",
                    "format": "Định dạng",
                    "condition": "Hiện trạng",
                    "rent": "Cho thuê",
                    "buy": "Cho mua",
                },
                copy_sort,
                lambda: (copy_page.set(1), load_copies()),
            )
            load_copies()

        def chart_click(event):
            status = bar_statuses.get(event.artist)
            if not status:
                return
            open_inventory_drilldown(status)

        figure.canvas.mpl_connect("pick_event", chart_click)

        def report_dates() -> tuple[date | None, date | None]:
            today = date.today()
            period = period_var.get()
            if period == "Tất cả":
                return None, None
            if period == "Hôm nay":
                return today, today
            if period == "Tháng này":
                return today.replace(day=1), today
            if period == "Quý này":
                first_month = (today.month - 1) // 3 * 3 + 1
                return today.replace(month=first_month, day=1), today
            if period == "Năm nay":
                return today.replace(month=1, day=1), today
            try:
                start = date.fromisoformat(start_var.get()) if start_var.get().strip() else None
                end = date.fromisoformat(end_var.get()) if end_var.get().strip() else None
            except ValueError as exc:
                raise ValueError("Ngày lọc phải theo dạng YYYY-MM-DD.") from exc
            if not start and not end:
                raise ValueError("Nhập ít nhất một ngày cho kỳ tùy chọn.")
            return start, end

        def current_report():
            start_on, end_on = report_dates()
            return self.call(lambda s: s.operational_report(start_on, end_on))

        def export_csv():
            path = filedialog.asksaveasfilename(
                parent=self,
                title="Xuất báo cáo NormaStore",
                defaultextension=".csv",
                filetypes=[("CSV", "*.csv")],
                initialfile="normastore-report.csv",
            )
            if not path:
                return
            try:
                report = current_report()
                with open(path, "w", newline="", encoding="utf-8-sig") as stream:
                    writer = csv.writer(stream)
                    writer.writerow(["Chỉ số", "Giá trị"])
                    for label, value in [
                        ("Doanh thu thuê phát sinh", report.rental_revenue),
                        ("Doanh thu bán phát sinh", report.sale_revenue),
                        ("Doanh thu Premium phát sinh", report.premium_revenue),
                        ("Tiền đã thu (gồm cọc)", report.cash_collected),
                        ("Tiền đã hoàn", report.cash_refunded),
                        ("Dòng tiền thuần (gồm cọc)", report.net_cash_flow),
                        ("Doanh thu trước giảm", report.gross_revenue),
                        ("Tổng giảm giá", report.discounts_granted),
                        ("Tỷ lệ giảm giá TB (%)", report.average_discount_rate),
                        ("Premium đang hiệu lực", report.active_premium_memberships),
                        ("Premium hết hạn", report.expired_premium_memberships),
                        ("Email đã gửi", report.email_notifications_sent),
                        ("SMS mock đã gửi", report.sms_notifications_sent),
                        ("Thông báo thất bại", report.notification_failures),
                        ("Phạt đã ghi nhận", report.penalties_assessed),
                        ("Hoàn hàng bán", report.sales_refunded),
                        ("Cọc đang giữ", report.deposits_held),
                        ("Có sẵn", report.available),
                        ("Đang thuê", report.rented),
                        ("Quá hạn", report.overdue_count),
                    ]:
                        writer.writerow([label, value])
                    writer.writerow([])
                    writer.writerow(["Top thuê", "Lượt"])
                    writer.writerows(report.top_rentals)
                    writer.writerow([])
                    writer.writerow(["Top bán", "Lượt"])
                    writer.writerows(report.top_sales)
                    writer.writerow([])
                    writer.writerow(["Top combo thuê", "Lượt"])
                    writer.writerows(report.top_combos)
                    writer.writerow([])
                    writer.writerow(["Top voucher", "Lượt"])
                    writer.writerows(report.top_vouchers)
                    writer.writerow([])
                    writer.writerow(["Item hết hàng", "ETA dự kiến"])
                    writer.writerows(
                        (
                            item.title,
                            item.estimated_available_on.isoformat()
                            if item.estimated_available_on
                            else "Chưa xác định",
                        )
                        for item in report.out_of_stock
                    )
                    writer.writerow([])
                    writer.writerow(["Item đặt trước", "Khách đang chờ"])
                    writer.writerows(report.waiting_reservations)
                    writer.writerow([])
                    writer.writerow(["Khách quá hạn", "Số đĩa", "Phạt hiện tại"])
                    writer.writerows(
                        (entry.customer_name, entry.rental_count, entry.overdue_amount)
                        for entry in report.overdue_customers
                    )
                messagebox.showinfo("Thống kê", "Đã xuất CSV thành công.", parent=self)
            except Exception as exc:
                messagebox.showerror("Thống kê", str(exc), parent=self)

        def export_chart():
            path = filedialog.asksaveasfilename(
                parent=self,
                title="Xuất biểu đồ tồn kho",
                defaultextension=".png",
                filetypes=[("PNG", "*.png")],
                initialfile="normastore-inventory.png",
            )
            if not path:
                return
            try:
                figure.savefig(path, dpi=160, bbox_inches="tight")
                messagebox.showinfo("Thống kê", "Đã xuất ảnh biểu đồ.", parent=self)
            except Exception as exc:
                messagebox.showerror("Thống kê", str(exc), parent=self)

        ttk.Button(heading, text="Áp dụng", command=lambda: refresh(), bootstyle="primary").pack(
            side=RIGHT, padx=5
        )
        ttk.Button(heading, text="Xuất CSV", command=export_csv, bootstyle="secondary").pack(
            side=RIGHT
        )
        ttk.Button(heading, text="Xuất ảnh", command=export_chart, bootstyle="secondary").pack(
            side=RIGHT, padx=5
        )

        def refresh():
            try:
                report = current_report()
            except Exception as exc:
                messagebox.showerror("Thống kê", str(exc), parent=self)
                return
            stats.set(
                f"Tài chính\n• Doanh thu thuê phát sinh: {vnd(report.rental_revenue)}  • Doanh thu bán phát sinh: {vnd(report.sale_revenue)}\n"
                f"• Doanh thu Premium phát sinh: {vnd(report.premium_revenue)}\n"
                f"• Tiền đã thu (gồm cọc): {vnd(report.cash_collected)}  • Tiền đã hoàn: {vnd(report.cash_refunded)}  • Dòng tiền thuần: {vnd(report.net_cash_flow)}\n"
                f"• Trước giảm: {vnd(report.gross_revenue)}  • Giảm giá: {vnd(report.discounts_granted)} ({report.average_discount_rate:.2f}%)\n"
                f"• Premium: {report.active_premium_memberships} đang hiệu lực, {report.expired_premium_memberships} hết hạn\n"
                f"• Khách Premium distinct: {report.premium_customer_count}  • Giảm theo nguồn: {', '.join(f'{name} {vnd(amount)}' for name, amount in report.discounts_by_source) or '—'}\n"
                f"• Thông báo: Email {report.email_notifications_sent}, SMS {report.sms_notifications_sent}, lỗi {report.notification_failures}\n"
                f"• Phạt đã ghi nhận: {vnd(report.penalties_assessed)}  • Hoàn hàng bán: {vnd(report.sales_refunded)}\n"
                f"• Cọc đang giữ: {vnd(report.deposits_held)}\n\n"
                f"Kho\n• Có sẵn: {report.available}  • Đang thuê: {report.rented}  • Chờ kiểm tra: {report.inspection}\n"
                f"• Sửa chữa: {report.repair}  • Mất: {report.lost}  • Ngưng khai thác: {report.retired}  • Quá hạn: {report.overdue_count}"
            )
            top_tree.delete(*top_tree.get_children())
            sale_tree.delete(*sale_tree.get_children())
            combo_tree.delete(*combo_tree.get_children())
            voucher_tree.delete(*voucher_tree.get_children())
            overdue_tree.delete(*overdue_tree.get_children())
            stockout_tree.delete(*stockout_tree.get_children())
            for title, count in report.top_rentals:
                top_tree.insert("", END, text=title, values=(count,))
            for title, count in report.top_sales:
                sale_tree.insert("", END, text=title, values=(count,))
            for name, count in report.top_combos:
                combo_tree.insert("", END, text=name, values=(count,))
            for name, count in report.top_vouchers:
                voucher_tree.insert("", END, text=name, values=(count,))
            for customer in report.overdue_customers:
                overdue_tree.insert(
                    "",
                    END,
                    text=customer.customer_name,
                    values=(customer.rental_count, vnd(customer.overdue_amount)),
                )
            for item in report.out_of_stock:
                eta = (
                    item.estimated_available_on.strftime("%d/%m/%Y")
                    if item.estimated_available_on
                    else "Chưa xác định"
                )
                stockout_tree.insert("", END, text=item.title, values=(eta,))
            axis.clear()
            self._style_figure(figure)
            labels = ["Có sẵn", "Đang thuê", "Kiểm tra", "Sửa chữa", "Mất", "Ngưng"]
            values = [
                report.available,
                report.rented,
                report.inspection,
                report.repair,
                report.lost,
                report.retired,
            ]
            bars = axis.bar(
                labels,
                values,
                color=["#2e8b57", "#3b82f6", "#f59e0b", "#ef4444", "#7c3aed", "#6b7280"],
            )
            bar_statuses.clear()
            bar_statuses.update(zip(bars, inventory_statuses))
            for bar in bars:
                bar.set_picker(True)
            axis.set_ylabel("Số bản đĩa")
            axis.set_title("Trạng thái tồn kho")
            figure.tight_layout()
            chart.draw_idle()

        page.refresh = refresh
