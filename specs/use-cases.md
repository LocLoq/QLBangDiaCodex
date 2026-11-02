# Ca sử dụng

| Nghiệp vụ | Luồng chính | Trường hợp lỗi / kết quả |
|---|---|---|
| Đăng nhập, ca | Xác thực, mở ca; đóng ca bằng tiền cuối ca | Sai tài khoản ghi audit thất bại; ca đã đóng hoặc sai quyền bị từ chối |
| Khách hàng | Tạo khách theo tên/SĐT, kích hoạt Premium, điều chỉnh uy tín | SĐT trùng, kỳ Premium không hỗ trợ hoặc thiếu quyền tạo lỗi nghiệp vụ |
| Catalog/kho | Tìm/lọc phim, bộ và tập; tạo item/copy; sửa giá, lưu trữ, kiểm tra copy | Barcode trùng, dữ liệu không hợp lệ hoặc thiếu quyền bị từ chối |
| Combo/voucher | Tạo combo cố định hoặc theo số tập; tạo voucher phần trăm/tiền | Item không tồn tại, mã trùng, loại giảm hoặc ngày hiệu lực sai bị từ chối |
| Lập phiếu | Chọn khách và ca, chọn bản thuê/mua, xem báo giá, thanh toán | Thiếu hạn trả, vượt hạn mức, voucher không hợp lệ hoặc tồn kho đổi sẽ rollback |
| Trả/gia hạn | Chọn các dòng của cùng khách, ghi tình trạng, phạt và hoàn cọc; gia hạn hoặc chuyển mua | Dòng không còn hoạt động, khác khách hoặc cần quyền quản lý bị từ chối |
| Hoàn bán | Chọn dòng còn hạn, xác nhận tình trạng và khấu trừ | Quá 7 ngày, bản không còn `SOLD` hoặc khấu trừ sai bị từ chối |
| Đặt trước | Chọn khách/item, phân bổ bản trống và giải phóng giữ chỗ hết hạn | Không có khách/item hoặc đặt trước trùng đang hiệu lực bị từ chối |
| Báo cáo/thông báo | Lọc kỳ, xem thống kê, xuất CSV/PNG/PDF; xử lý outbox | Provider lỗi được ghi trạng thái; thiếu Gemini dùng tìm kiếm nội bộ |

Các thay đổi liên quan đến cùng một phiếu và nhật ký tương ứng nằm trong cùng transaction. Tác vụ tạo mock theo khoảng ngày có kết quả cho biết ngày lỗi và các ngày đã tạo hoặc bỏ qua.
