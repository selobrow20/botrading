import sys
sys.path.insert(0, ".")
from notify.telegram_bot import TelegramNotifier

notifier = TelegramNotifier()

caption = (
    "🚀 <b>UPDATE RESMI: AUTO-COPIER MT5 v2.6.1 (1:1 MULTI-LAYER & PRECISION SYNC)</b> 🚀\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "Halo Trader VIP! Pembaruan penting v2.6.1 telah dirilis untuk memastikan seluruh layer posisi Master tersalin 1:1 secara sempurna ke MT5 Member.\n\n"
    "✨ <b>PERBAIKAN & PENINGKATAN v2.6.1:</b>\n"
    "1️⃣ <b>Sinkronisasi Posisi Presisi 1:1:</b>\n"
    "   • Toleransi pengecekan duplikasi dipersempit ke <b>$0.40 USD (4 pips)</b> (sebelumnya $2.00 terlalu lebar).\n"
    "   • Seluruh ladder limit order Master (misal: 4123, 4127, 4129) dipastikan masuk 100% tanpa ada yang terlewat/diabaikan.\n\n"
    "2️⃣ <b>Dukungan Multi-Layer Sesi US (Maks 4 Layer):</b>\n"
    "   • Kuota layer untuk Sesi US (19:00 - 24:00 WIB) kini mendukung hingga <b>4 layer posisi</b> sekaligus sesuai strategi Order Block & FVG.\n\n"
    "3️⃣ <b>Fixed Quota Replacement & Anti-Stacking Bypass:</b>\n"
    "   • Kuota limit order tidak akan menghapus pending order sebelumnya jika slot masih tersedia.\n"
    "   • Eksekusi sinyal order limit terjemput dari Master diprioritaskan instan tanpa hambatan minimum spacing.\n\n"
    "4️⃣ <b>Aturan Lot Tetap Konsisten:</b>\n"
    "   • Akun Cent (USC): <b>0.05 lot</b> (semua sesi).\n"
    "   • Akun Standard (USD): <b>0.01 lot</b>.\n\n"
    "📁 <b>CARA UPDATE:</b>\n"
    "• Bagi copier yang sedang aktif: <b>Otomatis ter-reload dalam 30 detik (OTA Update)</b>.\n"
    "• Atau cukup tutup copier lalu jalankan ulang <b>START_COPIER.bat</b>.\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "<i>Copier kini 100% sinkron 1:1 dengan posisi live Master MT5!</i>"
)

res = notifier.broadcast_copier_update(zip_path="member_copier.zip", custom_caption=caption)
print("Broadcast result:", res)
