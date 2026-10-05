import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
from matplotlib.patches import Rectangle
import numpy as np
import pandas as pd
import re

dates = pd.date_range('2026-09-27 10:00', periods=50, freq='15min')
closes = [4270.0 + np.sin(i/3)*10 + i*0.2 for i in range(50)]
highs = [c + np.random.uniform(0.5, 2.5) for c in closes]
lows = [c - np.random.uniform(0.5, 2.5) for c in closes]
opens = [c - np.random.uniform(-1, 1) for c in closes]
df_plot = pd.DataFrame({'Open': opens, 'High': highs, 'Low': lows, 'Close': closes, 'Volume': [1500]*50}, index=dates)

n_bars = len(df_plot)
close_series = df_plot['Close']
df_plot['EMA_20'] = close_series.ewm(span=20, adjust=False).mean()
df_plot['EMA_50'] = close_series.ewm(span=50, adjust=False).mean()
df_plot['Volume_SMA_20'] = df_plot['Volume'].rolling(20, min_periods=1).mean()

# TradingView Palette
bg_color = '#131722'       # TV Canvas Background
canvas_color = '#131722'   # TV Panel Background
grid_color = '#242832'     # TV Subtle Grid
text_color = '#d1d4dc'     # TV Primary Text
subtext_color = '#787b86'  # TV Secondary Text
tv_green = '#089981'       # TV Up Bar
tv_red = '#f23645'         # TV Down Bar
tv_blue = '#2962ff'        # TV Active / Blue Accent
ema20_color = '#f59e0b'    # Amber
ema50_color = '#00bcd4'    # Cyan
rsi_color = '#7e57c2'      # TV Purple

fig, (ax_main, ax_vol, ax_rsi) = plt.subplots(
    nrows=3, ncols=1, figsize=(13, 8.5), dpi=130, sharex=True,
    gridspec_kw={'height_ratios': [3.6, 0.85, 1.0], 'hspace': 0.04}
)
fig.patch.set_facecolor(bg_color)

for ax in (ax_main, ax_vol, ax_rsi):
    ax.set_facecolor(canvas_color)
    ax.yaxis.tick_right()
    ax.yaxis.set_label_position('right')
    ax.grid(True, linestyle='--', linewidth=0.5, color=grid_color, alpha=0.5)
    ax.tick_params(colors=subtext_color, labelsize=8.5, right=True, left=False)
    for spine in ax.spines.values():
        spine.set_color(grid_color)
    ax.spines['left'].set_visible(False)

x_coords = np.arange(n_bars)
body_width = 0.68
wick_width = 1.1

# Background TV Watermark
ax_main.text(0.5, 0.48, 'XAUUSD  15m', transform=ax_main.transAxes, color='#1c202e', fontsize=36, weight='heavy', ha='center', va='center', zorder=0)
ax_main.text(0.5, 0.32, 'TradingView', transform=ax_main.transAxes, color='#181c28', fontsize=20, weight='bold', ha='center', va='center', zorder=0)

# Candlesticks
for i in range(n_bars):
    row = df_plot.iloc[i]
    c_open, c_high, c_low, c_close = float(row['Open']), float(row['High']), float(row['Low']), float(row['Close'])
    is_up = c_close >= c_open
    c_color = tv_green if is_up else tv_red
    ax_main.vlines(x=i, ymin=c_low, ymax=c_high, color=c_color, linewidth=wick_width, zorder=2)
    b_bot = min(c_open, c_close)
    b_h = max(abs(c_close - c_open), (c_high - c_low) * 0.02)
    rect = Rectangle((i - body_width/2.0, b_bot), body_width, b_h, facecolor=c_color, edgecolor=c_color, linewidth=0.6, zorder=3)
    ax_main.add_patch(rect)

# EMAs
ax_main.plot(x_coords, df_plot['EMA_20'], color=ema20_color, linewidth=1.3, zorder=4)
ax_main.plot(x_coords, df_plot['EMA_50'], color=ema50_color, linewidth=1.3, zorder=4)

last_close = float(df_plot['Close'].iloc[-1])
last_open = float(df_plot['Open'].iloc[-1])
last_high = float(df_plot['High'].iloc[-1])
last_low = float(df_plot['Low'].iloc[-1])
chg = last_close - float(df_plot['Close'].iloc[-2])
chg_pct = (chg / float(df_plot['Close'].iloc[-2])) * 100.0
chg_color = tv_green if chg >= 0 else tv_red

