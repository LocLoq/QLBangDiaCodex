from __future__ import annotations

from pathlib import Path
from tempfile import NamedTemporaryFile

from matplotlib import get_data_path
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from normastore.application.contracts import OrderReceipt
from normastore.domain.enums import LineAction


class PdfReceiptExporter:
    """Render immutable receipt DTOs without accessing the database."""

    _font_registered = False
    font_name = "NormaStoreDejaVu"
    bold_font_name = "NormaStoreDejaVuBold"

    @classmethod
    def _register_fonts(cls) -> None:
        if cls._font_registered:
            return
        font_dir = Path(get_data_path()) / "fonts" / "ttf"
        pdfmetrics.registerFont(TTFont(cls.font_name, str(font_dir / "DejaVuSans.ttf")))
        pdfmetrics.registerFont(TTFont(cls.bold_font_name, str(font_dir / "DejaVuSans-Bold.ttf")))
        cls._font_registered = True

    @staticmethod
    def _money(value) -> str:
        return f"{value:,.0f} đ".replace(",", ".")

    @staticmethod
    def _date(value) -> str:
        return value.strftime("%d/%m/%Y") if value else "—"

    @staticmethod
    def _action(action: LineAction) -> str:
        return "Thuê" if action == LineAction.RENT else "Mua"

    def export(self, receipt: OrderReceipt, destination: Path, layout: str) -> Path:
        self._register_fonts()
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        page_size = A4 if layout == "A4" else (80 * mm, 297 * mm)
        margins = (14 * mm, 14 * mm, 12 * mm, 12 * mm) if layout == "A4" else (4 * mm, 4 * mm, 5 * mm, 5 * mm)
        styles = getSampleStyleSheet()
        body = ParagraphStyle(
            "NormaBody", parent=styles["BodyText"], fontName=self.font_name, fontSize=8 if layout == "80mm" else 9,
            leading=11 if layout == "80mm" else 12,
        )
        title = ParagraphStyle(
            "NormaTitle", parent=styles["Title"], fontName=self.bold_font_name, fontSize=15 if layout == "A4" else 11,
            leading=18 if layout == "A4" else 13, alignment=TA_CENTER,
        )
        right = ParagraphStyle("NormaRight", parent=body, alignment=TA_RIGHT)
        center = ParagraphStyle("NormaCenter", parent=body, alignment=TA_CENTER)
        story = [Paragraph("NormaStore", title)]
        story.append(Paragraph("PHIẾU THUÊ / MUA BĂNG ĐĨA", ParagraphStyle("Receipt", parent=body, alignment=TA_CENTER, fontName=self.bold_font_name)))
        story.append(Spacer(1, 4))
        story.append(Paragraph(
            f"<b>Mã phiếu:</b> {receipt.code}<br/><b>Lập lúc:</b> {receipt.created_at:%d/%m/%Y %H:%M}<br/>"
            f"<b>Trạng thái:</b> {receipt.status}",
            body,
        ))
        customer_lines = [f"<b>Khách hàng:</b> {receipt.customer_name}"]
        if receipt.customer_phone:
            customer_lines.append(f"<b>Điện thoại:</b> {receipt.customer_phone}")
        if receipt.customer_email:
            customer_lines.append(f"<b>Email:</b> {receipt.customer_email}")
        if receipt.customer_address:
            customer_lines.append(f"<b>Địa chỉ:</b> {receipt.customer_address}")
        customer_lines.append(f"<b>Nhân viên:</b> {receipt.employee_name}")
        story.extend([Spacer(1, 5), Paragraph("<br/>".join(customer_lines), body), Spacer(1, 7)])
        if layout == "A4":
            rows = [[
                Paragraph("#", center), Paragraph("Phim / Barcode", center), Paragraph("Loại", center),
                Paragraph("Đơn giá", center), Paragraph("Giảm", center), Paragraph("Thành tiền", center),
                Paragraph("Cọc", center), Paragraph("Hạn trả / trạng thái", center),
            ]]
            for index, line in enumerate(receipt.lines, start=1):
                rental = f"{self._date(line.due_date)}<br/>{line.rental_state or '—'}"
                rows.append([
                    Paragraph(str(index), center),
                    Paragraph(f"{line.title}<br/><font size='7'>{line.barcode or '—'}</font>", body),
                    Paragraph(self._action(line.action), center), Paragraph(self._money(line.unit_price), right),
                    Paragraph(self._money(line.discount_amount), right), Paragraph(self._money(line.net_amount), right),
                    Paragraph(self._money(line.deposit), right), Paragraph(rental, body),
                ])
            table = Table(rows, colWidths=[8 * mm, 48 * mm, 14 * mm, 21 * mm, 19 * mm, 23 * mm, 19 * mm, 30 * mm], repeatRows=1)
        else:
            rows = [[Paragraph("Nội dung", body), Paragraph("Số tiền", right)]]
            for index, line in enumerate(receipt.lines, start=1):
                detail = (
                    f"<b>{index}. {line.title}</b><br/>{line.barcode or '—'} • {self._action(line.action)}<br/>"
                    f"Giá {self._money(line.unit_price)} • Giảm {self._money(line.discount_amount)} • Cọc {self._money(line.deposit)}<br/>"
                    f"Hạn trả: {self._date(line.due_date)} {line.rental_state or ''}"
                )
                rows.append([Paragraph(detail, body), Paragraph(self._money(line.net_amount + line.deposit), right)])
            table = Table(rows, colWidths=[51 * mm, 21 * mm], repeatRows=1)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F4E78")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), self.bold_font_name),
            ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#B8C2CC")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4), ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        story.extend([table, Spacer(1, 8)])
        if receipt.discounts:
            discount_text = "<br/>".join(
                f"{discount.source}{f' ({discount.source_code})' if discount.source_code else ''}: -{self._money(discount.amount)}"
                for discount in receipt.discounts
            )
            story.extend([Paragraph("<b>Ưu đãi áp dụng</b><br/>" + discount_text, body), Spacer(1, 5)])
        totals = [
            ("Tổng trước giảm", receipt.gross_total), ("Giảm giá", -receipt.discount_total),
            ("Tiền cọc", receipt.deposit_total), ("Tổng phải thu", receipt.total_due),
            ("Đã thanh toán lúc lập phiếu", receipt.checkout_paid), ("Còn thiếu", receipt.balance_due),
        ]
        total_rows = [[Paragraph(f"<b>{label}</b>" if label in ("Tổng phải thu", "Còn thiếu") else label, body), Paragraph(
            f"<b>{self._money(value)}</b>" if label in ("Tổng phải thu", "Còn thiếu") else self._money(value), right,
        )] for label, value in totals]
        total_table = Table(total_rows, colWidths=[120 * mm if layout == "A4" else 50 * mm, 55 * mm if layout == "A4" else 22 * mm], hAlign="RIGHT")
        total_table.setStyle(TableStyle([("LINEABOVE", (0, 3), (-1, 3), 0.8, colors.HexColor("#1F4E78")), ("BOTTOMPADDING", (0, 0), (-1, -1), 3)]))
        story.extend([total_table, Spacer(1, 14)])
        if layout == "A4":
            signatures = Table([[Paragraph("<b>Khách hàng</b><br/><br/><br/><br/>(Ký và ghi rõ họ tên)", center), Paragraph("<b>Nhân viên</b><br/><br/><br/><br/>(Ký và ghi rõ họ tên)", center)]], colWidths=[85 * mm, 85 * mm])
            story.append(signatures)
        else:
            story.append(Paragraph("Cảm ơn quý khách. Vui lòng giữ phiếu khi trả đĩa.", ParagraphStyle("Thanks", parent=body, alignment=TA_CENTER)))
        temporary: Path | None = None
        try:
            with NamedTemporaryFile(prefix=".normastore-", suffix=".pdf", dir=destination.parent, delete=False) as stream:
                temporary = Path(stream.name)
            document = SimpleDocTemplate(str(temporary), pagesize=page_size, leftMargin=margins[0], rightMargin=margins[1], topMargin=margins[2], bottomMargin=margins[3])
            document.build(story)
            temporary.replace(destination)
            return destination
        except Exception:
            if temporary and temporary.exists():
                temporary.unlink()
            raise
