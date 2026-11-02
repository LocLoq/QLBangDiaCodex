# NormaStore

Ứng dụng desktop quản lý băng đĩa truyền thống, xây bằng Python 3.13, Tkinter/ttkbootstrap và MySQL 8.4 qua Laragon.

Đặc tả kiến trúc, dữ liệu và nghiệp vụ: [specs/README.md](specs/README.md).

Trước khi build hoặc triển khai, xem [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md).
Tiến độ và các điều kiện còn thiếu được ghi ở [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md).

## Chức năng hiện có

- Catalog Movie, Show, Season và Episode; chuyển Card/Danh sách (poster cache tải nền), xem chi tiết từng bộ và lọc Episode theo mùa, thêm Episode hàng loạt, tồn kho theo barcode, bulk archive và bulk sửa giá. Các thay đổi danh mục/kho chỉ dành cho Quản lý hoặc Quản trị viên và có audit.
- Phiếu trộn thuê/mua, hạn trả theo dòng, cọc, Premium, voucher, combo cố định hoặc N Episode cùng Show; thanh toán tiền mặt/chuyển khoản/ví điện tử.
- Trả từng phần, phạt, gia hạn, chuyển thuê thành mua, trả hàng bán, kiểm tra copy sau hoàn bán.
- Khách hàng, điểm uy tín có audit, Premium, đặt trước FIFO/giữ 24 giờ và đề cử phim.
- Phiếu đã lập, thông báo Email/SMS mock, thống kê theo ngày/tháng/quý/năm hoặc khoảng tùy chọn, doanh thu Premium, top thuê/bán/combo, drill-down biểu đồ tồn kho, xuất CSV/PNG.
- Mở/đóng ca; chỉ chủ ca hoặc Quản lý/Quản trị viên được đóng ca.

## Khởi động
Yêu cầu MySQL trong Laragon (cài đặt laragon) đang chạy trên `127.0.0.1:3306`, user `root` không mật khẩu.

```powershell
$py = 'C:\laragon\bin\python\python-3.13\python.exe'
& $py -m pip install -e '.[dev]'
Copy-Item .env.example .env.local
& $py -m normastore
```

Lần đầu app tự tạo `normastore_db`, chạy Alembic đến revision mới nhất, rồi thêm dữ liệu tối thiểu. Đăng nhập mặc định: `admin` / `admin123`; đổi mật khẩu ngay sau khi đăng nhập. Khi chỉ muốn chạy migration mà không mở giao diện, dùng `& $py -m alembic upgrade head` sau khi database đã được tạo.

## Backup trước migration/import

Tạo backup MySQL nhất quán trước khi import TMDB lớn hoặc nâng cấp phiên bản. File `.sql` được ghi trong `backups/` và đã bị Git bỏ qua.

```powershell
& $py scripts/backup_database.py
```

Nếu MySQL URL có password, lệnh sẽ yêu cầu nhập trực tiếp qua `mysqldump`; password không được đưa vào command line hay file backup metadata.

## Dữ liệu lớn

Không commit API key. Đặt `NORMASTORE_TMDB_API_KEY` trong `.env.local` sau khi đã thay key bị lộ, rồi chạy:

```powershell
& $py scripts/import_tmdb.py --movies 2000 --shows 100
& $py scripts/seed_demo.py --orders 25000
```

Importer lưu checkpoint trong `import_runs`; chạy lại sẽ tiếp tục trang đang dở và không tạo trùng TMDB ID. Seed dùng tên Việt Nam tự nhiên cho khách và nhân viên.

## AI search (optional)

Replace any Gemini API key that was previously exposed before using this feature. After importing the catalog, build the local embedding cache with the following command. Only the catalog item title and synopsis are sent; no customer data is sent.

```powershell
& $py scripts/build_embeddings.py --limit 100
& $py scripts/build_embeddings.py
```

The command stores 768-dimension vectors by default and is repeatable: unchanged items are skipped. If the key is missing, the provider is unavailable, or quota is exhausted, description search automatically falls back to local catalog search.

## SMTP và SMS mock

Đặt host/port/username/from vào `.env.local`. Mật khẩu SMTP không nằm trong database hay source: lưu trong Windows Credential Manager bằng service `normastore`, account `smtp`. Worker chạy mỗi 5 phút khi app mở. SMS chỉ ghi trạng thái mock. Sau khi cấu hình, dùng nút **Gửi email kiểm tra** trong Cài đặt & About; email chỉ được gửi khi người dùng bấm nút.

## Kiểm thử

```powershell
& $py -m pytest -q
& $py -m compileall -q src tests scripts alembic
```

## Đóng gói Windows

Cài dependency build rồi chạy script. MySQL/Laragon không được đóng gói; máy nhận phải có MySQL 8.4 tương thích và cấu hình `.env.local` cục bộ.

```powershell
& $py -m pip install -e '.[dev]'
& .\scripts\build_windows.ps1 -Python $py
```

Mở `installer\normastore.iss` bằng Inno Setup Compiler để tạo `dist\installer\NormaStore-Setup.exe`.

`ISCC.exe` (Inno Setup Compiler) must be installed separately to create the setup executable; the `dist\NormaStore` folder is the verified portable onedir build.

## Lưu ý TMDB

This product uses the TMDB API but is not endorsed or certified by TMDB. Nếu dùng thương mại, cần kiểm tra điều khoản cấp phép TMDB trước khi triển khai.
