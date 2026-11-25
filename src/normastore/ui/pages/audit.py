from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from ttkbootstrap.constants import BOTH, END, LEFT, X

from normastore.application.contracts import AuditQuery, PageRequest, SortSpec
from normastore.ui.formatting import format_datetime

ACTION_LABELS = {
    "LOGIN_FAILED": "Đăng nhập thất bại", "LOGIN_SUCCESS": "Đăng nhập thành công",
    "CHANGE_PASSWORD": "Đổi mật khẩu", "CREATE_EMPLOYEE": "Thêm nhân viên",
    "CREATE_CUSTOMER": "Thêm khách hàng", "ACTIVATE_PREMIUM": "Kích hoạt hội viên",
    "UPDATE_CUSTOMER": "Sửa khách hàng",
    "DELETE_CUSTOMER": "Xóa khách hàng",
    "UPDATE_PREMIUM_END": "Chỉnh hạn Premium", "CANCEL_PREMIUM": "Hủy Premium",
    "CREATE_VOUCHER": "Tạo voucher", "CREATE_COMBO": "Tạo combo",
    "CREATE_CATALOG": "Thêm phim hoặc tập", "UPDATE_CATALOG": "Sửa phim hoặc tập",
    "CREATE_SHOW": "Thêm bộ phim", "BULK_CREATE_EPISODES": "Thêm nhiều tập",
    "ADD_COPY": "Thêm đĩa", "UPDATE_COPY": "Sửa đĩa", "ARCHIVE": "Lưu trữ phim",
    "UPDATE_DEPOSIT_PERCENT": "Sửa tỷ lệ cọc", "BULK_PRICE_EDIT": "Sửa giá hàng loạt",
    "CHECKOUT": "Tạo phiếu thuê hoặc mua", "EXPORT_ORDER_PDF": "Xuất phiếu PDF",
    "RETURN_RENTAL": "Trả đĩa thuê", "EXTEND_RENTAL": "Gia hạn thuê",
    "RENTAL_TO_SALE": "Chuyển thuê thành mua", "RETURN_SALE": "Hoàn hàng bán",
    "CREATE_RESERVATION": "Tạo đặt trước", "UPDATE_DISCOVERY_DISCOUNT": "Sửa ưu đãi khám phá",
    "CREATE_MOCK_FIXTURES": "Tạo dữ liệu mẫu", "GENERATE_MOCK_DAY": "Tạo dữ liệu mẫu theo ngày",
    "GENERATE_MOCK_RANGE": "Tạo dữ liệu mẫu theo kỳ",
}
ENTITY_LABELS = {
    "UserAccount": "Tài khoản", "Employee": "Nhân viên", "Customer": "Khách hàng",
    "PremiumMembership": "Hội viên", "Voucher": "Voucher", "Combo": "Combo",
    "CatalogItem": "Phim hoặc tập", "Show": "Bộ phim", "PhysicalCopy": "Bản đĩa",
    "DepositDefault": "Cấu hình cọc", "Order": "Phiếu", "ReturnReceipt": "Phiếu trả đĩa",
    "RentalTerm": "Lượt thuê", "SaleReturn": "Hoàn hàng bán", "Reservation": "Đặt trước",
    "MockFixtures": "Dữ liệu mẫu", "MockDailyRun": "Dữ liệu mẫu theo ngày",
}

class AuditPageMixin:
    def audit_page(self, page) -> None:
        self._heading(page, "Lịch sử và hoạt động", "Thay đổi nghiệp vụ và sự kiện bảo mật")
        filters = ttk.Frame(page)
        filters.pack(fill=X, pady=(0, 8))
        text, action = tk.StringVar(), tk.StringVar(value="Tất cả")
        ttk.Label(filters, text="Tìm:").pack(side=LEFT)
        ttk.Entry(filters, textvariable=text, width=32).pack(side=LEFT, padx=(4, 10))
        ttk.Label(filters, text="Hành động:").pack(side=LEFT)
        action_codes = {label: code for code, label in ACTION_LABELS.items()}
        ttk.Combobox(filters, textvariable=action, values=("Tất cả", *action_codes),
                     state="readonly", width=30).pack(side=LEFT, padx=4)
        page_number = tk.IntVar(value=1)
        sort_state: dict[str, object] = {"field": "created", "descending": True}
        tree = self._create_treeview(
            page, columns=("created", "actor", "action", "entity", "entity_id"), show="headings"
        )
        titles = {
            "created": "Thời gian",
            "actor": "Nhân viên",
            "action": "Hành động",
            "entity": "Đối tượng",
            "entity_id": "ID",
        }
        for key, title in titles.items():
            tree.heading(key, text=title)
        tree.pack(fill=BOTH, expand=True)
        rows = {}

        def refresh():
            tree.delete(*tree.get_children())
            rows.clear()
            result = self.store.query_audit_logs(AuditQuery(text.get(), action_codes.get(action.get(), "")), PageRequest(page_number.get(), 50), SortSpec(str(sort_state['field']), bool(sort_state['descending'])))
            pager(result)
            for row in result.items:
                rows[str(row.audit_id)] = row
                tree.insert(
                    "",
                    END,
                    iid=str(row.audit_id),
                    values=(
                        format_datetime(row.created_at),
                        row.actor_name or "Hệ thống",
                        ACTION_LABELS.get(row.action, row.action),
                        ENTITY_LABELS.get(row.entity, row.entity),
                        row.entity_id,
                    ),
                )

        def detail(_event=None):
            selected = tree.selection()
            if len(selected) != 1:
                return
            row = rows[selected[0]]
            dialog = self._dialog("Chi tiết nhật ký", 720, 480, modal=False)
            body = tk.Text(dialog, wrap="word", padx=12, pady=12)
            self._theme_text_widgets.append(body)
            self._apply_ui_style()
            body.pack(fill=BOTH, expand=True)
            body.insert(
                "1.0",
                json.dumps(row.detail, ensure_ascii=False, indent=2, default=str)
                if isinstance(row.detail, (dict, list))
                else str(row.detail or "Không có chi tiết"),
            )
            body.configure(state="disabled")

        ttk.Button(
            filters,
            text="Lọc",
            command=lambda: (page_number.set(1), refresh()),
            bootstyle="secondary",
        ).pack(side=LEFT, padx=6)
        pager = self._create_pager(page, page_number, refresh)
        self._install_sortable_headings(
            tree, titles, sort_state, lambda: (page_number.set(1), refresh())
        )
        tree.bind("<Double-1>", detail)
        state: dict[str, str] = {}
        text.trace_add(
            "write", lambda *_: self._debounce(state, lambda: (page_number.set(1), refresh()))
        )
        action.trace_add(
            "write", lambda *_: self._debounce(state, lambda: (page_number.set(1), refresh()))
        )
        page.refresh = refresh
