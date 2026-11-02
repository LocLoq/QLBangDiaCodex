# Đặc tả NormaStore

NormaStore là ứng dụng desktop quản lý cửa hàng băng đĩa, dùng Python 3.13, Tkinter/ttkbootstrap, SQLAlchemy và MySQL. Bộ tài liệu này mô tả code trong repository sau khi tách lớp; các giới hạn đã kiểm chứng được ghi trong tài liệu vận hành.

| Tài liệu | Nội dung |
|---|---|
| [Kiến trúc](architecture.md) | Các lớp, interface và transaction |
| [Cơ sở dữ liệu](database.md) | Các bảng, model, khóa và quan hệ |
| [Quy tắc nghiệp vụ](business-rules.md) | Quyền, tiền cọc, khuyến mãi và trạng thái |
| [Ca sử dụng](use-cases.md) | Luồng nghiệp vụ và trường hợp lỗi |
| [Giao diện](ui.md) | 14 trang và các thao tác chính |
| [Tích hợp](integrations.md) | TMDB, Gemini, thông báo và xuất file |
| [Vận hành và kiểm thử](operations-testing.md) | Cấu hình, lệnh chạy, kiểm chứng và giới hạn |

Mã nguồn và migration là nguồn xác thực khi có khác biệt. Tài liệu không chứa giá trị secret trong cấu hình cục bộ.
