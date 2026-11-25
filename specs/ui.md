# Giao diện desktop

Ứng dụng có thanh điều hướng, giao diện sáng/tối, cỡ chữ và 13 trang. Các kết quả danh sách lớn dùng bộ lọc, sắp xếp và phân trang theo khả năng từng trang. Nhấn biểu tượng Home năm lần để bật hoặc tắt các trang Cài đặt và Lịch sử trong phiên hiện tại; quyền xem lịch sử vẫn áp dụng.

| Trang | Thao tác / service chính |
|---|---|
| Tổng quan | Tồn kho thấp, phim được thuê/bán nhiều, khám phá, đề cử ngẫu nhiên và đặt trước phim sắp ra |
| Tạo phiếu | Tìm phim, chọn đĩa, chọn mùa hoặc khoảng tập, `quote`, `checkout` |
| Hóa đơn đã tạo | `query_orders`, `order_detail`, `export_order_pdf` |
| Đĩa đã được thuê | `query_active_rentals`, `return_rentals`, `extend_rental`, `rental_to_sale`, `return_sale` |
| Đặt trước | `reserve`, `expire_reservation_holds`, `query_reservations` |
| Phim & tập | Danh sách/thẻ, tìm và lọc, xem bộ, thêm/sửa phim hoặc tập và thể loại, nhập đĩa |
| Kho đĩa | Tìm kiếm, nhóm bộ/mùa/tập/đĩa, thêm, cập nhật và kiểm tra đĩa |
| Khách hàng & Premium | Tìm/tạo khách, kích hoạt Premium, đề cử |
| Combo / Voucher | Danh sách, tạo combo cố định/theo bộ và voucher |
| Thông báo | `query_notifications` |
| Thống kê | `operational_report`, biểu đồ doanh thu/hỏng hóc/thể loại, bộ lọc, xuất CSV/PNG |
| Lịch sử và hoạt động | `query_audit_logs`, lọc và phân trang |
| Cài đặt & Giới thiệu | Cấu hình Gemini, thử SMTP, tỷ lệ cọc, tạo dữ liệu mẫu |

Các màn hình gọi service bằng DTO; widget quản lý trạng thái trình bày. Phân quyền nút chỉ hỗ trợ giao diện: service vẫn kiểm tra quyền ở các nghiệp vụ cần quản lý.
