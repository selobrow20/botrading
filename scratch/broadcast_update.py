import sys
sys.path.insert(0, ".")
from notify.telegram_bot import TelegramNotifier

notifier = TelegramNotifier()

caption = (
    "🚀 <b>UPDATE RESMI: AUTO-COPIER MT5 MEMBER (EDISI ULTRA-STABIL ANTI-DISCONNECT)</b> 🚀\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "Halo Trader VIP! Pembaruan penting telah dirilis untuk menjamin kestabilan koneksi 24/7 tanpa henti.\n\n"
    "✨ <b>PERBAIKAN & PENINGKATAN:</b>\n"
    "1️⃣ <b>Fix WinError 64 & Anti-Disconnect (Keepalive Heartbeat):</b>\n"
    "   • Menambahkan detak jantung (ping 20 detik) ke Telegram MTProto.\n"
    "   • Mencegah timeout koneksi/socket putus saat menunggu sinyal dari router atau ISP lokal (Indihome/Telkomsel/dll).\n\n"
    "2️⃣ <b>Koneksi MT5 Stabil Tanpa Kedip / Mati-Nyala:</b>\n"
    "   • Copier langsung menempel (silent attach) ke terminal MT5 aktif tanpa proses login ulang berkali-kali.\n"
    "   • Terminal MT5 tetap tenang dan tidak akan putus-nyambung lagi.\n\n"
    "3️⃣ <b>Deteksi Cerdas Akun Cent (USC) & Standard (USD):</b>\n"
    "   • 100% otomatis menyesuaikan lot dan simbol (<code>XAUUSDc</code> / <code>XAUUSD</code>) sesuai akun Anda.\n\n"
    "📁 <b>CARA UPDATE SANGAT MUDAH:</b>\n"
    "1. Matikan copier lama (tutup jendela hitam CMD jika sedang jalan).\n"
    "2. Unduh file <code>member_copier.zip</code> di bawah ini.\n"
    "3. Ekstrak (Extract Here) dan timpa file lama di folder copier Anda.\n"
    "4. Klik 2x <b>START_COPIER.bat</b>.\n"
    "━━━━━━━━━━━━━━━━━━━━━━\n"
    "<i>Koneksi kini ultra-stabil dan siap menduplikasi sinyal Grade A+ 9 Buku PDF secara presisi!</i>"
)

res = notifier.broadcast_copier_update(zip_path="member_copier.zip", custom_caption=caption)
print("Broadcast result:", res)
