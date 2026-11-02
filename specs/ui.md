# Giao diện desktop

Ứng dụng có thanh điều hướng, giao diện sáng/tối, cỡ chữ và 14 trang. Các kết quả danh sách lớn dùng bộ lọc, sắp xếp và phân trang theo khả năng từng trang.

| Trang | Thao tác / service chính |
|---|---|
| Tổng quan | `dashboard`, `today_recommendations` |
| Lập phiếu | `query_catalog`, `choose_checkout_copy`, `quote`, `checkout` |
| Phiếu đã lập | `query_orders`, `order_detail`, `export_order_pdf` |
| Trả đĩa & phạt | `query_active_rentals`, `return_rentals`, `extend_rental`, `rental_to_sale`, `return_sale` |
| Đặt trước | `reserve`, `expire_reservation_holds`, `query_reservations` |
| Phim & tập | Catalog card/danh sách, lọc, chi tiết, sửa item, tạo bộ và tập, tìm theo mô tả |
| Kho đĩa | `query_inventory`, cập nhật và kiểm tra copy |
| Khách hàng & Premium | Tìm/tạo khách, kích hoạt Premium, uy tín, đề cử |
| Combo / Voucher | Danh sách, tạo combo cố định/theo bộ và voucher |
| Nhân viên & ca | Danh sách nhân viên, tạo tài khoản, mở/đóng ca |
| Thông báo | `query_notifications` |
| Thống kê | `operational_report`, thống kê theo kỳ, xuất CSV/PNG |
| Nhật ký hành động | `query_audit_logs`, lọc và phân trang |
| Cài đặt & About | Credential Gemini, thử SMTP, cọc mặc định, tạo dữ liệu mock |

Các màn hình gọi service bằng DTO; widget quản lý trạng thái trình bày. Phân quyền nút chỉ hỗ trợ giao diện: service vẫn kiểm tra quyền ở các nghiệp vụ cần quản lý.
