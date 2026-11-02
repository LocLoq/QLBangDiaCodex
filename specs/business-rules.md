# Quy tắc nghiệp vụ

## Tài khoản và phân quyền

- Vai trò gồm `ADMIN`, `MANAGER`, `STAFF`. Các thay đổi danh mục/kho, khuyến mãi, nhân viên và điểm uy tín yêu cầu quản lý hoặc quản trị; service kiểm tra quyền và ghi audit.
- Đăng nhập và đổi mật khẩu dùng Argon2. Mật khẩu mới tối thiểu 8 ký tự. Ca chỉ được đóng bởi chủ ca hoặc quản lý/quản trị; tiền đầu/cuối ca không âm.
- `employee_id` là định danh nhân viên thực hiện nghiệp vụ và có thể khác ID tài khoản.

## Thuê, mua, cọc và giảm giá

- Mỗi dòng thuê cần hạn trả, bản đĩa và item cho phép thuê; dòng mua cần cả hai cho phép bán. Bản đĩa phải đang `AVAILABLE`. Khi lập phiếu, service kiểm tra lại tồn kho dưới khóa database.
- Hạn mức thuê cơ bản là 4, hoặc 8 với Premium, rồi điều chỉnh theo uy tín. Điểm từ 90: hệ số cọc 0,85 và thêm 2 đĩa; từ 70: 1 và không điều chỉnh; từ 50: 1,25 và giảm 1; dưới 50: 1,5 và hạn mức 1.
- Cọc thực tế = cọc cơ sở × hệ số uy tín × 0,70 nếu Premium, sau đó làm tròn lên nghìn đồng. Phiếu có thể gồm dòng thuê và mua cùng lúc.
- Combo cố định cần đủ item; combo theo bộ cần đủ số episode. Thứ tự giảm là combo, Premium 10% trên phần còn lại, voucher; tổng giảm tối đa 50% tiền hàng. Voucher cần đúng một loại giảm tiền hoặc phần trăm và phải trong thời gian hiệu lực.
- Premium có kỳ 30/90/365 ngày, giá lần lượt 59.000/159.000/499.000 đồng; kích hoạt ghi giao dịch thanh toán.

## Trả, gia hạn và đặt trước

- Phạt trễ mặc định 5.000 đồng/ngày, theo mức lưu trên dòng thuê. Hư nhẹ/hư nặng/mất lần lượt tính 25%/60%/100% giá trị thay thế; tiền cọc được cấn vào khoản phạt và số dư được ghi vào sổ thanh toán.
- Trả bình thường đưa đĩa về `AVAILABLE`; hư đưa vào `REPAIR`; mất đưa vào `LOST`. Gia hạn chuẩn 3 ngày; dòng quá hạn hoặc có người chờ cần quản lý phê duyệt.
- Hàng bán được xem xét hoàn trong 7 ngày kể cả ngày bán. Hoàn bán đưa đĩa vào `INSPECTION`; đĩa không ở tình trạng tốt cần quản lý, khoản khấu trừ không vượt số tiền hoàn.
- Đặt trước chờ FIFO theo thời gian tạo. Khi có bản phù hợp, hệ thống giữ 24 giờ; hết hạn giải phóng bản đĩa và phân bổ cho người chờ tiếp theo.
