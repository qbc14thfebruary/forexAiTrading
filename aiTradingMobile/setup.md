# PHẦN 1: FILE CODE ĐẦY ĐỦ CỦA: CONFIG.YMAL, RUN.PY, PROMTEN.txt
# PHẦN 2: FILE HƯỚNG DẪN CHI TIẾT SỬ DỤNG TRÊN ĐIỆN THOẠI (ANDROID)
Hướng dẫn này giúp bạn triển khai chạy toàn bộ hệ thống Bot trên trực tiếp điện thoại Android bằng công cụ Termux.

## Bước 1: Chuẩn bị API Key lấy dữ liệu giá
	Vì không dùng ứng dụng MT5 máy tính, bạn cần đăng ký một cổng truyền dữ liệu thay thế:

	Truy cập trang web: twelvedata.com
		Đăng ký một tài khoản miễn phí (Free Plan).
		Sau khi đăng ký thành công, bạn vào màn hình Dashboard sẽ thấy một chuỗi API Key của riêng bạn.
		Copy mã API Key này và lưu tạm vào ghi chú điện thoại.

## Bước 2: Cài đặt ứng dụng Termux trên điện thoại
	Để chạy được Python, bạn cần một môi trường dòng lệnh Linux:
		1. Tải ứng dụng Termux từ kho ứng dụng bảo mật F-Droid hoặc file APK chính thức trên GitHub của hãng (không nên tải trên CH Play vì phiên bản trên đó đã cũ và bị ngừng cập nhật).
		2. Mở ứng dụng Termux vừa cài đặt lên.

## Bước 3: Thiết lập môi trường Linux và Python trong Termux
	Hãy copy và dán lần lượt từng câu lệnh dưới đây vào màn hình Termux và nhấn Enter:

		1. Cập nhật hệ thống lõi:
			Bash:	pkg update && pkg upgrade -y

		2. Cấp quyền truy cập bộ nhớ điện thoại để lát nữa copy file code vào:
			Bash:	termux-setup-storage

		3. Cài đặt Python, Trình quản lý thư viện và các công cụ biên dịch:
			Bash:	pkg install python ndk-sysroot clang make -y

		4. Cài đặt các thư viện bổ trợ xử lý dữ liệu và đọc cấu hình của Bot:
			Bash:	pip install pandas requests pyyaml

## Bước 4: Tạo và chỉnh sửa file code trên điện thoại
	Để thuận tiện cho việc tạo các file run.py, configGG.yaml và promptEN.txt ngay trên điện thoại:

		1. Di chuyển vào thư mục lưu trữ của Termux:
			Bash:	cd ~ mkdir ytc_bot && cd ytc_bot

		2. Cài đặt trình chỉnh sửa file nhanh (Micro):
			Bash:	pkg install micro -y

		3. Tạo và chỉnh sửa file cấu hình configGG.yaml và lưu file:
			Bash:	micro configGG.yaml

			Mẹo: Bạn copy toàn bộ nội dung của file cấu hình ở Phần 1 đã chuẩn bị sẵn, dán vào đây.
			Đặc biệt lưu ý: Nhớ thay thế dòng YOUR_TWELVE_DATA_API_KEY bằng API Key bạn đã lấy ở Bước 1.
			Nhấn tổ hợp phím Ctrl + S để Lưu và Ctrl + Q để thoát ra ngoài.

		4. Tạo file code chính run.py và lưu file:
			Bash:	micro run.py

			Dán toàn bộ mã nguồn python ở mục 2 của Phần 1 vào đây.
			Nhấn tổ hợp phím Ctrl + S để Lưu và Ctrl + Q để thoát.

		5. Tạo file promptEN.txt và lưu file:
			Bash:	micro promptEN.txt

			Dán mẫu prompt tiếng Anh hiện có của bạn vào đây, lưu lại và thoát ra ngoài.

## Bước 5: Chạy Bot và tận hưởng thành quả 🎉
	Sau khi chuẩn bị đủ 3 file trên trong cùng một thư mục ytc_bot, bạn chỉ cần gõ lệnh sau để khởi động:

	Bash: python run.py

	Kết quả hiển thị: Bạn sẽ thấy màn hình log của Termux ghi rõ: Bot YTC Cloud đã khởi động thành công cho XAUUSD và bắt đầu tiến trình chờ đóng nến M5 để gửi phân tích trực tiếp lên nhóm Telegram của bạn.
	Cách đóng Bot: Khi không muốn chạy nữa, bạn chỉ cần nhấn giữ màn hình Termux chọn phím điều hướng và bấm Ctrl + C để tắt bot một cách an toàn.

# PHẦN 3: FILE HƯỚNG DẪN CHI TIẾT SỬ DỤNG TRÊN ĐIỆN THOẠI (IOS)
Hướng dẫn này giúp bạn triển khai chạy toàn bộ hệ thống Bot trên trực tiếp điện thoại IOS bằng ứng dụng "iPhython" (a-Shell / Pyto)

	## Bước 1: Cài đặt ứng dụng trên App Store
		Lên App Store trên iPhone, tìm và tải ứng dụng a-Shell (hoặc a-Shell mini). Đây là ứng dụng giả lập terminal Unix cực mạnh cho iOS hỗ trợ sẵn Python.

	##Bước 2: Chuẩn bị file trên iPhone
		1. Mở ứng dụng Tệp (Files) mặc định trên iPhone của bạn.

		2. Tạo một thư mục mới tên là ytc_bot trong mục Trên iPhone (On My iPhone) > a-Shell.

		3. Copy 3 file (run.py, configGG.yaml, promptEN.txt) vào thư mục ytc_bot vừa tạo.

		4. Mở file config.yaml bằng bất kỳ app soạn thảo văn bản nào trên iPhone để điền đầy đủ API Key (Twelve Data, Gemini, Telegram) của bạn rồi lưu lại.

	## Bước 3: Cài đặt thư viện và chạy trên a-Shell
		1. Mở ứng dụng a-Shell trên iPhone lên.

		2. Di chuyển vào thư mục chứa bot:
			Bash:	cd ytc_bot

		3. Cài đặt các thư viện cần thiết (a-Shell sử dụng lệnh pip install trực tiếp):
			Bash:	pip install pandas requests pyyaml

		4. Khởi động bot:
			Bash:	python run.py