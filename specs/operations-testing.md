# Vận hành và kiểm thử

## Cấu hình và chạy

- Python 3.13; cài dependency bằng `python -m pip install -e '.[dev]'`. Cấu hình dùng tiền tố `NORMASTORE_`, đọc biến môi trường và `.env`/`.env.local`; không commit secret.
- Chạy `python -m normastore` với MySQL 8.4 tương thích. Bootstrap tạo database nếu cần, chạy Alembic rồi thêm dữ liệu tối thiểu khi chưa có vai trò.
- Backup: `python scripts/backup_database.py`. Import: `python scripts/import_tmdb.py --movies 2000 --shows 100`. Seed: `python scripts/seed_demo.py --orders 25000`. Embedding: `python scripts/build_embeddings.py --limit 100`.
- Đóng gói Windows theo README và `RELEASE_CHECKLIST.md`; MySQL không nằm trong bộ cài.

## Kiểm thử đã thực hiện

- Baseline trước refactor: 74 test qua. Sau refactor: 87 test qua, gồm kiểm thử nghiệp vụ MySQL, ranh giới UI/application/database, DTO sau khi đóng session, rollback sau flush và trả một phần, mở/đóng ca, session riêng khi chạy đồng thời, import với client giả, Gemini được inject và lỗi provider embedding.
- DDL SQLAlchemy của 36 bảng được so sánh trước/sau trên dialect MySQL; mapper được cấu hình đầy đủ và các thao tác cần khóa `FOR UPDATE` vẫn dùng khóa. Chạy `python -m pytest -q` và `python -m compileall -q src tests scripts alembic` để kiểm tra lại.
- Đã mở 14 trang ở hai cỡ chữ và chế độ tối trên database kiểm thử với worker và provider thật bị vô hiệu. Kiểm tra Treeview gốc báo các cột số/tiền được căn phải thay vì căn giữa theo tiêu chí của script; kết quả mở trang riêng đã qua khi bỏ kiểm tra căn lề đó.
- Không kiểm chứng SMTP thực, TMDB/Gemini thật hoặc cài đặt trên máy Windows sạch trong đợt này.

## Giới hạn migration đã xác nhận

Upgrade từ database MySQL trống hiện thất bại tại revision `20260907_04`: migration đầu gọi `Base.metadata.create_all` với metadata hiện tại, tạo sẵn `deposit_defaults`; revision sau lại tạo bảng đó và MySQL báo lỗi 1050. Thử nghiệm được thực hiện trên database tạm riêng và database này đã bị xóa. Lịch sử migration và DDL chưa được thay đổi trong refactor; cần xử lý riêng trước khi triển khai khởi tạo mới. Database kiểm thử đã ở revision hiện tại chạy được bộ test.