# TradingView Header inside chart
ax_main.text(0.015, 0.94, 'XAUUSD · 15 · OANDA · TradingView', transform=ax_main.transAxes, color=text_color, fontsize=11, weight='bold')
ax_main.text(0.015, 0.88, f'O {last_open:.2f}  H {last_high:.2f}  L {last_low:.2f}  C {last_close:.2f}  {chg:+,.2f} ({chg_pct:+.2f}%)', transform=ax_main.transAxes, color=chg_color, fontsize=9.5, weight='bold')
ema20_last = df_plot['EMA_20'].iloc[-1]
ema50_last = df_plot['EMA_50'].iloc[-1]
ax_main.text(0.015, 0.82, f'EMA 20 {ema20_last:.2f}    EMA 50 {ema50_last:.2f}', transform=ax_main.transAxes, color=subtext_color, fontsize=8.5)

# Entry / TP / SL
entry_price = 4276.0
tp_price = 4242.0
sl_price = 4287.0
ax_main.axhline(entry_price, color=tv_blue, linestyle='--', linewidth=1.1, alpha=0.9, zorder=5)
ax_main.axhline(tp_price, color=tv_green, linestyle='--', linewidth=1.1, alpha=0.9, zorder=5)
ax_main.axhline(sl_price, color=tv_red, linestyle='--', linewidth=1.1, alpha=0.9, zorder=5)

# Right Axis Price formatting
y_max = max(df_plot['High'].max(), sl_price) + 3
y_min = min(df_plot['Low'].min(), tp_price) - 3
ax_main.set_ylim(y_min, y_max)
ax_main.yaxis.set_major_formatter(ticker.FormatStrFormatter('$%.2f'))

# Live Price & Level Pills on right scale
ax_main.text(n_bars + 0.3, last_close, f' {last_close:.2f} ', color='#ffffff', fontsize=8.5, weight='bold', va='center', bbox=dict(facecolor=tv_blue, edgecolor='none', boxstyle='round,pad=0.25'))
ax_main.text(n_bars + 0.3, tp_price, f' TP {tp_price:.2f} ', color='#ffffff', fontsize=8, weight='bold', va='center', bbox=dict(facecolor=tv_green, edgecolor='none', boxstyle='round,pad=0.25'))
ax_main.text(n_bars + 0.3, sl_price, f' SL {sl_price:.2f} ', color='#ffffff', fontsize=8, weight='bold', va='center', bbox=dict(facecolor=tv_red, edgecolor='none', boxstyle='round,pad=0.25'))

# Volume
vol_colors = [tv_green if df_plot['Close'].iloc[j] >= df_plot['Open'].iloc[j] else tv_red for j in range(n_bars)]
ax_vol.bar(x_coords, df_plot['Volume'], color=vol_colors, width=body_width, alpha=0.55, zorder=2)
ax_vol.plot(x_coords, df_plot['Volume_SMA_20'], color=tv_blue, linewidth=0.9, linestyle='-', zorder=3)
vol_last = df_plot['Volume'].iloc[-1]
vol_ma_last = df_plot['Volume_SMA_20'].iloc[-1]
ax_vol.text(0.015, 0.78, f'Vol {vol_last:,.0f}   Vol MA20 {vol_ma_last:,.0f}', transform=ax_vol.transAxes, color=subtext_color, fontsize=8)

# RSI
delta = df_plot['Close'].diff()
gain = (delta.where(delta > 0, 0)).rolling(14, min_periods=1).mean()
loss = (-delta.where(delta < 0, 0)).rolling(14, min_periods=1).mean()
rs = gain / (loss.replace(0, 1e-9))
rsi_s = 100 - (100 / (1 + rs))
ax_rsi.plot(x_coords, rsi_s, color=rsi_color, linewidth=1.3)
ax_rsi.axhline(70, color='#787b86', linestyle='--', linewidth=0.7, alpha=0.6)
ax_rsi.axhline(30, color='#787b86', linestyle='--', linewidth=0.7, alpha=0.6)
ax_rsi.fill_between(x_coords, 30, 70, color=rsi_color, alpha=0.08)
ax_rsi.set_ylim(10, 90)
ax_rsi.text(0.015, 0.78, f'RSI 14 close {rsi_s.iloc[-1]:.1f}', transform=ax_rsi.transAxes, color=subtext_color, fontsize=8)

# Dates
date_indices = np.linspace(0, n_bars - 1, min(7, n_bars), dtype=int)
time_labels = [str(df_plot.index[idx])[5:16].replace('-', '/') for idx in date_indices]
ax_rsi.set_xticks(date_indices)
ax_rsi.set_xticklabels(time_labels, rotation=0, ha='center', fontsize=8, color=subtext_color)
ax_main.set_xlim(-1, n_bars + 4.5)

# Watermark bottom right
fig.text(0.985, 0.012, 'TradingView Style Pro Engine', color='#363a45', fontsize=8, ha='right', weight='bold')

plt.savefig('scratch/tv_style_sample.png', facecolor=fig.get_facecolor(), bbox_inches='tight', pad_inches=0.15, dpi=130)
print('Saved scratch/tv_style_sample.png successfully!')
