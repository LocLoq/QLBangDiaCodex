import csv
from tkinter import filedialog, messagebox

CATALOG_COLUMNS = (
    "type",
    "title",
    "show_ref",
    "show_id",
    "season",
    "episode",
    "overview",
    "release_date",
    "genres",
    "rental_price",
    "sale_price",
    "replacement_value",
    "can_rent",
    "can_sell",
)
COPY_COLUMNS = (
    "item_id",
    "quantity",
    "media_format",
    "can_rent",
    "can_sell",
    "aisle",
    "rack",
    "compartment",
)


def export_template(parent, kind):
    columns = CATALOG_COLUMNS if kind == "catalog" else COPY_COLUMNS
    path = filedialog.asksaveasfilename(
        parent=parent,
        defaultextension=".csv",
        filetypes=[("CSV", "*.csv")],
        initialfile="mau-phim.csv" if kind == "catalog" else "mau-dia.csv",
    )
    if not path:
        return
    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as stream:
            csv.writer(stream).writerow(columns)
        if kind == "catalog":
            details = (
                "type nhận MOVIE, SHOW hoặc EPISODE. SHOW cần show_ref duy nhất. "
                "EPISODE dùng show_ref của SHOW trong tệp hoặc show_id có sẵn, "
                "kèm season và episode. Ngày có dạng YYYY-MM-DD, nhiều thể loại ngăn cách bằng |. "
                "can_rent và can_sell nhận 1 hoặc 0."
            )
        else:
            details = (
                "item_id là mã phim hoặc tập trong danh mục. quantity là số lượng, "
                "media_format nhận VHS, VCD, DVD hoặc Blu-ray. "
                "can_rent và can_sell nhận 1 hoặc 0."
            )
        messagebox.showinfo("CSV", f"Đã lưu tệp mẫu.\n\n{details}", parent=parent)
    except OSError as exc:
        messagebox.showerror("CSV", str(exc), parent=parent)


def import_file(app, kind, refresh):
    path = filedialog.askopenfilename(parent=app, filetypes=[("CSV", "*.csv")])
    if not path:
        return
    try:
        with open(path, encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            required = {"type", "title"} if kind == "catalog" else {"item_id"}
            if not reader.fieldnames or not required.issubset(reader.fieldnames):
                raise ValueError("Thiếu cột bắt buộc. Hãy sử dụng tệp mẫu của ứng dụng.")
            rows = list(reader)
        if not rows:
            raise ValueError("Tệp không có dữ liệu.")
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError("Số cột trong tệp không khớp với dòng tiêu đề.")
        method = app.store.import_catalog_csv if kind == "catalog" else app.store.import_copies_csv
        count = method(rows, app.account.employee_id)
        refresh()
        messagebox.showinfo("CSV", f"Đã nhập {count} bản ghi.", parent=app)
    except Exception as exc:
        messagebox.showerror("CSV", str(exc), parent=app)
