from __future__ import annotations

import json
import tkinter as tk
from tkinter import ttk

from ttkbootstrap.constants import BOTH, END, LEFT, X

from normastore.application.contracts import AuditQuery, PageRequest, SortSpec


class AuditPageMixin:
    def audit_page(self, page) -> None:
        self._heading(page, "Nhật ký hành động", "Thay đổi nghiệp vụ và sự kiện bảo mật")
        filters = ttk.Frame(page)
        filters.pack(fill=X, pady=(0, 8))
        text, action = tk.StringVar(), tk.StringVar()
        ttk.Label(filters, text="Tìm:").pack(side=LEFT)
        ttk.Entry(filters, textvariable=text, width=32).pack(side=LEFT, padx=(4, 10))
        ttk.Label(filters, text="Hành động:").pack(side=LEFT)
        ttk.Entry(filters, textvariable=action, width=25).pack(side=LEFT, padx=4)
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
            result = self.store.query_audit_logs(AuditQuery(text.get(), action.get()), PageRequest(page_number.get(), 50), SortSpec(str(sort_state['field']), bool(sort_state['descending'])))
            pager(result)
            for row in result.items:
                rows[str(row.audit_id)] = row
                tree.insert(
                    "",
                    END,
                    iid=str(row.audit_id),
                    values=(
                        row.created_at,
                        row.actor_name or "Hệ thống",
                        row.action,
                        row.entity,
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
