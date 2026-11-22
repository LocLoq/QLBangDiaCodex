# Vận hành và kiểm thử

## Cấu hình và chạy

- Python 3.13; cài dependency bằng `python -m pip install -e '.[dev]'`. Cấu hình dùng tiền tố `NORMASTORE_`, đọc biến môi trường và `.env`/`.env.local`; không commit secret.
- Chạy `python -m normastore` với MySQL 8.4 tương thích. Bootstrap tạo database nếu cần, chạy Alembic rồi thêm dữ liệu tối thiểu khi chưa có vai trò.
- Backup: `python scripts/backup_database.py`. Import: `python scripts/import_tmdb.py --movies 2000 --shows 100`. Seed: `python scripts/seed_demo.py --orders 25000`. Embedding: `python scripts/build_embeddings.py --limit 100`.
- Đóng gói Windows theo README và `RELEASE_CHECKLIST.md`; MySQL không nằm trong bộ cài.

## Kiểm thử đã thực hiện

- Bộ kiểm thử bao gồm nghiệp vụ MySQL, ranh giới UI/application/database, DTO sau khi đóng session, rollback, đặt trước, giá và cọc, báo cáo, migration và sao lưu. Chạy `python -m pytest -q` và `python -m compileall -q src tests scripts alembic` để kiểm tra lại.
- Đã mở 14 trang ở hai cỡ chữ và chế độ tối trên database kiểm thử. Bộ kiểm tra nhận biết nội dung nằm trong vùng cuộn và kiểm tra cuộn đến cuối; cột số có thể căn phải.
- Không kiểm chứng SMTP thực, TMDB/Gemini thật hoặc cài đặt trên máy Windows sạch trong đợt này.

## Migration

Khởi tạo MySQL trống và nâng cấp từ revision `20260907_04` với phim, đĩa, ca và phiếu đã được kiểm tra trên database tạm. Revision `20261121_06` xóa dữ liệu ca và uy tín; revision `20261121_08` xóa cọc cố định cũ. Ứng dụng và lệnh `python -m normastore.migrate` sao lưu trước nâng cấp; chạy Alembic trực tiếp cũng kiểm tra sao lưu trước khi nâng cấp dữ liệu cũ. Nếu sao lưu thất bại, nâng cấp dừng. Các revision xóa dữ liệu không khôi phục dữ liệu bằng downgrade; dùng bản sao lưu để phục hồi.
