from __future__ import annotations

import csv
import tkinter as tk
from bisect import bisect_left
from datetime import date, datetime
from tkinter import filedialog, messagebox, ttk

import ttkbootstrap as tb
from ttkbootstrap.constants import BOTH, END, LEFT, RIGHT, X
from ttkbootstrap.widgets.scrolled import ScrolledFrame

from normastore.application.contracts import PageRequest, SortSpec
from normastore.domain.enums import (
    CopyStatus,
    LineAction,
)
from normastore.ui.formatting import vnd
from normastore.ui.pages.inventory import CONDITION_LABELS, STATUS_LABELS


class StatisticsPageMixin:
    def statistics_page(self, page) -> None:
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.dates import date2num
        from matplotlib.figure import Figure

        root_page = page
        heading = self._heading(page, "Thống kê", "Doanh thu phát sinh tách hoàn toàn tiền cọc")
        period_var = tk.StringVar(value="Tháng này")
        ttk.Label(heading, text="Kỳ:").pack(side=LEFT)
        ttk.Combobox(
            heading,
            textvariable=period_var,
            values=("Tất cả", "Hôm nay", "Tháng này", "Quý này", "Năm nay", "Tùy chọn"),
            state="readonly",
            width=12,
        ).pack(side=LEFT, padx=(4, 8))
        start_entry = tb.DateEntry(heading, dateformat="%d/%m/%Y", popup_title="Từ ngày", width=10)
        start_entry.entry.delete(0, END)
        start_entry.pack(side=LEFT)
        ttk.Label(heading, text="đến").pack(side=LEFT, padx=3)
        end_entry = tb.DateEntry(heading, dateformat="%d/%m/%Y", popup_title="Đến ngày", width=10)
        end_entry.entry.delete(0, END)
        end_entry.pack(side=LEFT)
        sections = ttk.Notebook(root_page)
        sections.pack(fill=BOTH, expand=True)
        overview_tab, finance_tab, inventory_tab = (ttk.Frame(sections) for _ in range(3))
        for tab, title in ((overview_tab, "Tổng quan"), (finance_tab, "Tài chính"), (inventory_tab, "Kho")):
            sections.add(tab, text=title)
        page = ScrolledFrame(overview_tab, autohide=False)
        page.pack(fill=BOTH, expand=True)
        finance_page = ScrolledFrame(finance_tab, autohide=False)
        finance_page.pack(fill=BOTH, expand=True)
        inventory_page = ScrolledFrame(inventory_tab, autohide=False)
        inventory_page.pack(fill=BOTH, expand=True)
        filters = ttk.Frame(page, padding=(0, 5))
        filters.pack(fill=X)
        action_var = tk.StringVar(value="Tất cả giao dịch")
        ttk.Label(filters, text="Loại giao dịch:").pack(side=LEFT)
        ttk.Combobox(filters, textvariable=action_var, values=("Tất cả giao dịch", "Thuê", "Mua"), state="readonly", width=18).pack(side=LEFT, padx=6)
        genres = {"Tất cả thể loại": None}
        genres.update({genre.name: genre.id for genre in self.store.list_genres()})
        genre_var = tk.StringVar(value="Tất cả thể loại")
        ttk.Label(filters, text="Thể loại:").pack(side=LEFT, padx=(10, 0))
        genre_control = ttk.Combobox(filters, textvariable=genre_var, values=tuple(genres), state="readonly", width=22)
        genre_control.pack(side=LEFT, padx=6)
        ttk.Label(page, text="Biểu đồ phim theo bộ lọc; chỉ số cửa hàng theo kỳ, tồn kho là trạng thái hiện tại.", bootstyle="secondary").pack(anchor="w")
        stats = tk.StringVar()
        stats_label = ttk.Label(finance_page, textvariable=stats, font=("Segoe UI", 13), justify=LEFT)
        stats_label.pack(anchor="w")
        finance_figure = Figure(figsize=(11, 14), dpi=100)
        finance_axes = finance_figure.subplots(4, 2).flat
        finance_axes = list(finance_axes)
        finance_chart = FigureCanvasTkAgg(finance_figure, master=finance_page)
        finance_chart.get_tk_widget().pack(fill=X)
        inventory_stats = tk.StringVar()
        ttk.Label(inventory_page, textvariable=inventory_stats, justify=LEFT).pack(anchor="w", pady=8)
        tables = ttk.PanedWindow(page, orient="horizontal")
        tables.pack(fill=BOTH, expand=True)
        top_frame = ttk.Frame(tables, padding=4)
        overdue_frame = ttk.Labelframe(tables, text="Khách hàng quá hạn", padding=8)
        stockout_frame = ttk.Labelframe(inventory_page, text="Hết hàng và ngày dự kiến có lại", padding=8)
        tables.add(top_frame, weight=1)
        tables.add(overdue_frame, weight=1)
        stockout_frame.pack(fill=BOTH, expand=True, pady=8)
        top_tabs = ttk.Notebook(top_frame)
        top_tabs.pack(fill=BOTH, expand=True)
        rental_tab, sale_tab, customer_tab, combo_tab, voucher_tab = (
            ttk.Frame(top_tabs, padding=6),
            ttk.Frame(top_tabs, padding=6),
            ttk.Frame(top_tabs, padding=6),
            ttk.Frame(top_tabs, padding=6),
            ttk.Frame(top_tabs, padding=6),
        )
        top_tabs.add(rental_tab, text="Top thuê")
        top_tabs.add(sale_tab, text="Top bán")
        top_tabs.add(customer_tab, text="Top khách hàng")
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
        ttk.Label(customer_tab, text="Theo giá trị hóa đơn sau giảm, không gồm cọc", bootstyle="secondary").pack(anchor="w")
        customer_tree = self._create_treeview(
            customer_tab, columns=("phone", "orders", "total"), show="tree headings", height=11
        )
        for column, title in (("#0", "Khách hàng"), ("phone", "SĐT"),
                              ("orders", "Số phiếu"), ("total", "Giá trị hóa đơn")):
            customer_tree.heading(column, text=title)
        customer_tree.column("#0", width=160, minwidth=100)
        customer_tree.column("phone", width=100, minwidth=85)
        customer_tree.column("orders", width=75, minwidth=60, anchor="e")
        customer_tree.column("total", width=140, minwidth=100, anchor="e")
        customer_tree.pack(fill=BOTH, expand=True)
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
        stockout_tree.heading("eta", text="Ngày có lại dự kiến")
        stockout_tree.column("eta", width=110, anchor="e")
        stockout_tree.pack(fill=BOTH, expand=True)
        chart_frame = ttk.Labelframe(inventory_page, text="Phân bổ tồn kho", padding=6)
        chart_frame.pack(fill=X, pady=(10, 0))
        figure = Figure(figsize=(7.8, 4), dpi=100)
        self._figures.append(figure)
        axis = figure.add_subplot(111)
        self._style_figure(figure)
        chart = FigureCanvasTkAgg(figure, master=chart_frame)
        chart.get_tk_widget().pack(fill=X)
        analysis_frame = ttk.Labelframe(page, text="Phân tích theo bộ lọc", padding=6)
        analysis_frame.pack(fill=X, pady=(10, 0))
        analysis_figure = Figure(figsize=(8, 4), dpi=100)
        self._figures.append(analysis_figure)
        genre_axis = analysis_figure.add_subplot(111)
        analysis_chart = FigureCanvasTkAgg(analysis_figure, master=analysis_frame)
        analysis_chart.get_tk_widget().pack(fill=X)
        revenue_figure = Figure(figsize=(9, 4), dpi=100)
        self._figures.append(revenue_figure)
        revenue_axis = revenue_figure.add_subplot(111)
        revenue_chart = FigureCanvasTkAgg(revenue_figure, master=finance_page)
        revenue_chart.get_tk_widget().pack(fill=X)
        damage_figure = Figure(figsize=(8, 4), dpi=100)
        self._figures.append(damage_figure)
        damage_axis = damage_figure.add_subplot(111)
        damage_chart = FigureCanvasTkAgg(damage_figure, master=inventory_page)
        damage_chart.get_tk_widget().pack(fill=X)
        self._figures.append(finance_figure)
        revenue_points: list[tuple[float, str]] = []
        revenue_tooltip = None
        hovered_day: float | None = None

        def hide_revenue_tooltip(_event=None):
            nonlocal hovered_day
            hovered_day = None
            if revenue_tooltip is not None and revenue_tooltip.get_visible():
                revenue_tooltip.set_visible(False)
                revenue_chart.draw_idle()

        def hover_revenue(event):
            nonlocal hovered_day
            if (event.inaxes is not revenue_axis or event.xdata is None or event.ydata is None
                    or not revenue_points or revenue_tooltip is None):
                hide_revenue_tooltip()
                return
            index = bisect_left(revenue_points, event.xdata, key=lambda point: point[0])
            candidates = revenue_points[max(0, index - 1):index + 1]
            day, text = min(candidates, key=lambda point: abs(point[0] - event.xdata))
            if day == hovered_day:
                return
            hovered_day = day
            bounds = revenue_axis.bbox
            left_side = bounds.x1 - event.x < 205
            below = bounds.y1 - event.y < 65
            revenue_tooltip.xy = event.xdata, event.ydata
            revenue_tooltip.set_position((-10 if left_side else 10, -10 if below else 10))
            revenue_tooltip.set_ha("right" if left_side else "left")
            revenue_tooltip.set_va("top" if below else "bottom")
            revenue_tooltip.set_text(text)
            revenue_tooltip.set_color(self._palette.tooltip_foreground)
            revenue_tooltip.get_bbox_patch().set_facecolor(self._palette.tooltip_background)
            revenue_tooltip.set_visible(True)
            revenue_chart.draw_idle()

        revenue_chart.mpl_connect("motion_notify_event", hover_revenue)
        revenue_chart.mpl_connect("figure_leave_event", hide_revenue_tooltip)
        revenue_chart.mpl_connect("scroll_event", hide_revenue_tooltip)
        revenue_chart.get_tk_widget().bind("<Unmap>", hide_revenue_tooltip, add="+")
        for canvas, scroll_page in ((chart, inventory_page), (damage_chart, inventory_page),
                                    (analysis_chart, page), (revenue_chart, finance_page),
                                    (finance_chart, finance_page)):
            def scroll_chart(event, target=scroll_page):
                target.yview_scroll(-int(event.delta / 120), "units")
                return "break"
            canvas.get_tk_widget().bind("<MouseWheel>", scroll_chart)
        table_wheel_tag = f"NormaStatsTableWheel{id(root_page)}"

        def scroll_table(event):
            if event.num in (4, 5):
                step = -1 if event.num == 4 else 1
            else:
                step = -int(event.delta / 120)
            event.widget.yview_scroll(step, "units")
            return "break"

        for sequence in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            root_page.bind_class(table_wheel_tag, sequence, scroll_table)
        for table in (top_tree, sale_tree, customer_tree, combo_tree, voucher_tree, overdue_tree, stockout_tree):
            table.bindtags((table_wheel_tag, *table.bindtags()))
        inventory_statuses = (
            CopyStatus.AVAILABLE,
            CopyStatus.HELD,
            CopyStatus.RENTED,
            CopyStatus.INSPECTION,
            CopyStatus.REPAIR,
            CopyStatus.LOST,
            CopyStatus.RETIRED,
        )
        bar_statuses: dict[object, CopyStatus] = {}

        def open_inventory_drilldown(status: CopyStatus):
            dialog = tb.Toplevel(self)
            dialog.title(f"Kho: {STATUS_LABELS[status]}")
            dialog.geometry("760x440")
            dialog.transient(self)
            label = ttk.Label(dialog, text="", font=self._font("section"))
            label.pack(anchor="w", padx=12, pady=(12, 6))
            tree = self._create_treeview(
                dialog, columns=("format", "condition", "percent", "location", "rent", "buy"), show="tree headings"
            )
            tree.heading("#0", text="Mã vạch / phim")
            tree.heading("format", text="Định dạng")
            tree.heading("condition", text="Hiện trạng")
            tree.heading("percent", text="Tình trạng (%)")
            tree.heading("location", text="Dãy / Kệ / Ngăn")
            tree.heading("rent", text="Cho thuê")
            tree.heading("buy", text="Cho mua")
            tree.column("#0", width=360)
            tree.pack(fill=BOTH, expand=True, padx=12, pady=(0, 12))
            copy_page = tk.IntVar(value=1)
            copy_sort: dict[str, object] = {"field": "barcode", "descending": False}

            def load_copies():
                tree.delete(*tree.get_children())
                result = self.store.query_inventory(status, PageRequest(copy_page.get(), 50), SortSpec(str(copy_sort['field']), bool(copy_sort['descending'])))
                label.configure(
                    text=f"{result.total_items:,} bản đĩa trạng thái {STATUS_LABELS[status]}".replace(
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
                            CONDITION_LABELS[copy.condition],
                            f"{copy.condition_percent}%",
                            " / ".join(value or "—" for value in (copy.aisle, copy.rack, copy.compartment)),
                            "Có" if copy.can_rent else "Không",
                            "Có" if copy.can_sell else "Không",
                        ),
                    )

            copy_pager = self._create_pager(dialog, copy_page, load_copies)
            self._install_sortable_headings(
                tree,
                {
                    "#0": "Mã vạch / phim",
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
                start = datetime.strptime(start_entry.entry.get().strip(), "%d/%m/%Y").date() if start_entry.entry.get().strip() else None
                end = datetime.strptime(end_entry.entry.get().strip(), "%d/%m/%Y").date() if end_entry.entry.get().strip() else None
            except ValueError as exc:
                raise ValueError("Ngày lọc phải theo dạng ngày/tháng/năm.") from exc
            if not start and not end:
                raise ValueError("Nhập ít nhất một ngày cho kỳ tùy chọn.")
            return start, end

        def current_report():
            start_on, end_on = report_dates()
            return self.store.operational_report(start_on, end_on)

        def current_charts():
            start_on, end_on = report_dates()
            action = {"Tất cả giao dịch": None, "Thuê": LineAction.RENT, "Mua": LineAction.BUY}[action_var.get()]
            return self.store.chart_report(start_on, end_on, action, genres[genre_var.get()])

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
                chart_data = current_charts()
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
                        ("SMS mô phỏng đã gửi", report.sms_notifications_sent),
                        ("Thông báo thất bại", report.notification_failures),
                        ("Phạt đã ghi nhận", report.penalties_assessed),
                        ("Hoàn hàng bán", report.sales_refunded),
                        ("Cọc đang giữ", report.deposits_held),
                        ("Có sẵn", report.available),
                        ("Đang giữ", report.held),
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
                    writer.writerow(["Top khách hàng", "SĐT", "Số phiếu", "Giá trị hóa đơn sau giảm, không gồm cọc"])
                    writer.writerows((customer.customer_name, customer.phone, customer.order_count, customer.total)
                                     for customer in report.top_customers)
                    writer.writerow([])
                    writer.writerow(["Top combo thuê", "Lượt"])
                    writer.writerows(report.top_combos)
                    writer.writerow([])
                    writer.writerow(["Top voucher", "Lượt"])
                    writer.writerows(report.top_vouchers)
                    writer.writerow([])
                    writer.writerow(["Phim hết hàng", "Ngày có lại dự kiến"])
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
                    writer.writerow(["Phim đặt trước", "Khách đang chờ"])
                    writer.writerows(report.waiting_reservations)
                    writer.writerow([])
                    writer.writerow(["Khách quá hạn", "Số đĩa", "Phạt hiện tại"])
                    writer.writerows(
                        (entry.customer_name, entry.rental_count, entry.overdue_amount)
                        for entry in report.overdue_customers
                    )
                    writer.writerow([])
                    writer.writerow(["Ngày", "Loại", "Doanh thu phim sau giảm, không gồm cọc"])
                    writer.writerows((day, "Thuê" if action == LineAction.RENT else "Mua", value) for day, action, value in chart_data.revenue)
                    writer.writerow([])
                    writer.writerow(["Hỏng hóc khi trả", "Số lượt"])
                    damage_labels = {"LIGHT_DAMAGE": "Hư nhẹ khi trả thuê", "HEAVY_DAMAGE": "Hư nặng khi trả thuê", "LOST": "Mất", "SALE_WORN": "Mòn khi hoàn bán", "SALE_DAMAGED": "Hư khi hoàn bán"}
                    writer.writerows((damage_labels.get(name, name), count) for name, count in chart_data.damages)
                    writer.writerow([])
                    writer.writerow(["Thể loại bán chạy", "Số lượt bán"])
                    writer.writerows(chart_data.genres)
                messagebox.showinfo("Thống kê", "Đã xuất CSV thành công.", parent=self)
            except Exception as exc:
                messagebox.showerror("Thống kê", str(exc), parent=self)

        def export_chart():
            path = filedialog.asksaveasfilename(
                parent=self,
                title="Xuất biểu đồ phân tích",
                defaultextension=".png",
                filetypes=[("PNG", "*.png")],
                initialfile="normastore-phan-tich.png",
            )
            if not path:
                return
            try:
                hide_revenue_tooltip()
                selected_figure = (analysis_figure, revenue_figure, figure)[sections.index(sections.select())]
                selected_figure.savefig(path, dpi=160, bbox_inches="tight")
                messagebox.showinfo("Thống kê", "Đã xuất ảnh biểu đồ.", parent=self)
            except Exception as exc:
                messagebox.showerror("Thống kê", str(exc), parent=self)

        ttk.Button(heading, text="Áp dụng", command=lambda: refresh(), bootstyle="primary").pack(
            side=RIGHT, padx=5
        )
        csv_button = ttk.Button(heading, text="Xuất CSV", command=export_csv, bootstyle="secondary")
        csv_button.pack(side=RIGHT)
        chart_button = ttk.Button(heading, text="Xuất ảnh", command=export_chart, bootstyle="secondary")
        chart_button.pack(side=RIGHT, padx=5)
        refresh_generation = {"value": 0}

        def render(result):
            nonlocal hovered_day, revenue_tooltip
            report, chart_data = result
            discount_labels = {"DISCOVERY": "Khám phá", "COMBO": "Combo", "PREMIUM": "Hội viên", "VOUCHER": "Voucher"}
            stats.set("")
            groups = (
                ("Doanh thu phát sinh", (("Thuê", report.rental_revenue), ("Bán", report.sale_revenue), ("Premium", report.premium_revenue)), True),
                ("Dòng tiền (gồm cọc)", (("Đã thu", report.cash_collected), ("Đã hoàn", report.cash_refunded), ("Thuần", report.net_cash_flow)), True),
                (f"Giá trị và giảm giá ({report.average_discount_rate:.2f}%)", (("Trước giảm", report.gross_revenue), ("Giảm giá", report.discounts_granted)), True),
                ("Giảm giá theo nguồn", tuple((discount_labels.get(name, name), amount) for name, amount in report.discounts_by_source), True),
                ("Phạt, hoàn hàng và cọc", (("Phạt ghi nhận", report.penalties_assessed), ("Hoàn hàng bán", report.sales_refunded), ("Cọc đang giữ", report.deposits_held)), True),
                ("Hội viên", (("Đang hiệu lực", report.active_premium_memberships), ("Hết hạn", report.expired_premium_memberships), ("Khách hội viên", report.premium_customer_count)), False),
                ("Thông báo", (("Email", report.email_notifications_sent), ("SMS", report.sms_notifications_sent), ("Lỗi", report.notification_failures)), False),
            )
            for axis_finance in finance_axes:
                axis_finance.clear()
            self._style_figure(finance_figure)
            for axis_finance, (title, rows, currency) in zip(finance_axes, groups):
                axis_finance.set_title(title)
                axis_finance.grid(False)
                if not rows:
                    axis_finance.text(0.5, 0.5, "Không có dữ liệu", ha="center", va="center", transform=axis_finance.transAxes, color=self._palette.foreground)
                    axis_finance.set_axis_off()
                    continue
                axis_finance.set_axis_on()
                names, amounts = zip(*rows)
                positions = list(range(len(names)))
                axis_finance.barh(positions, [float(amount) for amount in amounts], color="#3b82f6")
                axis_finance.set_yticks(positions, names)
                axis_finance.invert_yaxis()
                axis_finance.xaxis.set_visible(False)
                for position, amount in zip(positions, amounts):
                    label = vnd(amount, exact=True) if currency else f"{amount:,}"
                    axis_finance.annotate(label, xy=(float(amount), position), xytext=(4, 0), textcoords="offset points", va="center", color=self._palette.foreground)
                minimum, maximum = min(float(amount) for amount in amounts), max(float(amount) for amount in amounts)
                span = max(maximum - min(minimum, 0), 1)
                axis_finance.set_xlim(min(minimum, 0) - span * 0.04, max(maximum, 0) + span * 0.55)
            finance_axes[-1].set_axis_off()
            finance_figure.tight_layout(pad=2.2)
            finance_chart.draw_idle()
            inventory_stats.set(
                f"Kho\n• Có sẵn: {report.available}  • Đang thuê: {report.rented}  • Chờ kiểm tra: {report.inspection}\n"
                f"• Đang giữ: {report.held}  • Sửa chữa: {report.repair}  • Mất: {report.lost}  • Ngưng khai thác: {report.retired}  • Quá hạn: {report.overdue_count}"
            )
            top_tree.delete(*top_tree.get_children())
            sale_tree.delete(*sale_tree.get_children())
            customer_tree.delete(*customer_tree.get_children())
            combo_tree.delete(*combo_tree.get_children())
            voucher_tree.delete(*voucher_tree.get_children())
            overdue_tree.delete(*overdue_tree.get_children())
            stockout_tree.delete(*stockout_tree.get_children())
            for title, count in report.top_rentals:
                top_tree.insert("", END, text=title, values=(count,))
            for title, count in report.top_sales:
                sale_tree.insert("", END, text=title, values=(count,))
            for customer in report.top_customers:
                customer_tree.insert("", END, iid=str(customer.customer_id), text=customer.customer_name,
                                     values=(customer.phone, customer.order_count, vnd(customer.total, exact=True)))
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
            labels = ["Có sẵn", "Đang giữ", "Đang thuê", "Kiểm tra", "Sửa chữa", "Mất", "Ngưng"]
            values = [
                report.available,
                report.held,
                report.rented,
                report.inspection,
                report.repair,
                report.lost,
                report.retired,
            ]
            bar_statuses.clear()
            colors = ["#48C78E", "#FFD166", "#58A6FF", "#FFAE42", "#FF6B6B", "#BD93F9", "#A8B5C2"]
            positive = [(label, value, status, color) for label, value, status, color in zip(labels, values, inventory_statuses, colors) if value]
            if positive:
                wedges, _ = axis.pie([value for _, value, _, _ in positive], startangle=90,
                                     colors=[color for _, _, _, color in positive])
                total = sum(values)
                axis.legend(wedges, [f"{label}: {value} ({value / total:.1%})" for label, value, _, _ in positive],
                            loc="center left", bbox_to_anchor=(1, 0.5), labelcolor=self._palette.foreground,
                            facecolor=self._palette.surface, edgecolor=self._palette.border, framealpha=1)
                bar_statuses.update((wedge, status) for wedge, (_, _, status, _) in zip(wedges, positive))
                for wedge in wedges:
                    wedge.set_picker(True)
            else:
                axis.text(0.5, 0.5, "Kho chưa có đĩa", ha="center", transform=axis.transAxes)
            axis.set_title("Trạng thái tồn kho")
            figure.tight_layout()
            chart.draw_idle()

            hovered_day = None
            revenue_tooltip = None
            revenue_points.clear()
            revenue_axis.clear()
            damage_axis.clear()
            genre_axis.clear()
            self._style_figure(analysis_figure)
            self._style_figure(revenue_figure)
            self._style_figure(damage_figure)
            dates = sorted({day for day, _action, _amount in chart_data.revenue})
            if dates:
                by_day = {(day, action): amount for day, action, amount in chart_data.revenue}
                available_actions = {action for _, action in by_day}
                visible_series = []
                for action, name, color in ((LineAction.RENT, "Thuê", "#3b82f6"), (LineAction.BUY, "Bán", "#2e8b57")):
                    if action not in available_actions:
                        continue
                    visible_series.append((action, name))
                    values = [float(by_day.get((day, action), 0)) for day in dates]
                    revenue_axis.plot(dates, values, label=name, color=color)
                    revenue_axis.fill_between(dates, values, alpha=0.25, color=color)
                if visible_series:
                    revenue_axis.legend()
                    for day in dates:
                        rows = [f"{day:%d/%m/%Y}"]
                        rows.extend(
                            f"{name}: {vnd(by_day.get((day, action), 0), exact=True)}"
                            for action, name in visible_series
                        )
                        revenue_points.append((date2num(day), "\n".join(rows)))
                    revenue_tooltip = revenue_axis.annotate(
                        "", xy=(0, 0), textcoords="offset points", xytext=(10, 10),
                        fontsize=10, zorder=10, visible=False,
                        bbox={"boxstyle": "round,pad=0.45", "edgecolor": "none"},
                    )
                    revenue_tooltip.set_in_layout(False)
            else:
                revenue_axis.text(0.5, 0.5, "Không có giao dịch trong kỳ", ha="center", transform=revenue_axis.transAxes)
            revenue_axis.set_title("Doanh thu phim sau giảm, không gồm cọc")
            revenue_axis.set_ylabel("Đồng")
            damage_names = {"LIGHT_DAMAGE": "Hư nhẹ khi trả thuê", "HEAVY_DAMAGE": "Hư nặng khi trả thuê", "LOST": "Mất", "SALE_WORN": "Mòn khi hoàn bán", "SALE_DAMAGED": "Hư khi hoàn bán"}
            if chart_data.damages:
                damage_axis.pie([count for _, count in chart_data.damages], labels=[damage_names.get(name, name) for name, _ in chart_data.damages], autopct="%1.0f%%")
            else:
                damage_axis.text(0.5, 0.5, "Không có hỏng hóc", ha="center", transform=damage_axis.transAxes)
            damage_axis.set_title("Hỏng hóc khi trả hoặc hoàn đĩa")
            if chart_data.genres:
                genre_axis.barh([name for name, _ in reversed(chart_data.genres)], [count for _, count in reversed(chart_data.genres)], color="#3b82f6")
            else:
                genre_axis.text(0.5, 0.5, "Không có lượt bán", ha="center", transform=genre_axis.transAxes)
            genre_axis.set_title("Thể loại bán chạy")
            genre_axis.set_xlabel("Số lượt bán")
            analysis_figure.tight_layout()
            analysis_chart.draw_idle()
            revenue_figure.tight_layout()
            revenue_chart.draw_idle()
            damage_figure.tight_layout()
            damage_chart.draw_idle()

        def refresh():
            try:
                genres.clear()
                genres.update({"Tất cả thể loại": None})
                genres.update({genre.name: genre.id for genre in self.store.list_genres()})
                genre_control.configure(values=tuple(genres))
                start_on, end_on = report_dates()
                action = {"Tất cả giao dịch": None, "Thuê": LineAction.RENT, "Mua": LineAction.BUY}[action_var.get()]
                genre_id = genres[genre_var.get()]
            except Exception as exc:
                messagebox.showerror("Thống kê", str(exc), parent=self)
                return
            refresh_generation["value"] += 1
            hide_revenue_tooltip()
            generation = refresh_generation["value"]
            stats.set("Đang tải thống kê…")
            csv_button.configure(state="disabled")
            chart_button.configure(state="disabled")

            def work():
                for _ in range(3):
                    revision = self.store.cache_revision
                    report = self.store.operational_report(start_on, end_on)
                    charts = self.store.chart_report(start_on, end_on, action, genre_id)
                    if revision == self.store.cache_revision:
                        return report, charts
                raise ValueError("Dữ liệu đang thay đổi liên tục; hãy thử lại.")

            def done(result):
                if generation != refresh_generation["value"] or not root_page.winfo_exists():
                    return
                render(result)
                csv_button.configure(state="normal")
                chart_button.configure(state="normal")

            def failed(exc):
                if generation != refresh_generation["value"] or not root_page.winfo_exists():
                    return
                stats.set("Không thể tải thống kê.")
                messagebox.showerror("Thống kê", str(exc), parent=self)

            self._run_async(work, done, failed)

        root_page.refresh = refresh
