# Quy tắc nghiệp vụ

## Tài khoản và phân quyền

- Vai trò gồm `ADMIN`, `MANAGER`, `STAFF`. Các thay đổi danh mục/kho, khuyến mãi và nhân viên yêu cầu quản lý hoặc quản trị; service kiểm tra quyền và ghi audit.
- Đăng nhập và đổi mật khẩu dùng Argon2. Mật khẩu mới tối thiểu 8 ký tự.
- `employee_id` là định danh nhân viên thực hiện nghiệp vụ và có thể khác ID tài khoản.

## Thuê, mua, cọc và giảm giá

- Mỗi dòng thuê cần hạn trả, bản đĩa và phim cho phép thuê; dòng mua cần cả hai cho phép bán. Đĩa phải có sẵn hoặc được giữ còn hạn cho chính khách hàng. Service kiểm tra lại tồn kho dưới khóa database.
- Không giới hạn số đĩa thuê theo khách hàng.
- Phim hoặc tập nhập thủ công có thể gắn nhiều thể loại; tên mới được tạo khi lưu. Bộ lọc và thống kê thể loại dùng các liên kết thể loại hiện tại của phim hoặc tập.
- Cọc cơ sở bằng tỷ lệ cấu hình, mặc định 75%, nhân giá bán của đĩa trước khuyến mãi; giảm tiếp 30% cho Premium và làm tròn lên nghìn đồng.
- Combo cố định cần đủ phim/tập; combo theo bộ cần đủ số tập. Thứ tự giảm là Khám phá theo từng phim, combo, Premium 10% trên phần còn lại, voucher; tổng giảm tối đa 50% tiền hàng. Voucher cần đúng một loại giảm tiền hoặc phần trăm và phải trong thời gian hiệu lực.
- Premium có kỳ 30/90/365 ngày, giá lần lượt 59.000/159.000/499.000 đồng; kích hoạt ghi giao dịch thanh toán.
- Quản lý và quản trị viên có thể đổi ngày hết hạn của Premium đang hiệu lực hoặc hủy ngay. Hủy giữ nguyên lịch sử hội viên và thanh toán. Chỉ xóa được hồ sơ khách hàng chưa có lịch sử nghiệp vụ.

## Trả, gia hạn và đặt trước

- Phạt trễ mặc định 5.000 đồng/ngày, theo mức lưu trên dòng thuê. Hư nhẹ/hư nặng/mất lần lượt tính 25%/60%/100% giá trị thay thế; tiền cọc được cấn vào khoản phạt và số dư được ghi vào sổ thanh toán.
- Khi trả, nhân viên chọn hiện trạng, tỷ lệ tình trạng và trạng thái kho cho từng đĩa; báo mất bắt buộc chuyển `LOST`. Gia hạn chọn ngày trả mới và nhập phí thỏa thuận; dòng quá hạn hoặc có người chờ cần quản lý phê duyệt. Khi gia hạn quá hạn, tiền phạt đến ngày gia hạn được thu riêng và không tính lại khi trả đúng hạn mới.
- Chuyển thuê thành mua cấn cọc đã thu vào giá bán, không tính cọc là giảm giá; chỉ cấn khi phiếu thuê đã thanh toán đủ. Phần cọc vượt giá bán được hoàn. Nếu khách trả thêm chưa đủ, phiếu bán được đánh dấu chưa thanh toán đủ. Khi hoàn phiếu chuyển mua, số hoàn tối đa bằng cọc đã cấn cộng số tiền khách đã trả thêm, không vượt giá bán; phiếu thuê cũ chưa thanh toán đủ cần đối soát thủ công.
- Hàng bán được xem xét hoàn trong 7 ngày kể cả ngày bán. Hoàn bán đưa đĩa vào `INSPECTION`; đĩa không ở tình trạng tốt cần quản lý, khoản khấu trừ không vượt số tiền hoàn.
- Đặt trước hỗ trợ phim cho thuê hoặc bán và chờ FIFO theo thời gian tạo. Chỉ bản đĩa có ít nhất một quyền thuê/bán tương ứng với phim được phân bổ. Đĩa mới nhập được phân bổ ngay khi phim đã phát hành; phim sắp ra tiếp tục chờ đến ngày phát hành. Khi chọn đĩa hoặc lập phiếu, hệ thống phân bổ lượt đang chờ trước, kể cả khi tác vụ nền chưa chạy. Hệ thống giữ 24 giờ; hết hạn giải phóng bản đĩa và phân bổ cho người chờ tiếp theo.
- Có thể hủy cùng lúc nhiều lượt đang chờ hoặc đang giữ đĩa. Lượt đã hủy vẫn hiện trong lịch sử. Hệ thống giải phóng đĩa của cả nhóm đã hủy trước khi phân bổ lại theo thứ tự chờ.
- Chọn khách ở Tạo phiếu tự thêm các đĩa đang giữ hợp lệ cho khách, ưu tiên thuê và dùng hạn trả đang chọn; đĩa chỉ bán được thêm dạng mua. Đổi khách thay các dòng tự thêm, giữ các dòng thủ công. Bỏ dòng khỏi giỏ không hủy đặt trước và không tự thêm lại khi làm mới cùng khách.
- Hoàn tất phiếu lưu ghi chú “Đặt trước” trên dòng giao dịch và liên kết lượt đặt trước với dòng đó; tab Đặt trước hiển thị Đã thuê/Đã mua. Ghi chú được giữ trong chi tiết phiếu và PDF; lượt hoàn tất cũ không có liên kết vẫn hiển thị Đã nhận.
- Nhập kho theo số lượng nguyên dương, mặc định 1, thực hiện trong một giao dịch. Đĩa mới dùng mã tự sinh `DIA-` và 12 ký tự hex viết hoa; voucher mới trên giao diện dùng `VC-` và cùng quy tắc. Mã cũ giữ nguyên; giao diện không cho nhập hoặc sửa mã, mã đĩa đã lưu không được đổi qua nghiệp vụ sửa kho.
