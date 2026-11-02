# Tích hợp và adapter

## TMDB

`scripts/import_tmdb.py` gọi use case `application.tmdb_import` với `TmdbClient`. Import phim/bộ/tập, thể loại, review và bản đĩa; kiểm tra TMDB ID trùng và lưu checkpoint theo trang trong `import_runs`. Khi lỗi, thông tin lỗi được ghi cho lượt đang chạy và client được đóng. Không có kiểm thử API thật trong bộ test refactor.

## Gemini và cache

Tìm kiếm theo mô tả dùng embedding và cosine similarity; khi thiếu key, quota hoặc provider không đáp ứng, ứng dụng tìm trong catalog nội bộ và trả cảnh báo. Chỉ tiêu đề và tóm tắt item được dùng làm nội dung embedding. `scripts/build_embeddings.py` bỏ qua vector còn hợp lệ và commit từng lô 25; lô đang xây bị bỏ nếu provider thất bại.

Đề cử dùng kho còn cho thuê, xu hướng và lịch sử khách; Gemini có thể xếp hạng lại. Kết quả AI có cache theo ngày hoặc khách. Poster được lưu trong cache cục bộ và tải nền.

## Email, SMS và xuất file

Worker chạy khi ứng dụng mở, gom nhắc hạn hiện tại theo dòng thuê/kênh và cập nhật outbox. SMTP dùng mật khẩu trong Windows Credential Manager (`normastore` / `smtp`); SMS là mock. Không gửi email thật trong test.

PDF dùng `PdfReceiptExporter` với DTO hóa đơn và hỗ trợ A4/80 mm. Thống kê có xuất CSV và biểu đồ PNG. Người dùng chọn đường dẫn qua UI; adapter xuất PDF và ghi audit sau khi tạo file.
