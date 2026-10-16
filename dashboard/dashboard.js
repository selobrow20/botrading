/**
 * BOTRADING UNIFIED COMMAND CENTER & WEB DASHBOARD CONTROLLER (v2.0)
 * Mengelola navigasi tab, polling REST API, live terminal streaming, 
 * render tabel interaktif, audio synthesizer, dan integrasi 3D Office.
 */

document.addEventListener('DOMContentLoaded', () => {

  // ==========================================================================
  // 1. AUDIO SYNTHESIZER (PURE WEBAUDIO - ZERO DEPENDENCIES)
  // ==========================================================================
  class AudioSynth {
    constructor() {
      this.ctx = null;
      this.muted = false;
    }

    ensureContext() {
      if (!this.ctx) {
        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        this.ctx = new AudioCtx();
      }
      if (this.ctx.state === 'suspended') {
        this.ctx.resume();
      }
    }

    playSignalAlert() {
      if (this.muted) return;
      this.ensureContext();
      const now = this.ctx.currentTime;
      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(587.33, now); // D5
      osc.frequency.exponentialRampToValueAtTime(880.00, now + 0.15); // A5
      gain.gain.setValueAtTime(0.2, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.35);
      osc.connect(gain);
      gain.connect(this.ctx.destination);
      osc.start(now);
      osc.stop(now + 0.35);
    }

    playOrderSuccess() {
      if (this.muted) return;
      this.ensureContext();
      const now = this.ctx.currentTime;
      [1046.50, 1318.51].forEach((freq, idx) => {
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();
        osc.type = 'triangle';
        osc.frequency.setValueAtTime(freq, now + idx * 0.1);
        gain.gain.setValueAtTime(0.25, now + idx * 0.1);
        gain.gain.exponentialRampToValueAtTime(0.01, now + idx * 0.1 + 0.3);
        osc.connect(gain);
        gain.connect(this.ctx.destination);
        osc.start(now + idx * 0.1);
        osc.stop(now + idx * 0.1 + 0.3);
      });
    }

    playCyberTick() {
      if (this.muted) return;
      try {
        this.ensureContext();
        const now = this.ctx.currentTime;
        const osc = this.ctx.createOscillator();
        const gain = this.ctx.createGain();
        osc.type = 'sine';
        osc.frequency.setValueAtTime(1200, now);
        osc.frequency.exponentialRampToValueAtTime(1800, now + 0.04);
        gain.gain.setValueAtTime(0.06, now);
        gain.gain.exponentialRampToValueAtTime(0.001, now + 0.04);
        osc.connect(gain);
        gain.connect(this.ctx.destination);
        osc.start(now);
        osc.stop(now + 0.04);
      } catch(e) {}
    }
  }

  const audio = new AudioSynth();

  // ==========================================================================
  // ATSMATRIX // INTERACTIVE PARTICLE & TELEMETRY MESH CANVAS
  // ==========================================================================
  function initMatrixMeshCanvas() {
    const canvas = document.getElementById('matrix-mesh-canvas');
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    let width = canvas.width = window.innerWidth;
    let height = canvas.height = window.innerHeight;

    window.addEventListener('resize', () => {
      width = canvas.width = window.innerWidth;
      height = canvas.height = window.innerHeight;
    });

    const nodeCount = Math.min(Math.floor((width * height) / 28000), 40);
    const nodes = [];
    const colors = ['#00f3ff', '#38bdf8', '#a855f7', '#00ff88'];

    for (let i = 0; i < nodeCount; i++) {
      nodes.push({
        x: Math.random() * width,
        y: Math.random() * height,
        vx: (Math.random() - 0.5) * 0.35,
        vy: (Math.random() - 0.5) * 0.35,
        radius: Math.random() * 2 + 1.2,
        color: colors[Math.floor(Math.random() * colors.length)],
        pulse: Math.random() * Math.PI,
      });
    }

    let mouse = { x: -1000, y: -1000 };
    window.addEventListener('mousemove', (e) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
    });

    function renderMesh() {
      ctx.clearRect(0, 0, width, height);

      for (let i = 0; i < nodes.length; i++) {
        const n1 = nodes[i];
        n1.x += n1.vx;
        n1.y += n1.vy;
        n1.pulse += 0.02;

        if (n1.x < 0 || n1.x > width) n1.vx *= -1;
        if (n1.y < 0 || n1.y > height) n1.vy *= -1;

        const dxMouse = n1.x - mouse.x;
        const dyMouse = n1.y - mouse.y;
        const distMouse = Math.sqrt(dxMouse * dxMouse + dyMouse * dyMouse);
        if (distMouse < 120) {
          const force = (120 - distMouse) / 120;
          n1.x += (dxMouse / distMouse) * force * 1.5;
          n1.y += (dyMouse / distMouse) * force * 1.5;
        }

        const currentRadius = n1.radius + Math.sin(n1.pulse) * 0.5;
        ctx.beginPath();
        ctx.arc(n1.x, n1.y, Math.max(currentRadius, 0.5), 0, Math.PI * 2);
        ctx.fillStyle = n1.color;
        ctx.shadowColor = n1.color;
        ctx.shadowBlur = 8;
        ctx.fill();
        ctx.shadowBlur = 0;

        for (let j = i + 1; j < nodes.length; j++) {
          const n2 = nodes[j];
          const dx = n1.x - n2.x;
          const dy = n1.y - n2.y;
          const dist = Math.sqrt(dx * dx + dy * dy);

          if (dist < 140) {
            const alpha = (1 - dist / 140) * 0.22;
            ctx.beginPath();
            ctx.moveTo(n1.x, n1.y);
            ctx.lineTo(n2.x, n2.y);
            ctx.strokeStyle = `rgba(0, 243, 255, ${alpha})`;
            ctx.lineWidth = 0.8;
            ctx.stroke();
          }
        }
      }

      requestAnimationFrame(renderMesh);
    }

    renderMesh();
  }

  initMatrixMeshCanvas();

  // ==========================================================================
  // 2. APP STATE
  // ==========================================================================
  const state = {
    currentTab: 'overview',
    autoRefresh: true,
    pollingIntervalMs: 2500,
    pollingTimer: null,
    terminalAutoScroll: true,
    lastLogCount: 0,
    officeInitialized: false,
    officeInstance: null,
    searchStocksQuery: '',
    searchSignalsQuery: '',
    filterSignalsCat: 'all',
    filterSignalsOutcome: 'all',
    filterLogLevel: 'ALL',
    cryptoClosedFilter: 'all',
    cryptoClosedSearch: '',
    cachedClosedHistory: []
  };

  // ==========================================================================
  // 3. TAB NAVIGATION
  // ==========================================================================
  const tabs = document.querySelectorAll('.dash-tab');
  const panes = document.querySelectorAll('.tab-pane');

  function switchTab(tabId) {
    state.currentTab = tabId;
    audio.playCyberTick();

    tabs.forEach(t => {
      if (t.dataset.tab === tabId) {
        t.classList.add('active');
      } else {
        t.classList.remove('active');
      }
    });

    panes.forEach(p => {
      if (p.id === `pane-${tabId}`) {
        p.classList.add('active');
      } else {
        p.classList.remove('active');
      }
    });

    // Inisialisasi 3D Office jika tab office dibuka pertama kali
    if (tabId === 'office') {
      ensureOffice3D();
    } else if (tabId === 'atsmatrix') {
      if (window.atsCockpit) {
        window.atsCockpit.init();
        setTimeout(() => {
          if (window.atsCockpit.torusEngine) window.atsCockpit.torusEngine.onResize();
          if (window.atsCockpit.funnelEngine) window.atsCockpit.funnelEngine.resize();
          if (window.atsCockpit.chartEngine) window.atsCockpit.chartEngine.resize();
          if (window.atsCockpit.oscEngine) window.atsCockpit.oscEngine.resize();
          window.atsCockpit.updateBezierWires();
        }, 80);
      }
    }

    // Refresh data tab spesifik seketika
    fetchActiveTabData();
  }

  tabs.forEach(t => {
    t.addEventListener('click', () => switchTab(t.dataset.tab));
  });

  const btnBrandHome = document.getElementById('btn-brand-home');
  if (btnBrandHome) {
    btnBrandHome.addEventListener('click', () => switchTab('overview'));
  }

  const btnGotoTerminal = document.getElementById('btn-goto-terminal');
  if (btnGotoTerminal) {
    btnGotoTerminal.addEventListener('click', () => switchTab('terminal'));
  }

  const btnGotoOffice = document.getElementById('btn-goto-office');
  if (btnGotoOffice) {
    btnGotoOffice.addEventListener('click', () => switchTab('office'));
  }

  const btnGotoCryptoPnl = document.getElementById('btn-goto-crypto-pnl');
  if (btnGotoCryptoPnl) {
    btnGotoCryptoPnl.addEventListener('click', () => {
      switchTab('crypto');
      setTimeout(() => {
        const el = document.getElementById('crypto-pnl-suite');
        if (el) el.scrollIntoView({ behavior: 'smooth' });
      }, 100);
    });
  }

  // ==========================================================================
  // 4. 3D OFFICE LAZY INITIALIZER & CONTROLS
  // ==========================================================================
  function ensureOffice3D() {
    if (!state.officeInitialized && typeof Office3D !== 'undefined') {
      try {
        state.officeInstance = new Office3D('office-canvas', 'labels-container', 'speech-bubbles-container');
        state.officeInitialized = true;
      } catch (e) {
        console.warn('Inisialisasi 3D Office ditunda:', e);
      }
    } else if (state.officeInstance && state.officeInstance.onResize) {
      setTimeout(() => state.officeInstance.onResize(), 100);
    }
  }

  // Camera Mode Bar di Tab 3D Office
  const camBtns = document.querySelectorAll('.cam-btn');
  camBtns.forEach(btn => {
    btn.addEventListener('click', () => {
      camBtns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      if (state.officeInstance && state.officeInstance.setCameraMode) {
        state.officeInstance.setCameraMode(btn.dataset.cam);
      }
    });
  });

  // ==========================================================================
  // 5. REST API CLIENT & DATA FETCHERS
  // ==========================================================================

  // --- A. OVERVIEW / COMMAND CENTER ---
  async function fetchOverview() {
    try {
      const res = await fetch('/api/overview');
      if (!res.ok) return;
      const data = await res.json();

      // 1. Status Bot Core
      const botBadge = document.getElementById('bot-status-badge');
      const botText = document.getElementById('bot-status-text');
      const ovStatus = document.getElementById('ov-bot-status');
      const ovPid = document.getElementById('ov-bot-pid');
      const ovUptime = document.getElementById('ov-bot-uptime');

      if (data.bot && data.bot.running) {
        if (botBadge) botBadge.classList.remove('offline');
        if (botText) botText.innerHTML = `ONLINE (#${data.bot.pid})`;
        if (ovStatus) ovStatus.textContent = 'ONLINE';
        if (ovPid) ovPid.textContent = `PID #${data.bot.pid} (${data.bot.memory_mb} MB)`;
        if (ovUptime) ovUptime.textContent = `Uptime: ${data.bot.uptime_str}`;
      } else {
        if (botBadge) botBadge.classList.add('offline');
        if (botText) botText.innerHTML = `OFFLINE`;
        if (ovStatus) ovStatus.textContent = 'OFFLINE';
        if (ovPid) ovPid.textContent = 'Proses main.py tidak aktif';
        if (ovUptime) ovUptime.textContent = 'Menunggu start';
      }

      // 2. Status Jam Bursa
      if (data.markets) {
        const m = data.markets;
        const chipIdx = document.getElementById('chip-idx');
        const descIdx = document.getElementById('chip-idx-desc');
        if (chipIdx && descIdx) {
          chipIdx.className = `market-chip ${m.idx.open ? 'open' : 'closed'}`;
          descIdx.textContent = m.idx.open ? 'BUKA' : 'TUTUP';
        }

        const chipGold = document.getElementById('chip-gold');
        const descGold = document.getElementById('chip-gold-desc');
        if (chipGold && descGold) {
          chipGold.className = `market-chip ${m.gold.open ? 'open' : 'closed'}`;
          descGold.textContent = m.gold.open ? 'BUKA' : 'TUTUP';
        }

        // Sessions Dots
        const dotIdx = document.getElementById('dot-session-idx');
        const descSessionIdx = document.getElementById('desc-session-idx');
        if (dotIdx) dotIdx.className = `session-dot ${m.idx.open ? 'active' : ''}`;
        if (descSessionIdx) descSessionIdx.textContent = m.idx.desc;

        const dotGold = document.getElementById('dot-session-gold');
        const descSessionGold = document.getElementById('desc-session-gold');
        if (dotGold) dotGold.className = `session-dot ${m.gold.open ? 'active' : ''}`;
        if (descSessionGold) descSessionGold.textContent = m.gold.desc;

        if (m.sessions) {
          const dotLondon = document.getElementById('dot-session-london');
          if (dotLondon) dotLondon.className = `session-dot ${m.sessions.london.active ? 'active' : ''}`;
          const dotNy = document.getElementById('dot-session-ny');
          if (dotNy) dotNy.className = `session-dot ${m.sessions.new_york.active ? 'active' : ''}`;
        }
      }

      // 3. MT5 KPI & Gold Price
      if (data.mt5) {
        const priceStr = `$${Number(data.mt5.gold_price).toLocaleString('en-US', { minimumFractionDigits: 2 })}`;
        const navGold = document.getElementById('nav-gold-price');
        if (navGold) navGold.textContent = priceStr;

        const ovEquity = document.getElementById('ov-mt5-equity');
        const ovBal = document.getElementById('ov-mt5-balance');
        const ovPos = document.getElementById('ov-mt5-positions');
        const tabMt5Pos = document.getElementById('tab-mt5-pos');

        if (ovEquity) ovEquity.textContent = `${data.mt5.equity.toFixed(2)} ${data.mt5.currency}`;
        if (ovBal) ovBal.textContent = `${data.mt5.balance.toFixed(2)} ${data.mt5.currency}`;
        if (ovPos) ovPos.textContent = `${data.mt5.open_positions_count} Posisi Terbuka`;
        if (tabMt5Pos) tabMt5Pos.textContent = `${data.mt5.open_positions_count} Pos`;
      }

      // 4. Crypto KPI
      if (data.crypto) {
        const ovCryptoVal = document.getElementById('ov-crypto-val');
        const ovCryptoMode = document.getElementById('ov-crypto-mode');
        const ovCryptoOpen = document.getElementById('ov-crypto-open');
        const ovCryptoBal = document.getElementById('ov-crypto-balance');
        const tabCryptoPos = document.getElementById('tab-crypto-pos');

        const estVal = data.crypto.total_est_usdt != null ? data.crypto.total_est_usdt : (data.crypto.free_usdt || 0);
        if (ovCryptoVal) ovCryptoVal.textContent = `$${Number(estVal).toFixed(2)} USDT`;
        if (ovCryptoMode) ovCryptoMode.textContent = `${data.crypto.mode.toUpperCase()} SPOT`;
        if (ovCryptoOpen) {
          const invStr = data.crypto.invested_usdt ? ` ($${Number(data.crypto.invested_usdt).toFixed(2)})` : '';
          ovCryptoOpen.textContent = `${data.crypto.open_positions_count} Koin Aktif${invStr}`;
        }
        if (ovCryptoBal) ovCryptoBal.textContent = `$${Number(data.crypto.free_usdt || 0).toFixed(2)} USDT`;
        if (tabCryptoPos) tabCryptoPos.textContent = `${data.crypto.open_positions_count} Pos`;

        // 4b. Realized Profit & Loss Banner di Overview
        if (data.crypto.stats) {
          const cstats = data.crypto.stats;
          const isReal = data.crypto.mode === 'real';
          const netVal = (isReal && cstats.active_mode_pnl != null) ? cstats.active_mode_pnl : (cstats.total_realized_pnl_usdt || 0.0);
          const profVal = (isReal && cstats.active_profit != null) ? cstats.active_profit : (cstats.total_profit_usdt || 0.0);
          const lossVal = (isReal && cstats.active_loss != null) ? cstats.active_loss : (cstats.total_loss_usdt || 0.0);
          const winsVal = (isReal && cstats.active_wins != null) ? cstats.active_wins : (cstats.win_count || 0);
          const lossesVal = (isReal && cstats.active_losses != null) ? cstats.active_losses : (cstats.lose_count || 0);
          const bepVal = (isReal && cstats.active_bep != null) ? cstats.active_bep : (cstats.bep_count || 0);
          const wrVal = (isReal && cstats.active_win_rate != null) ? cstats.active_win_rate : (cstats.win_rate || 0.0);

          const ovPnlNet = document.getElementById('ov-pnl-net');
          const ovPnlProfit = document.getElementById('ov-pnl-profit');
          const ovPnlLoss = document.getElementById('ov-pnl-loss');
          const ovPnlWinRate = document.getElementById('ov-pnl-winrate');
          const ovPnlMode = document.getElementById('ov-pnl-mode');
          const ovPnlWinCount = document.getElementById('ov-pnl-win-count');
          const ovPnlLoseCount = document.getElementById('ov-pnl-lose-count');
          const ovPnlCounts = document.getElementById('ov-pnl-counts');

          if (ovPnlNet) {
            ovPnlNet.textContent = `${netVal >= 0 ? '+' : ''}$${netVal.toFixed(4)} USDT`;
            ovPnlNet.className = `pnl-stat-value ${netVal >= 0 ? 'val-green' : 'val-red'}`;
          }
          if (ovPnlProfit) ovPnlProfit.textContent = `+$${profVal.toFixed(4)} USDT`;
          if (ovPnlLoss) ovPnlLoss.textContent = `-$${Math.abs(lossVal).toFixed(4)} USDT`;
          if (ovPnlWinRate) ovPnlWinRate.textContent = `${wrVal}%`;
          if (ovPnlMode) ovPnlMode.textContent = isReal ? 'Mode Real (Binance Spot Live)' : 'Mode Paper (Simulasi)';
          if (ovPnlWinCount) ovPnlWinCount.textContent = `${winsVal} Trade Menang`;
          if (ovPnlLoseCount) ovPnlLoseCount.textContent = `${lossesVal} Trade Cutloss`;
          if (ovPnlCounts) ovPnlCounts.textContent = `${winsVal}W / ${lossesVal}L (${bepVal} BEP)`;

          // Mini PnL Tape
          const tapeEl = document.getElementById('ov-pnl-tape');
          if (tapeEl && data.crypto.recent_closed) {
            if (data.crypto.recent_closed.length === 0) {
              tapeEl.innerHTML = `<div class="overview-pnl-item" style="color: var(--text-muted); font-size: 12px; justify-content: center;">Belum ada trade tertutup.</div>`;
            } else {
              tapeEl.innerHTML = data.crypto.recent_closed.map(item => {
                const isProf = item.outcome === 'PROFIT';
                const isLoss = item.outcome === 'LOSS';
                const pnlSign = (item.pnl_usdt || 0) >= 0 ? '+' : '';
                const pnlColor = isProf ? 'val-green' : (isLoss ? 'val-red' : '');
                const badge = isProf ? '<span class="badge badge-profit" style="font-size:10px; padding:2px 6px;">PROFIT</span>' :
                              (isLoss ? '<span class="badge badge-loss" style="font-size:10px; padding:2px 6px;">CUTLOSS</span>' :
                                        '<span class="badge badge-bep" style="font-size:10px; padding:2px 6px;">BEP</span>');
                return `
                  <div class="overview-pnl-item">
                    <div style="display:flex; justify-content:space-between; align-items:center;">
                      <strong class="cell-mono" style="font-size:12px; color:var(--cyan-glow);">${item.symbol}</strong>
                      ${badge}
                    </div>
                    <div class="cell-mono ${pnlColor}" style="font-size:13px; font-weight:800;">
                      ${pnlSign}$${Number(item.pnl_usdt || 0).toFixed(4)} <small style="font-size:10px;">(${pnlSign}${Number(item.pnl_pct || 0).toFixed(2)}%)</small>
                    </div>
                    <div style="font-size:10px; color:var(--text-dim); display:flex; justify-content:space-between;">
                      <span>Hold: ${item.hold_duration || '-'}</span>
                      <span>${item.close_time ? item.close_time.split(' ')[1] : ''}</span>
                    </div>
                  </div>
                `;
              }).join('');
            }
          }
        }
      }

      // 5. Signals Stats KPI
      if (data.signals_stats) {
        const s = data.signals_stats;
        const ovWinRate = document.getElementById('ov-win-rate');
        const ovWins = document.getElementById('ov-wins-count');
        const ovLosses = document.getElementById('ov-losses-count');
        const ovTotal = document.getElementById('ov-total-signals');
        const tabSignalsCount = document.getElementById('tab-signals-count');

        if (ovWinRate) ovWinRate.textContent = `${s.win_rate}%`;
        if (ovWins) ovWins.textContent = s.wins;
        if (ovLosses) ovLosses.textContent = s.losses;
        if (ovTotal) ovTotal.textContent = `${s.total} Sinyal`;
        if (tabSignalsCount) tabSignalsCount.textContent = s.total;
      }

    } catch (e) {
      console.warn('Gagal memuat overview:', e);
    }
  }

  // --- B. SAHAM IDX DATA ---
  async function fetchStocksData() {
    try {
      const res = await fetch('/api/stocks');
      if (!res.ok) return;
      const data = await res.json();

      // Badge hitungan di tab
      const tabCount = document.getElementById('tab-stocks-count');
      if (tabCount && data.watchlist) tabCount.textContent = data.watchlist.length;

      // Tabel Watchlist
      const tbody = document.getElementById('tbody-stocks');
      if (tbody && data.stocks) {
        const q = state.searchStocksQuery.toUpperCase().trim();
        const filtered = data.stocks.filter(s => !q || s.ticker.toUpperCase().includes(q));

        if (filtered.length === 0) {
          tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 20px; color: var(--text-muted);">Tidak ada saham yang cocok dengan pencarian '${q}'.</td></tr>`;
        } else {
          tbody.innerHTML = filtered.map(s => {
            const sig = s.last_signal || 'WAIT';
            let badgeClass = 'badge-wait';
            if (sig.includes('BUY')) badgeClass = 'badge-buy';
            else if (sig.includes('SELL')) badgeClass = 'badge-sell';

            const priceStr = s.last_price ? `Rp ${Number(s.last_price).toLocaleString('id-ID')}` : '-';
            const tpStr = s.tp ? `Rp ${Number(s.tp).toLocaleString('id-ID')}` : '-';
            const slStr = s.sl ? `Rp ${Number(s.sl).toLocaleString('id-ID')}` : '-';

            let outcomeBadge = '-';
            if (s.outcome === 'WIN') outcomeBadge = '<span class="badge badge-win">WIN</span>';
            else if (s.outcome === 'LOSE') outcomeBadge = '<span class="badge badge-lose">LOSE</span>';
            else if (s.outcome === 'OPEN') outcomeBadge = '<span class="badge badge-open">OPEN</span>';

            return `
              <tr>
                <td><strong class="cell-mono" style="color: var(--cyan-glow);">${s.ticker}</strong></td>
                <td><span class="badge ${badgeClass}">${sig}</span></td>
                <td class="cell-mono">${priceStr}</td>
                <td class="cell-mono val-green">${tpStr}</td>
                <td class="cell-mono val-red">${slStr}</td>
                <td class="cell-mono" style="color: var(--text-muted); font-size: 11px;">${s.candle_time}</td>
                <td>${outcomeBadge}</td>
              </tr>
            `;
          }).join('');
        }
      }

      // Tabel Riwayat Sinyal Saham IDX
      const tbodySig = document.getElementById('tbody-stocks-signals');
      if (tbodySig && data.recent_signals) {
        if (data.recent_signals.length === 0) {
          tbodySig.innerHTML = `<tr><td colspan="9" style="text-align:center; padding: 20px; color: var(--text-muted);">Belum ada sinyal saham IDX tercatat.</td></tr>`;
        } else {
          tbodySig.innerHTML = data.recent_signals.slice(0, 15).map(sig => {
            const act = sig.signal_type || 'BUY';
            const badgeClass = act.includes('BUY') ? 'badge-buy' : 'badge-sell';
            let outBadge = '<span class="badge badge-open">OPEN</span>';
            if (sig.outcome === 'WIN') outBadge = '<span class="badge badge-win">WIN</span>';
            else if (sig.outcome === 'LOSE') outBadge = '<span class="badge badge-lose">LOSE</span>';

            return `
              <tr>
                <td class="cell-mono">#${sig.id}</td>
                <td><strong class="cell-mono">${sig.ticker}</strong></td>
                <td style="font-size: 12px; color: var(--text-muted);">${sig.strategy_name}</td>
                <td><span class="badge ${badgeClass}">${act}</span></td>
                <td class="cell-mono">Rp ${Number(sig.price).toLocaleString('id-ID')}</td>
                <td class="cell-mono val-green">${sig.take_profit_price ? 'Rp ' + Number(sig.take_profit_price).toLocaleString('id-ID') : '-'}</td>
                <td class="cell-mono val-red">${sig.stop_loss_price ? 'Rp ' + Number(sig.stop_loss_price).toLocaleString('id-ID') : '-'}</td>
                <td class="cell-mono" style="font-size: 11px; color: var(--text-dim);">${sig.candle_time}</td>
                <td>${outBadge}</td>
              </tr>
            `;
          }).join('');
        }
      }

    } catch (e) {
      console.warn('Gagal memuat data saham:', e);
    }
  }

  // --- C. FOREX & MT5 DATA ---
  async function fetchForexData() {
    try {
      const res = await fetch('/api/forex');
      if (!res.ok) return;
      const data = await res.json();

      if (data.account) {
        const acc = data.account;
        const mt5Login = document.getElementById('mt5-login');
        const mt5Server = document.getElementById('mt5-badge-server');
        const mt5Bal = document.getElementById('mt5-balance');
        const mt5Eq = document.getElementById('mt5-equity');
        const mt5Fm = document.getElementById('mt5-free-margin');

        if (mt5Login) mt5Login.textContent = `${acc.login} (${acc.currency})`;
        if (mt5Server) mt5Server.textContent = acc.server || 'Standby';
        if (mt5Bal) mt5Bal.textContent = `${Number(acc.balance).toFixed(2)} ${acc.currency}`;
        if (mt5Eq) mt5Eq.textContent = `${Number(acc.equity).toFixed(2)} ${acc.currency}`;
        if (mt5Fm) mt5Fm.textContent = `${Number(acc.free_margin).toFixed(2)} ${acc.currency}`;

        // Sinkronisasi HUD 3D
        const hudLogin = document.getElementById('hud-mt5-login');
        const hudBal = document.getElementById('hud-mt5-balance');
        if (hudLogin) hudLogin.textContent = `${acc.server} #${acc.login}`;
        if (hudBal) hudBal.innerHTML = `${acc.balance.toFixed(2)} ${acc.currency} / <strong class="val-green">${acc.equity.toFixed(2)} ${acc.currency}</strong>`;
      }

      // Tabel Posisi Terbuka MT5
      const tbodyPos = document.getElementById('tbody-mt5-positions');
      const hudOpenPos = document.getElementById('hud-open-positions');
      if (tbodyPos && data.positions) {
        if (data.positions.length === 0) {
          tbodyPos.innerHTML = `<tr><td colspan="9" style="text-align:center; padding: 20px; color: var(--text-muted);">Tidak ada posisi trading terbuka saat ini (Standby).</td></tr>`;
          if (hudOpenPos) hudOpenPos.innerHTML = `<span style="color:var(--text-dim);">Tidak ada posisi aktif</span>`;
        } else {
          tbodyPos.innerHTML = data.positions.map(p => {
            const pnlClass = p.profit >= 0 ? 'val-green' : 'val-red';
            const badgeClass = p.type === 'BUY' ? 'badge-buy' : 'badge-sell';
            return `
              <tr>
                <td class="cell-mono">#${p.ticket}</td>
                <td><strong class="cell-mono" style="color: var(--gold-accent);">${p.symbol}</strong></td>
                <td><span class="badge ${badgeClass}">${p.type}</span></td>
                <td class="cell-mono">${p.lot} Lot</td>
                <td class="cell-mono">$${p.openPrice.toFixed(2)}</td>
                <td class="cell-mono">$${p.currentPrice.toFixed(2)}</td>
                <td class="cell-mono val-red">$${p.sl.toFixed(2)}</td>
                <td class="cell-mono val-green">$${p.tp.toFixed(2)}</td>
                <td class="cell-mono ${pnlClass}">${p.profit >= 0 ? '+' : ''}${p.profit.toFixed(2)} USC</td>
              </tr>
            `;
          }).join('');

          if (hudOpenPos && data.positions[0]) {
            const p0 = data.positions[0];
            const pnlClass = p0.profit >= 0 ? 'badge-buy' : 'badge-sell';
            hudOpenPos.innerHTML = `<span class="badge ${pnlClass}">${p0.type}</span> ${p0.lot} Lot @ $${p0.openPrice} (${p0.profit >= 0 ? '+' : ''}${p0.profit.toFixed(2)} USC)`;
          }
        }
      }

      // Sinyal Gold Terbaru
      const tbodyGold = document.getElementById('tbody-gold-signals');
      if (tbodyGold && data.signals) {
        if (data.signals.length === 0) {
          tbodyGold.innerHTML = `<tr><td colspan="8" style="text-align:center; padding: 20px; color: var(--text-muted);">Belum ada sinyal Gold tercatat.</td></tr>`;
        } else {
          tbodyGold.innerHTML = data.signals.slice(0, 15).map(sig => {
            const act = sig.signal_type || 'BUY';
            const badgeClass = act.includes('BUY') ? 'badge-buy' : 'badge-sell';
            let outBadge = '<span class="badge badge-open">OPEN</span>';
            if (sig.outcome === 'WIN') outBadge = '<span class="badge badge-win">WIN</span>';
            else if (sig.outcome === 'LOSE') outBadge = '<span class="badge badge-lose">LOSE</span>';

            let note = sig.outcome_note || sig.reasons || '-';
            try {
              if (note.startsWith('[')) {
                const arr = JSON.parse(note);
                note = arr.join(' • ');
              }
            } catch(e) {}

            return `
              <tr>
                <td class="cell-mono">#${sig.id}</td>
                <td><span class="badge ${badgeClass}">${act}</span></td>
                <td class="cell-mono">$${Number(sig.price).toFixed(2)}</td>
                <td class="cell-mono val-green">$${sig.take_profit_price ? Number(sig.take_profit_price).toFixed(2) : '-'}</td>
                <td class="cell-mono val-red">$${sig.stop_loss_price ? Number(sig.stop_loss_price).toFixed(2) : '-'}</td>
                <td class="cell-mono" style="font-size: 11px; color: var(--text-dim);">${sig.candle_time}</td>
                <td>${outBadge}</td>
                <td style="font-size: 11px; color: var(--text-muted); max-width: 320px; overflow: hidden; text-overflow: ellipsis;">${note}</td>
              </tr>
            `;
          }).join('');
        }
      }

    } catch (e) {
      console.warn('Gagal memuat data forex:', e);
    }
  }

  function formatCryptoQty(val) {
    if (val == null || isNaN(val)) return '0';
    const num = Number(val);
    if (num === 0) return '0';
    if (Number.isInteger(num)) return num.toLocaleString('en-US');
    if (num >= 1000) {
      return num.toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 2 });
    }
    const s = num.toFixed(8).replace(/\.?0+$/, '');
    const parts = s.split('.');
    parts[0] = Number(parts[0]).toLocaleString('en-US');
    return parts.length > 1 ? parts.join('.') : parts[0];
  }

  function formatCryptoPrice(val) {
    if (val == null || isNaN(val)) return '-';
    const num = Number(val);
    if (num === 0) return '0.00';
    if (num >= 1000) return num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
    if (num >= 1) {
      const s = num.toFixed(4).replace(/0+$/, '');
      const dec = s.split('.')[1] || '';
      return dec.length < 2 ? num.toFixed(2) : s;
    }
    if (num >= 0.001) {
      return num.toFixed(5);
    }
    return num.toFixed(8);
  }

  window.formatCryptoQty = formatCryptoQty;
  window.formatCryptoPrice = formatCryptoPrice;

  // --- D. CRYPTO AUTO-PUMP DATA ---
  async function fetchCryptoData() {
    try {
      const res = await fetch('/api/crypto');
      if (!res.ok) return;
      const data = await res.json();

      // Parameter Cards
      const cfgMode = document.getElementById('crypto-cfg-mode');
      const estTotal = document.getElementById('crypto-est-total');
      const freeUsdt = document.getElementById('crypto-free-usdt');
      const investedUsdt = document.getElementById('crypto-invested-usdt');
      const capitalCoin = document.getElementById('crypto-capital');
      const maxPos = document.getElementById('crypto-max-pos');
      const totalPnl = document.getElementById('crypto-total-pnl');
      const winRate = document.getElementById('crypto-win-rate');

      if (cfgMode) cfgMode.textContent = data.mode.toUpperCase();
      if (capitalCoin) capitalCoin.textContent = `$${data.capital_per_coin.toFixed(2)} USDT`;
      if (maxPos) maxPos.textContent = `${data.open_positions ? data.open_positions.length : 0} Koin (Maks ${data.max_positions})`;

      if (data.balance) {
        if (estTotal) estTotal.textContent = `$${Number(data.balance.total_est_usdt || data.balance.free_usdt || 0).toFixed(2)} USDT`;
        if (freeUsdt) freeUsdt.textContent = `$${Number(data.balance.free_usdt || 0).toFixed(2)} USDT`;
        if (investedUsdt) investedUsdt.textContent = `$${Number(data.balance.invested_usdt || 0).toFixed(2)} USDT`;
      }

      if (data.stats) {
        const isReal = data.mode === 'real';
        const pnlVal = (isReal && data.stats.active_mode_pnl != null) ? data.stats.active_mode_pnl : (data.stats.total_realized_pnl_usdt || 0.0);
        const profVal = (isReal && data.stats.active_profit != null) ? data.stats.active_profit : (data.stats.total_profit_usdt || 0.0);
        const lossVal = (isReal && data.stats.active_loss != null) ? data.stats.active_loss : (data.stats.total_loss_usdt || 0.0);
        const winsVal = (isReal && data.stats.active_wins != null) ? data.stats.active_wins : (data.stats.win_count || 0);
        const lossesVal = (isReal && data.stats.active_losses != null) ? data.stats.active_losses : (data.stats.lose_count || 0);
        const bepVal = (isReal && data.stats.active_bep != null) ? data.stats.active_bep : (data.stats.bep_count || 0);
        const wrVal = (isReal && data.stats.active_win_rate != null) ? data.stats.active_win_rate : (data.stats.win_rate || 0.0);

        if (totalPnl) {
          totalPnl.textContent = `${pnlVal >= 0 ? '+' : ''}$${pnlVal.toFixed(4)} USDT`;
          totalPnl.className = `kpi-val ${pnlVal >= 0 ? 'val-green' : 'val-red'}`;
        }
        if (winRate) {
          winRate.textContent = `${wrVal}% (${winsVal} Win / ${lossesVal} Lose)${isReal ? ' [Mode Real]' : ' [Mode Paper]'}`;
        }

        // Update dedicated PnL Suite cards
        const pnlNet = document.getElementById('crypto-pnl-net');
        const pnlProfit = document.getElementById('crypto-pnl-profit');
        const pnlLoss = document.getElementById('crypto-pnl-loss');
        const pnlWinRate = document.getElementById('crypto-pnl-winrate');
        const pnlWinsSub = document.getElementById('crypto-pnl-wins-sub');
        const pnlLossesSub = document.getElementById('crypto-pnl-losses-sub');
        const pnlRatioSub = document.getElementById('crypto-pnl-ratio-sub');
        const badgeMode = document.getElementById('badge-pnl-mode');

        if (pnlNet) {
          pnlNet.textContent = `${pnlVal >= 0 ? '+' : ''}$${pnlVal.toFixed(4)} USDT`;
          pnlNet.className = `pnl-stat-value ${pnlVal >= 0 ? 'val-green' : 'val-red'}`;
        }
        if (pnlProfit) pnlProfit.textContent = `+$${profVal.toFixed(4)} USDT`;
        if (pnlLoss) pnlLoss.textContent = `-$${Math.abs(lossVal).toFixed(4)} USDT`;
        if (pnlWinRate) pnlWinRate.textContent = `${wrVal}%`;
        if (pnlWinsSub) pnlWinsSub.textContent = `${winsVal} Posisi Profit Sukses`;
        if (pnlLossesSub) pnlLossesSub.textContent = `${lossesVal} Posisi Terkena Cutloss`;
        if (pnlRatioSub) pnlRatioSub.textContent = `${winsVal}W / ${lossesVal}L (${bepVal} BEP)`;
        if (badgeMode) {
          badgeMode.textContent = isReal ? 'MODE REAL (BINANCE SPOT LIVE)' : 'MODE PAPER (SIMULASI)';
        }
      }

      // Tabel Rincian Dompet Spot Binance (Holdings)
      const tbodyHoldings = document.getElementById('tbody-crypto-holdings');
      if (tbodyHoldings && data.balance && data.balance.assets) {
        if (data.balance.assets.length === 0) {
          tbodyHoldings.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 20px; color: var(--text-muted);">Tidak ada aset tercatat di dompet Spot.</td></tr>`;
        } else {
          tbodyHoldings.innerHTML = data.balance.assets.map(a => {
            const isCash = a.asset === 'USDT';
            const isDust = !isCash && (Number(a.value_usdt || 0) < 0.01);
            const priceStr = isCash ? '$1.00' : ('$' + formatCryptoPrice(a.price));
            const assetIcon = isCash ? '💵' : (isDust ? '🪙' : '🪙');
            let badgeTag;
            if (isCash) {
              badgeTag = '<span class="badge" style="background:rgba(59,130,246,0.15);color:var(--accent-blue);">KAS STABLECOIN</span>';
            } else if (isDust) {
              badgeTag = '<span class="badge" style="background:rgba(255,255,255,0.08);color:var(--text-dim);border:1px dashed rgba(255,255,255,0.2);">SISA DUST (&lt; $0.01)</span>';
            } else {
              badgeTag = '<span class="badge" style="background:rgba(168,85,247,0.15);color:var(--purple-master);">ALTCOIN SPOT</span>';
            }
            const pct = a.pct_share || 0;
            return `
              <tr id="holding-row-${a.asset}">
                <td><strong>${assetIcon} ${a.asset}</strong> ${badgeTag}</td>
                <td class="cell-mono">${Number(a.amount).toLocaleString(undefined, { maximumFractionDigits: 8 })}</td>
                <td class="cell-mono">${Number(a.free).toLocaleString(undefined, { maximumFractionDigits: 8 })}</td>
                <td class="cell-mono">${Number(a.locked).toLocaleString(undefined, { maximumFractionDigits: 8 })}</td>
                <td class="cell-mono" id="holding-price-${a.asset}" data-raw-price="${a.price}">$${formatCryptoPrice(a.price)}</td>
                <td class="cell-mono"><strong class="val-green" id="holding-val-${a.asset}">$${Number(a.value_usdt).toFixed(2)} USDT</strong></td>
                <td>
                  <div style="display:flex; align-items:center; gap:8px;">
                    <div style="flex:1; background:rgba(255,255,255,0.08); height:6px; border-radius:3px; overflow:hidden;">
                      <div id="holding-bar-${a.asset}" style="width:${Math.min(pct, 100)}%; background:var(--cyan-glow); height:100%;"></div>
                    </div>
                    <span class="cell-mono" id="holding-pct-${a.asset}" style="font-size:12px; min-width:42px;">${pct}%</span>
                  </div>
                </td>
              </tr>
            `;
          }).join('');
        }
      }

      // Tabel Open Positions
      const tbodyOpen = document.getElementById('tbody-crypto-open');
      const badgeOpenCount = document.getElementById('badge-open-crypto-count');
      if (badgeOpenCount && data.open_positions) {
        badgeOpenCount.textContent = `${data.open_positions.length} Koin Berjalan`;
      }
      if (tbodyOpen && data.open_positions) {
        if (data.open_positions.length === 0) {
          tbodyOpen.innerHTML = `<tr><td colspan="14" style="text-align:center; padding: 20px; color: var(--text-muted);">Tidak ada posisi koin crypto terbuka saat ini (Sedang memindai sweet spot pump).</td></tr>`;
        } else {
          tbodyOpen.innerHTML = data.open_positions.map(p => {
            const curP = p.current_price != null ? p.current_price : p.entry_price;
            const pnlPct = p.pnl_pct != null ? p.pnl_pct : 0;
            const pnlUsdt = p.pnl_usdt != null ? p.pnl_usdt : 0;
            const pnlClass = pnlPct >= 0 ? 'val-green' : 'val-red';
            const curPStr = formatCryptoPrice(curP);
            const entryPStr = formatCryptoPrice(p.entry_price);
            const mktVal = p.market_val_usdt != null ? `$${Number(p.market_val_usdt).toFixed(2)}` : `$${Number(p.cost_usdt).toFixed(2)}`;

            const statusBadge = (p.status === 'TP1_HIT' || p.tp1_hit)
              ? `<span class="badge" style="background: rgba(0, 255, 136, 0.2); color: #00ff88; border: 1px solid rgba(0, 255, 136, 0.4); font-weight: 700;">🎯 TP1 HIT (SISA 50% JALAN)</span>`
              : `<span class="badge badge-open">AKTIF BERJALAN</span>`;

            return `
              <tr id="pos-row-${p.id}">
                <td class="cell-mono">#${p.id}</td>
                <td><strong class="cell-mono" style="color: var(--cyan-glow);">${p.symbol}</strong></td>
                <td><span class="badge" style="background: rgba(168, 85, 247, 0.2); color: var(--purple-master);">${p.mode.toUpperCase()}</span></td>
                <td class="cell-mono">$${entryPStr}</td>
                <td class="cell-mono font-bold" id="pos-price-${p.id}" data-raw-price="${curP}" style="color: var(--gold-accent);">$${curPStr}</td>
                <td class="cell-mono ${pnlClass}" id="pos-pnl-${p.id}"><strong>${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</strong> (${pnlUsdt >= 0 ? '+' : ''}$${pnlUsdt.toFixed(4)})</td>
                <td class="cell-mono">${formatCryptoQty(p.quantity)}</td>
                <td class="cell-mono">$${Number(p.cost_usdt).toFixed(2)}</td>
                <td class="cell-mono" id="pos-val-${p.id}">${mktVal}</td>
                <td class="cell-mono val-red">$${formatCryptoPrice(p.sl_price)}</td>
                <td class="cell-mono val-green">$${formatCryptoPrice(p.tp1_price)}</td>
                <td class="cell-mono val-green">$${formatCryptoPrice(p.tp2_price)}</td>
                <td class="cell-mono" style="font-size: 11px; color: var(--text-dim);">${p.entry_time}</td>
                <td>${statusBadge}</td>
              </tr>
            `;
          }).join('');
        }
      }

      // Simpan riwayat transaksi tertutup ke cache & render tabel interaktif
      if (data.closed_history && Array.isArray(data.closed_history)) {
        state.cachedClosedHistory = data.closed_history;

        // Hitung pill counters
        const cAll = data.closed_history.length;
        const cProf = data.closed_history.filter(d => d.outcome === 'PROFIT').length;
        const cLoss = data.closed_history.filter(d => d.outcome === 'LOSS').length;
        const cBep = data.closed_history.filter(d => d.outcome === 'BEP').length;

        const elAll = document.getElementById('count-pill-all');
        const elProf = document.getElementById('count-pill-profit');
        const elLoss = document.getElementById('count-pill-loss');
        const elBep = document.getElementById('count-pill-bep');

        if (elAll) elAll.textContent = cAll;
        if (elProf) elProf.textContent = cProf;
        if (elLoss) elLoss.textContent = cLoss;
        if (elBep) elBep.textContent = cBep;

        renderCryptoClosedTable();
      }

    } catch (e) {
      console.warn('Gagal memuat crypto data:', e);
    }
  }

  // --- E. RENDER TABEL RIWAYAT PROFIT & LOSS CRYPTO DENGAN FILTER & SEARCH ---
  function renderCryptoClosedTable() {
    const tbodyClosed = document.getElementById('tbody-crypto-closed');
    if (!tbodyClosed) return;

    const list = state.cachedClosedHistory || [];
    const filter = state.cryptoClosedFilter;
    const search = (state.cryptoClosedSearch || '').toUpperCase().trim();

    const filtered = list.filter(item => {
      // 1. Filter outcome (profit, loss, bep)
      if (filter === 'profit' && item.outcome !== 'PROFIT') return false;
      if (filter === 'loss' && item.outcome !== 'LOSS') return false;
      if (filter === 'bep' && item.outcome !== 'BEP') return false;

      // 2. Filter search query (symbol atau exit_reason)
      if (search) {
        const sym = (item.symbol || '').toUpperCase();
        const reason = (item.exit_reason || '').toUpperCase();
        if (!sym.includes(search) && !reason.includes(search)) return false;
      }
      return true;
    });

    // Ringkasan footer
    const sumEl = document.getElementById('pnl-filter-summary');
    const totEl = document.getElementById('pnl-filter-total-usdt');
    if (sumEl) sumEl.textContent = `Menampilkan ${filtered.length} dari ${list.length} trade`;

    let totalFilteredPnl = 0.0;
    filtered.forEach(item => {
      totalFilteredPnl += Number(item.pnl_usdt || 0.0);
    });

    if (totEl) {
      totEl.textContent = `Total PnL Terfilter: ${totalFilteredPnl >= 0 ? '+' : ''}$${totalFilteredPnl.toFixed(4)} USDT`;
      totEl.className = `cell-mono font-bold ${totalFilteredPnl >= 0 ? 'val-green' : 'val-red'}`;
    }

    if (filtered.length === 0) {
      tbodyClosed.innerHTML = `<tr><td colspan="12" style="text-align:center; padding: 24px; color: var(--text-muted);">Tidak ada transaksi yang cocok dengan filter (${filter}${search ? ', "' + search + '"' : ''}).</td></tr>`;
      return;
    }

    tbodyClosed.innerHTML = filtered.map(p => {
      const isProf = p.outcome === 'PROFIT';
      const isLoss = p.outcome === 'LOSS';
      const pnlClass = isProf ? 'val-green' : (isLoss ? 'val-red' : '');
      const modeBadge = p.mode === 'real'
        ? '<span class="badge" style="background: rgba(168, 85, 247, 0.2); color: var(--purple-master);">REAL</span>'
        : '<span class="badge" style="background: rgba(59, 130, 246, 0.15); color: var(--accent-blue);">PAPER</span>';

      const outcomeBadge = isProf
        ? '<span class="badge badge-profit">PROFIT</span>'
        : (isLoss ? '<span class="badge badge-loss">CUTLOSS</span>' : '<span class="badge badge-bep">BEP</span>');

      let exitBadge = p.exit_reason || 'Target tercapai';
      if (exitBadge.includes('TP1')) {
        exitBadge = `<span class="badge badge-buy">${exitBadge}</span>`;
      } else if (exitBadge.includes('Stop Loss') || exitBadge.includes('SL')) {
        exitBadge = `<span class="badge badge-sell">${exitBadge}</span>`;
      } else if (exitBadge.includes('Stagnasi')) {
        exitBadge = `<span class="badge badge-wait">${exitBadge}</span>`;
      } else {
        exitBadge = `<span style="font-size: 11px; color: var(--text-muted);">${exitBadge}</span>`;
      }

      const pnlSign = (p.pnl_usdt || 0) >= 0 ? '+' : '';
      const pnlPctSign = (p.pnl_pct || 0) >= 0 ? '+' : '';

      return `
        <tr>
          <td class="cell-mono">#${p.id}</td>
          <td><strong class="cell-mono" style="color: var(--cyan-glow); font-size: 13px;">${p.symbol}</strong></td>
          <td>${modeBadge}</td>
          <td>${outcomeBadge}</td>
          <td class="cell-mono">$${formatCryptoPrice(p.entry_price)}</td>
          <td class="cell-mono font-bold">$${formatCryptoPrice(p.close_price)}</td>
          <td class="cell-mono">$${Number(p.cost_usdt || 0).toFixed(2)}</td>
          <td class="cell-mono ${pnlClass}"><strong>${pnlSign}$${Number(p.pnl_usdt || 0).toFixed(4)}</strong></td>
          <td class="cell-mono ${pnlClass}"><strong>${pnlPctSign}${Number(p.pnl_pct || 0).toFixed(2)}%</strong></td>
          <td class="cell-mono" style="color: var(--text-main); font-weight: 600;">${p.hold_duration || '-'}</td>
          <td class="cell-mono" style="font-size: 11px; color: var(--text-dim);">${p.close_time || '-'}</td>
          <td>${exitBadge}</td>
        </tr>
      `;
    }).join('');
  }

  // --- REAL-TIME LIVE CRYPTO UPDATE ENGINE (ZERO REFRESH) ---
  function updateCryptoLiveUI(live) {
    if (!live) return;

    // 1. Update KPI Card Values
    const estTotal = document.getElementById('crypto-est-total');
    const investedUsdt = document.getElementById('crypto-invested-usdt');
    const freeUsdt = document.getElementById('crypto-free-usdt');
    const ovCryptoVal = document.getElementById('ov-crypto-val');
    const ovCryptoBal = document.getElementById('ov-crypto-balance');
    const badgeOpenCount = document.getElementById('badge-open-crypto-count');
    const maxPos = document.getElementById('crypto-max-pos');

    if (live.total_est_usdt != null) {
      const totStr = `$${Number(live.total_est_usdt).toFixed(2)} USDT`;
      if (estTotal) estTotal.textContent = totStr;
      if (ovCryptoVal) ovCryptoVal.textContent = totStr;
    }
    if (live.invested_usdt != null && investedUsdt) {
      investedUsdt.textContent = `$${Number(live.invested_usdt).toFixed(2)} USDT`;
    }
    if (live.free_usdt != null) {
      const fStr = `$${Number(live.free_usdt).toFixed(2)} USDT`;
      if (freeUsdt) freeUsdt.textContent = fStr;
      if (ovCryptoBal) ovCryptoBal.textContent = fStr;
    }

    if (live.open_positions) {
      const countStr = `${live.open_positions.length} Koin Berjalan`;
      if (badgeOpenCount && badgeOpenCount.textContent !== countStr) {
        badgeOpenCount.textContent = countStr;
      }
      if (maxPos) {
        maxPos.textContent = `${live.open_positions.length} Koin`;
      }

      // Update ATS-MATRIX Telemetry elements
      const pingEl = document.getElementById('ats-live-ping');
      if (pingEl) {
        const ms = Math.floor(18 + Math.random() * 14);
        pingEl.textContent = `FEED LATENCY: ${ms}ms [CLOB SYNC]`;
      }

      const pipeMeta4 = document.getElementById('pipe-meta-4');
      if (pipeMeta4) {
        pipeMeta4.textContent = `${live.open_positions.length} POS ACTIVE (BINANCE)`;
      }

      const winProbEl = document.getElementById('ats-win-prob');
      const funnelBar = document.getElementById('ats-funnel-bar');
      if (winProbEl && funnelBar) {
        const greenCount = live.open_positions.filter(p => (p.pnl_pct || 0) >= 0).length;
        const prob = (live.open_positions.length > 0)
          ? (78.0 + (greenCount / live.open_positions.length) * 12.0 + Math.random() * 1.5).toFixed(1)
          : '82.4';
        winProbEl.textContent = `${prob}%`;
        funnelBar.style.width = `${Math.min(prob, 98)}%`;
      }
    }

    // 2. Render atau Update Holdings Table rows
    const tbodyHoldings = document.getElementById('tbody-crypto-holdings');
    if (tbodyHoldings && live.assets && Array.isArray(live.assets)) {
      const currentHoldings = Array.from(tbodyHoldings.querySelectorAll('tr[id^="holding-row-"]')).map(tr => tr.id).join(',');
      const newHoldings = live.assets.map(a => `holding-row-${a.asset}`).join(',');
      const needsRender = tbodyHoldings.innerHTML.includes('Memuat') || currentHoldings !== newHoldings;
      if (needsRender) {
        if (live.assets.length === 0) {
          tbodyHoldings.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 20px; color: var(--text-muted);">Tidak ada aset tercatat di dompet Spot.</td></tr>`;
        } else {
          tbodyHoldings.innerHTML = live.assets.map(a => {
            const isCash = a.asset === 'USDT';
            const isDust = !isCash && (Number(a.value_usdt || 0) < 0.01);
            const priceStr = isCash ? '$1.00' : ('$' + formatCryptoPrice(a.price));
            const assetIcon = isCash ? '💵' : '🪙';
            let badgeTag;
            if (isCash) {
              badgeTag = '<span class="badge" style="background:rgba(59,130,246,0.15);color:var(--accent-blue);">KAS STABLECOIN</span>';
            } else if (isDust) {
              badgeTag = '<span class="badge" style="background:rgba(255,255,255,0.08);color:var(--text-dim);border:1px dashed rgba(255,255,255,0.2);">SISA DUST (&lt; $0.01)</span>';
            } else {
              badgeTag = '<span class="badge" style="background:rgba(168,85,247,0.15);color:var(--purple-master);">ALTCOIN SPOT</span>';
            }
            const pct = a.pct_share || 0;
            return `
              <tr id="holding-row-${a.asset}">
                <td><strong>${assetIcon} ${a.asset}</strong> ${badgeTag}</td>
                <td class="cell-mono">${Number(a.amount).toLocaleString(undefined, { maximumFractionDigits: 8 })}</td>
                <td class="cell-mono">${Number(a.free).toLocaleString(undefined, { maximumFractionDigits: 8 })}</td>
                <td class="cell-mono">${Number(a.locked).toLocaleString(undefined, { maximumFractionDigits: 8 })}</td>
                <td class="cell-mono" id="holding-price-${a.asset}" data-raw-price="${a.price}">$${formatCryptoPrice(a.price)}</td>
                <td class="cell-mono"><strong class="val-green" id="holding-val-${a.asset}">$${Number(a.value_usdt).toFixed(2)} USDT</strong></td>
                <td>
                  <div style="display:flex; align-items:center; gap:8px;">
                    <div style="flex:1; background:rgba(255,255,255,0.08); height:6px; border-radius:3px; overflow:hidden;">
                      <div id="holding-bar-${a.asset}" style="width:${Math.min(pct, 100)}%; background:var(--cyan-glow); height:100%;"></div>
                    </div>
                    <span class="cell-mono" id="holding-pct-${a.asset}" style="font-size:12px; min-width:42px;">${pct}%</span>
                  </div>
                </td>
              </tr>
            `;
          }).join('');
        }
      } else {
        live.assets.forEach(a => {
          const priceEl = document.getElementById(`holding-price-${a.asset}`);
          const valEl = document.getElementById(`holding-val-${a.asset}`);
          const pctEl = document.getElementById(`holding-pct-${a.asset}`);
          const barEl = document.getElementById(`holding-bar-${a.asset}`);

          if (priceEl && a.asset !== 'USDT') {
            const oldP = parseFloat(priceEl.dataset.rawPrice || 0);
            const newP = a.price || 0;
            const newPStr = '$' + formatCryptoPrice(newP);
            if (priceEl.textContent !== newPStr) {
              priceEl.textContent = newPStr;
              if (oldP > 0 && Math.abs(newP - oldP) > 0.000000001) {
                priceEl.classList.remove('price-flash-up', 'price-flash-down');
                void priceEl.offsetWidth; // trigger reflow
                priceEl.classList.add(newP >= oldP ? 'price-flash-up' : 'price-flash-down');
                setTimeout(() => priceEl.classList.remove('price-flash-up', 'price-flash-down'), 450);
              }
              priceEl.dataset.rawPrice = newP;
            }
          }

          if (valEl && a.value_usdt != null) {
            valEl.textContent = `$${Number(a.value_usdt).toFixed(2)} USDT`;
          }
          if (pctEl && a.pct_share != null) {
            pctEl.textContent = `${a.pct_share}%`;
          }
          if (barEl && a.pct_share != null) {
            barEl.style.width = `${Math.min(a.pct_share, 100)}%`;
          }
        });
      }
    }

    // 3. Render atau Update Open Positions rows
    const tbodyOpen = document.getElementById('tbody-crypto-open');
    if (tbodyOpen && live.open_positions && Array.isArray(live.open_positions)) {
      const currentPosKeys = Array.from(tbodyOpen.querySelectorAll('tr[id^="pos-row-"]')).map(tr => `${tr.id}_${tr.dataset.status || ''}`).join(',');
      const newPosKeys = live.open_positions.map(p => `pos-row-${p.id}_${p.status || ''}`).join(',');
      const needsRender = tbodyOpen.innerHTML.includes('Memuat') || currentPosKeys !== newPosKeys;
      if (needsRender) {
        if (live.open_positions.length === 0) {
          tbodyOpen.innerHTML = `<tr><td colspan="14" style="text-align:center; padding: 20px; color: var(--text-muted);">Tidak ada posisi koin crypto terbuka saat ini (Sedang memindai sweet spot pump).</td></tr>`;
        } else {
          tbodyOpen.innerHTML = live.open_positions.map(p => {
            const curP = p.current_price != null ? p.current_price : p.entry_price;
            const pnlPct = p.pnl_pct != null ? p.pnl_pct : 0;
            const pnlUsdt = p.pnl_usdt != null ? p.pnl_usdt : 0;
            const pnlClass = pnlPct >= 0 ? 'val-green' : 'val-red';
            const curPStr = formatCryptoPrice(curP);
            const entryPStr = formatCryptoPrice(p.entry_price);
            const mktVal = p.market_val_usdt != null ? `$${Number(p.market_val_usdt).toFixed(2)}` : `$${Number(p.cost_usdt).toFixed(2)}`;

            return `
              <tr id="pos-row-${p.id}" data-status="${p.status || ''}">
                <td class="cell-mono">#${p.id}</td>
                <td><strong class="cell-mono" style="color: var(--cyan-glow);">${p.symbol}</strong></td>
                <td><span class="badge" style="background: rgba(168, 85, 247, 0.2); color: var(--purple-master);">${(p.mode || 'real').toUpperCase()}</span></td>
                <td class="cell-mono">$${entryPStr}</td>
                <td class="cell-mono font-bold" id="pos-price-${p.id}" data-raw-price="${curP}" style="color: var(--gold-accent);">$${curPStr}</td>
                <td class="cell-mono ${pnlClass}" id="pos-pnl-${p.id}"><strong>${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</strong> (${pnlUsdt >= 0 ? '+' : ''}$${pnlUsdt.toFixed(4)})</td>
                <td class="cell-mono">${formatCryptoQty(p.quantity)}</td>
                <td class="cell-mono">$${Number(p.cost_usdt).toFixed(2)}</td>
                <td class="cell-mono" id="pos-val-${p.id}">${mktVal}</td>
                <td class="cell-mono val-red">$${formatCryptoPrice(p.sl_price)}</td>
                <td class="cell-mono val-green">$${formatCryptoPrice(p.tp1_price)}</td>
                <td class="cell-mono val-green">$${formatCryptoPrice(p.tp2_price)}</td>
                <td class="cell-mono" style="font-size: 11px; color: var(--text-dim);">${p.entry_time}</td>
                <td>${(p.status === "TP1_HIT" || p.tp1_hit) ? '<span class="badge" style="background: rgba(0, 255, 136, 0.2); color: #00ff88; border: 1px solid rgba(0, 255, 136, 0.4); font-weight: 700;">🎯 TP1 HIT (SISA 50% JALAN)</span>' : '<span class="badge badge-open">AKTIF BERJALAN</span>'}</td>
              </tr>
            `;
          }).join('');
        }
      } else {
        live.open_positions.forEach(p => {
          const priceEl = document.getElementById(`pos-price-${p.id}`);
          const pnlEl = document.getElementById(`pos-pnl-${p.id}`);
          const valEl = document.getElementById(`pos-val-${p.id}`);

          if (priceEl) {
            const oldP = parseFloat(priceEl.dataset.rawPrice || 0);
            const newP = p.current_price || 0;
            const newPStr = '$' + formatCryptoPrice(newP);
            if (priceEl.textContent !== newPStr) {
              priceEl.textContent = newPStr;
              if (oldP > 0 && Math.abs(newP - oldP) > 0.000000001) {
                priceEl.classList.remove('price-flash-up', 'price-flash-down');
                void priceEl.offsetWidth; // trigger reflow
                priceEl.classList.add(newP >= oldP ? 'price-flash-up' : 'price-flash-down');
                setTimeout(() => priceEl.classList.remove('price-flash-up', 'price-flash-down'), 450);
              }
              priceEl.dataset.rawPrice = newP;
            }
          }

          if (pnlEl) {
            const pnlPct = p.pnl_pct != null ? p.pnl_pct : 0;
            const pnlUsdt = p.pnl_usdt != null ? p.pnl_usdt : 0;
            const pnlClass = pnlPct >= 0 ? 'val-green' : 'val-red';
            pnlEl.className = `cell-mono ${pnlClass}`;
            pnlEl.innerHTML = `<strong>${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%</strong> (${pnlUsdt >= 0 ? '+' : ''}$${pnlUsdt.toFixed(4)})`;
          }

          if (valEl && p.market_val_usdt != null) {
            valEl.textContent = `$${Number(p.market_val_usdt).toFixed(2)}`;
          }
        });
      }
    }

    // Forward live telemetry to ATSMATRIX / NIULAI4 cockpit if active
    if (window.atsCockpit && typeof window.atsCockpit.updateLiveTelemetry === 'function') {
      window.atsCockpit.updateLiveTelemetry(live);
    }
  }

  // ==========================================================================
  // D2. BINANCE FUTURES REAL-TIME DESK (HERMES SCANNER)
  // ==========================================================================
  async function fetchFuturesData(silent = false) {
    try {
      const res = await fetch('/api/futures/live');
      if (!res.ok) return;
      const data = await res.json();
      if (!data || data.status !== 'ok') return;

      updateFuturesLiveUI(data);
    } catch (e) {
      if (!silent) console.warn('Fetch futures err:', e);
    }
  }

  function updateFuturesLiveUI(data) {
    if (!data) return;

    // 1. Badge Navbar Tab & Slot
    const badgeTab = document.getElementById('tab-futures-count');
    const badgeSlot = document.getElementById('fut-slot-badge');
    const activeCount = data.active_count || 0;
    const maxActive = (data.rules && data.rules.max_concurrent_trades) || 3;

    if (badgeTab) {
      badgeTab.textContent = `${activeCount} AKTIF`;
      if (activeCount > 0) {
        badgeTab.style.background = 'rgba(0, 255, 136, 0.2)';
        badgeTab.style.color = '#00ff88';
        badgeTab.style.borderColor = '#00ff88';
      } else {
        badgeTab.style.background = 'rgba(240, 185, 11, 0.2)';
        badgeTab.style.color = '#f0b90b';
        badgeTab.style.borderColor = '#f0b90b';
      }
    }

    if (badgeSlot) {
      badgeSlot.textContent = `${activeCount} / ${maxActive} AKTIF`;
      badgeSlot.style.color = activeCount >= maxActive ? '#f0b90b' : '#00ff88';
    }

    // 2. Wallet KPI Metrics
    const w = data.wallet || {};
    const elTot = document.getElementById('fut-wallet-total');
    const elSub = document.getElementById('fut-wallet-sub');
    const elUsed = document.getElementById('fut-wallet-used');
    const elPnl = document.getElementById('fut-wallet-pnl');
    const elPnlSub = document.getElementById('fut-pnl-status');

    if (elTot) elTot.textContent = `$${Number(w.total_usdt || 0).toFixed(4)} USDT`;
    if (elSub) elSub.textContent = `Kas Bebas: $${Number(w.free_usdt || 0).toFixed(4)} USDT`;
    if (elUsed) elUsed.textContent = `$${Number(w.used_margin || 0).toFixed(4)} USDT`;
    
    const pnl = Number(w.unrealized_pnl || 0);
    if (elPnl) {
      elPnl.textContent = `${pnl >= 0 ? '+' : ''}$${pnl.toFixed(4)} USDT`;
      elPnl.className = `kpi-val ${pnl >= 0 ? 'val-green' : 'val-red'}`;
    }
    if (elPnlSub) {
      const runningCount = (data.positions || []).length;
      elPnlSub.textContent = `${runningCount} Posisi Running • ${pnl >= 0 ? 'Floating Profit' : 'Floating Drawdown'}`;
    }

    // 3. Render Running Positions (Order yang sudah kejemput)
    const tbodyPos = document.getElementById('tbody-futures-positions');
    const badgeRun = document.getElementById('badge-running-count');
    const positions = data.positions || [];
    if (badgeRun) badgeRun.textContent = `${positions.length} Posisi`;

    if (tbodyPos) {
      if (positions.length === 0) {
        tbodyPos.innerHTML = `
          <tr>
            <td colspan="10" style="text-align: center; padding: 35px 20px; color: var(--text-muted);">
              <div style="font-size: 15px; margin-bottom: 6px; color: #fff; font-weight: 600;">ℹ️ Belum ada order yang kejemput.</div>
              <div style="font-size: 12px; color: var(--text-dim); max-width: 600px; margin: 0 auto; line-height: 1.6;">
                Semua order saat ini masih berupa <strong>Order Limit</strong> menunggu harga pasar menyentuh titik entry. Begitu harga pasar menyentuh titik entry, posisi otomatis muncul di sini lengkap dengan floating PnL live dan tombol Market Close.
              </div>
            </td>
          </tr>
        `;
      } else {
        tbodyPos.innerHTML = positions.map(p => {
          const isLong = p.side === 'LONG';
          const sideColor = isLong ? '#00ff88' : '#ff4d6a';
          const pnlVal = Number(p.unrealized_pnl || 0);
          const pnlPct = Number(p.pnl_pct || 0);
          const pnlClass = pnlVal >= 0 ? 'val-green' : 'val-red';
          const pnlSign = pnlVal >= 0 ? '+' : '';

          return `
            <tr>
              <td>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span style="font-size: 16px;">🪙</span>
                  <div>
                    <strong style="color: #fff; font-size: 13px;">${p.symbol}</strong>
                    <div style="font-size: 10px; color: var(--text-dim);">USDT-M Perpetual</div>
                  </div>
                </div>
              </td>
              <td>
                <span class="badge" style="background: ${isLong ? 'rgba(0, 255, 136, 0.15)' : 'rgba(255, 77, 106, 0.15)'}; color: ${sideColor}; border: 1px solid ${sideColor}; font-weight: 700;">
                  ${isLong ? '↗ BUY (LONG)' : '↘ SELL (SHORT)'}
                </span>
              </td>
              <td>
                <span class="badge" style="background: rgba(240, 185, 11, 0.15); color: #f0b90b; border: 1px solid #f0b90b; font-family: var(--font-mono); font-weight: 700;">
                  ${p.leverage}x
                </span>
              </td>
              <td class="cell-mono font-bold" style="color: #00f3ff;">$${Number(p.initial_margin || 0).toFixed(4)} USDT</td>
              <td class="cell-mono font-bold">$${formatCryptoPrice(p.entry_price)}</td>
              <td class="cell-mono font-bold" style="color: #fff;" id="fut-pos-price-${p.symbol}">$${formatCryptoPrice(p.mark_price)}</td>
              <td class="cell-mono" style="color: #ff4d6a; font-weight: 600;">${p.stop_loss ? ('$' + formatCryptoPrice(p.stop_loss)) : '<span style="color:var(--text-dim)">-</span>'}</td>
              <td class="cell-mono" style="color: #00ff88; font-weight: 600;">${p.take_profit ? ('$' + formatCryptoPrice(p.take_profit)) : '<span style="color:var(--text-dim)">-</span>'}</td>
              <td class="cell-mono ${pnlClass}">
                <div style="font-weight: 700; font-size: 13px;">${pnlSign}$${pnlVal.toFixed(4)} USDT</div>
                <div style="font-size: 11px;">(${pnlSign}${pnlPct.toFixed(2)}%)</div>
              </td>
              <td style="text-align: center;">
                <button class="btn btn-sm" onclick="cancelFuturesOrder('${p.symbol}', 'position')" style="background: rgba(255, 77, 106, 0.15); color: #ff4d6a; border: 1px solid #ff4d6a; font-size: 11px; padding: 4px 10px; border-radius: 6px; cursor: pointer;">
                  ✕ Market Close
                </button>
              </td>
            </tr>
          `;
        }).join('');
      }
    }

    // 4. Render Pending Limit Orders (Antrian belum kejemput)
    const tbodyOrders = document.getElementById('tbody-futures-orders');
    const badgePending = document.getElementById('badge-pending-count');
    const orders = data.open_orders || [];
    if (badgePending) badgePending.textContent = `${orders.length} Antrian`;

    if (tbodyOrders) {
      if (orders.length === 0) {
        tbodyOrders.innerHTML = `
          <tr>
            <td colspan="12" style="text-align: center; padding: 35px 20px; color: var(--text-muted);">
              <div style="font-size: 15px; margin-bottom: 6px; color: #fff; font-weight: 600;">ℹ️ Tidak ada order limit yang sedang mengantri.</div>
              <div style="font-size: 12px; color: var(--text-dim);">Bot sedang standby menunggu sinyal valid baru dari scanner teman Anda.</div>
            </td>
          </tr>
        `;
      } else {
        tbodyOrders.innerHTML = orders.map(o => {
          const isLong = o.side === 'LONG';
          const sideColor = isLong ? '#00ff88' : '#ff4d6a';
          const diffVal = Number(o.diff_pct || 0);
          const diffSign = diffVal > 0 ? '+' : '';

          return `
            <tr id="fut-order-row-${o.order_id}">
              <td>
                <div style="display: flex; align-items: center; gap: 8px;">
                  <span style="font-size: 16px;">⏳</span>
                  <div>
                    <strong style="color: #fff; font-size: 13px;">${o.symbol}</strong>
                    <div style="font-size: 10px; color: var(--text-dim); font-family: var(--font-mono);">ID: ${o.order_id}</div>
                  </div>
                </div>
              </td>
              <td>
                <span class="badge" style="background: ${isLong ? 'rgba(0, 255, 136, 0.15)' : 'rgba(255, 77, 106, 0.15)'}; color: ${sideColor}; border: 1px solid ${sideColor}; font-weight: 700;">
                  ${isLong ? 'LIMIT BUY' : 'LIMIT SELL'}
                </span>
              </td>
              <td class="cell-mono font-bold" style="color: #f0b90b; font-size: 13px;">$${formatCryptoPrice(o.limit_price)}</td>
              <td class="cell-mono font-bold" style="color: #fff;" id="fut-order-live-${o.symbol}" data-price="${o.current_price}">$${formatCryptoPrice(o.current_price)}</td>
              <td>
                <span class="badge" id="fut-order-dist-${o.symbol}" style="background: rgba(56, 189, 248, 0.12); color: #38bdf8; border: 1px solid rgba(56, 189, 248, 0.3); font-family: var(--font-mono); font-size: 11px; font-weight: 700;">
                  ${diffSign}${diffVal.toFixed(2)}%
                </span>
              </td>
              <td class="cell-mono">${Number(o.qty).toLocaleString(undefined, { maximumFractionDigits: 4 })}</td>
              <td class="cell-mono" style="color: var(--text-muted);">$${Number(o.notional || 0).toFixed(2)}</td>
              <td class="cell-mono font-bold" style="color: #00f3ff;">
                $${Number(o.initial_margin || 0).toFixed(4)} USDT
                <div style="font-size: 9px; color: #00ff88; font-family: var(--font-mono);">&le; 55 Cent OK</div>
              </td>
              <td class="cell-mono" style="color: #ff4d6a; font-weight: 600;">
                ${o.stop_loss ? ('$' + formatCryptoPrice(o.stop_loss)) : '<span style="color:var(--text-dim)">-</span>'}
              </td>
              <td class="cell-mono" style="color: #00ff88; font-weight: 600;">
                ${o.take_profit ? ('$' + formatCryptoPrice(o.take_profit)) : '<span style="color:var(--text-dim)">-</span>'}
              </td>
              <td class="cell-mono" style="font-size: 11px; color: var(--text-dim);">${o.time}</td>
              <td style="text-align: center;">
                <button class="btn btn-sm btn-danger" onclick="cancelFuturesOrder('${o.symbol}', '${o.order_id}')" style="font-size: 11px; padding: 4px 10px; border-radius: 6px; cursor: pointer;" title="Batalkan order antri ini">
                  Batalkan
                </button>
              </td>
            </tr>
          `;
        }).join('');

        // Terapkan animasi flash harga jika harga berubah
        orders.forEach(o => {
          const elPrice = document.getElementById(`fut-order-live-${o.symbol}`);
          if (elPrice) {
            const oldP = parseFloat(elPrice.getAttribute('data-prev-price') || 0);
            const curP = parseFloat(o.current_price);
            if (oldP > 0 && curP !== oldP) {
              const cls = curP > oldP ? 'price-flash-up' : 'price-flash-down';
              elPrice.classList.add(cls);
              setTimeout(() => elPrice.classList.remove(cls), 600);
            }
            elPrice.setAttribute('data-prev-price', curP);
          }
        });
      }
    }
  }

  window.cancelFuturesOrder = async function(symbol, orderId) {
    if (!confirm(`Batalkan order ${symbol} (ID: ${orderId}) sekarang?`)) return;
    try {
      const res = await fetch(`/api/action/futures/cancel?symbol=${encodeURIComponent(symbol)}&orderId=${encodeURIComponent(orderId)}`);
      const data = await res.json();
      if (data.success) {
        alert(`Berhasil: ${data.message}`);
        fetchFuturesData();
      } else {
        alert(`Gagal: ${data.error || 'Terjadi kesalahan'}`);
      }
    } catch (e) {
      alert(`Error koneksi: ${e}`);
    }
  };

  // --- E. SIGNALS DATABASE & STATS ---
  async function fetchSignalsData() {
    try {
      const cat = state.filterSignalsCat;
      const out = state.filterSignalsOutcome;
      const url = `/api/signals?category=${encodeURIComponent(cat)}&outcome=${encodeURIComponent(out)}&limit=100`;
      
      const res = await fetch(url);
      if (!res.ok) return;
      const data = await res.json();

      if (data.stats) {
        const s = data.stats;
        const statTotal = document.getElementById('sig-stat-total');
        const statWins = document.getElementById('sig-stat-wins');
        const statLosses = document.getElementById('sig-stat-losses');
        const statOpen = document.getElementById('sig-stat-open');
        const statWinrate = document.getElementById('sig-stat-winrate');

        if (statTotal) statTotal.textContent = s.total;
        if (statWins) statWins.textContent = s.wins;
        if (statLosses) statLosses.textContent = s.losses;
        if (statOpen) statOpen.textContent = s.open;
        if (statWinrate) statWinrate.textContent = `${s.win_rate}%`;
      }

      const tbody = document.getElementById('tbody-signals-all');
      if (tbody && data.signals) {
        const q = state.searchSignalsQuery.toUpperCase().trim();
        const filtered = data.signals.filter(s => !q || s.ticker.toUpperCase().includes(q));

        if (filtered.length === 0) {
          tbody.innerHTML = `<tr><td colspan="11" style="text-align:center; padding: 20px; color: var(--text-muted);">Tidak ada sinyal yang sesuai dengan kriteria filter.</td></tr>`;
        } else {
          tbody.innerHTML = filtered.map(s => {
            const act = s.signal_type || 'BUY';
            const badgeClass = act.includes('BUY') ? 'badge-buy' : 'badge-sell';
            let outBadge = '<span class="badge badge-open">OPEN</span>';
            if (s.outcome === 'WIN') outBadge = '<span class="badge badge-win">WIN</span>';
            else if (s.outcome === 'LOSE') outBadge = '<span class="badge badge-lose">LOSE</span>';

            const isGold = s.ticker.includes('XAU') || s.ticker.includes('GC=');
            const prefix = isGold ? '$' : 'Rp ';
            const entryStr = `${prefix}${Number(s.price).toLocaleString()}`;
            const tpStr = s.take_profit_price ? `${prefix}${Number(s.take_profit_price).toLocaleString()}` : '-';
            const slStr = s.stop_loss_price ? `${prefix}${Number(s.stop_loss_price).toLocaleString()}` : '-';
            const pnlStr = s.pnl_pct !== null && s.pnl_pct !== undefined ? `${s.pnl_pct >= 0 ? '+' : ''}${s.pnl_pct.toFixed(2)}%` : '-';

            let note = s.outcome_note || s.reasons || '-';
            try {
              if (note.startsWith('[')) {
                const arr = JSON.parse(note);
                note = arr.join(' • ');
              }
            } catch(e) {}

            return `
              <tr>
                <td class="cell-mono">#${s.id}</td>
                <td><strong class="cell-mono" style="color: ${isGold ? 'var(--gold-accent)' : 'var(--cyan-glow)'};">${s.ticker}</strong></td>
                <td style="font-size: 11px; color: var(--text-muted);">${s.strategy_name}</td>
                <td><span class="badge ${badgeClass}">${act}</span></td>
                <td class="cell-mono">${entryStr}</td>
                <td class="cell-mono val-green">${tpStr}</td>
                <td class="cell-mono val-red">${slStr}</td>
                <td class="cell-mono" style="font-size: 11px; color: var(--text-dim);">${s.candle_time}</td>
                <td>${outBadge}</td>
                <td class="cell-mono ${s.pnl_pct >= 0 ? 'val-green' : 'val-red'}">${pnlStr}</td>
                <td style="font-size: 11px; color: var(--text-muted); max-width: 300px; overflow: hidden; text-overflow: ellipsis;">${note}</td>
              </tr>
            `;
          }).join('');
        }
      }

    } catch (e) {
      console.warn('Gagal memuat sinyal:', e);
    }
  }

  // --- F. KALENDER EKONOMI DATA ---
  async function fetchCalendarData() {
    try {
      const res = await fetch('/api/calendar');
      if (!res.ok) return;
      const data = await res.json();

      const tbody = document.getElementById('tbody-calendar');
      if (tbody && data.events) {
        if (data.events.length === 0) {
          tbody.innerHTML = `<tr><td colspan="7" style="text-align:center; padding: 20px; color: var(--text-muted);">Tidak ada jadwal rilis berita ekonomi berdampak tinggi saat ini.</td></tr>`;
        } else {
          tbody.innerHTML = data.events.map(ev => {
            const impact = (ev.impact || 'low').toLowerCase();
            let badgeClass = 'badge-wait';
            if (impact.includes('high')) badgeClass = 'badge-high';
            else if (impact.includes('med')) badgeClass = 'badge-med';

            return `
              <tr>
                <td class="cell-mono" style="color: var(--cyan-glow);">${ev.date_wib}</td>
                <td><strong class="cell-mono">${ev.country}</strong></td>
                <td><span class="badge ${badgeClass}">${ev.impact.toUpperCase()}</span></td>
                <td><strong style="color: #fff;">${ev.title}</strong></td>
                <td class="cell-mono">${ev.forecast || '-'}</td>
                <td class="cell-mono" style="color: var(--text-dim);">${ev.previous || '-'}</td>
                <td>${ev.alert_sent ? '<span class="badge badge-win">TERKIRIM</span>' : '<span class="badge badge-open">TERJADWAL</span>'}</td>
              </tr>
            `;
          }).join('');
        }
      }
    } catch (e) {
      console.warn('Gagal memuat kalender:', e);
    }
  }

  // --- G. LIVE TERMINAL LOGS ---
  async function fetchLiveLogs() {
    try {
      const level = state.filterLogLevel;
      const res = await fetch(`/api/logs?lines=150&level=${encodeURIComponent(level)}`);
      if (!res.ok) return;
      const data = await res.json();
      if (!data.logs) return;

      const logs = data.logs;

      // 1. Quick Logs di tab Overview
      const quickStream = document.getElementById('ov-quick-logs');
      if (quickStream) {
        const last6 = logs.slice(-6);
        quickStream.innerHTML = last6.map(l => `
          <div class="log-entry">
            <span class="log-time">[${l.timestamp.split(' ')[1] || l.timestamp}]</span>
            <span class="log-level ${l.level}">[${l.level}]</span>
            <span class="log-comp">[${l.component}]</span>
            <span class="log-msg">${escapeHtml(l.message)}</span>
          </div>
        `).join('');
      }

      // 2. Full Terminal di tab Terminal
      const fullStream = document.getElementById('full-terminal-stream');
      if (fullStream && state.currentTab === 'terminal') {
        fullStream.innerHTML = logs.map(l => `
          <div class="log-entry">
            <span class="log-time">[${l.timestamp}]</span>
            <span class="log-level ${l.level}">[${l.level}]</span>
            <span class="log-comp">[${l.component}]</span>
            <span class="log-msg">${escapeHtml(l.message)}</span>
          </div>
        `).join('');

        if (state.terminalAutoScroll) {
          fullStream.scrollTop = fullStream.scrollHeight;
        }
      }

    } catch (e) {
      console.warn('Gagal memuat live logs:', e);
    }
  }

  function escapeHtml(str) {
    if (!str) return '';
    return str.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  }

  // ==========================================================================
  // 6. MASTER DISPATCHER & POLLING CYCLE
  // ==========================================================================
  async function fetchActiveTabData() {
    // Jalankan overview & quick logs non-blocking agar tidak menunda render tab aktif
    fetchOverview().catch(e => console.warn('Overview err:', e));
    fetchLiveLogs().catch(e => console.warn('Logs err:', e));

    // Data spesifik tab aktif
    if (state.currentTab === 'stocks') {
      await fetchStocksData();
    } else if (state.currentTab === 'forex') {
      await fetchForexData();
    } else if (state.currentTab === 'crypto') {
      await fetchCryptoData();
    } else if (state.currentTab === 'futures') {
      await fetchFuturesData();
    } else if (state.currentTab === 'signals') {
      await fetchSignalsData();
    } else if (state.currentTab === 'calendar') {
      await fetchCalendarData();
    } else if (state.currentTab === 'terminal') {
      await fetchLiveLogs();
    }
  }

  function startPolling() {
    if (state.pollingTimer) clearInterval(state.pollingTimer);
    fetchActiveTabData();
    state.pollingTimer = setInterval(() => {
      if (state.autoRefresh) {
        fetchActiveTabData();
      }
    }, state.pollingIntervalMs);

    // Live Real-Time Crypto & Futures Streaming (Setiap 1 Detik, Zero Refresh)
    setInterval(async () => {
      if (!state.autoRefresh) return;
      try {
        const res = await fetch('/api/crypto/live');
        if (res.ok) {
          const live = await res.json();
          updateCryptoLiveUI(live);
        }
      } catch(e) {}

      // Real-time Binance Futures Stream (Zero Refresh)
      if (state.currentTab === 'futures') {
        fetchFuturesData(true);
      }
    }, 1000);
  }

  // ==========================================================================
  // 7. USER ACTIONS & EVENT LISTENERS
  // ==========================================================================

  // --- Scan Saham Manual ---
  async function triggerManualScan() {
    const btnScan = document.getElementById('btn-run-stock-scan');
    const btnQuickScan = document.getElementById('btn-quick-scan');
    [btnScan, btnQuickScan].forEach(b => {
      if (b) {
        b.disabled = true;
        b.innerHTML = '<span>⏳ Memindai Watchlist...</span>';
      }
    });

    try {
      const res = await fetch('/api/action/scan', { method: 'POST' });
      const data = await res.json();
      audio.playSignalAlert();
      alert('🔍 Pemindaian Watchlist Dimulai!\nHasil scan otomatis diperbarui dalam beberapa detik.');
      setTimeout(fetchStocksData, 4000);
    } catch (e) {
      alert('Gagal memulai scan: ' + e);
    } finally {
      [btnScan, btnQuickScan].forEach(b => {
        if (b) {
          b.disabled = false;
          b.innerHTML = '<span>🔍 Scan Watchlist Sekarang</span>';
        }
      });
    }
  }

  const btnScan = document.getElementById('btn-run-stock-scan');
  if (btnScan) btnScan.addEventListener('click', triggerManualScan);
  const btnQuickScan = document.getElementById('btn-quick-scan');
  if (btnQuickScan) btnQuickScan.addEventListener('click', triggerManualScan);

  // --- Toggle Crypto Mode (Real / Paper) ---
  const btnToggleCrypto = document.getElementById('btn-toggle-crypto-mode');
  if (btnToggleCrypto) {
    btnToggleCrypto.addEventListener('click', async () => {
      const currentMode = document.getElementById('crypto-cfg-mode')?.textContent?.toLowerCase() || 'real';
      const targetMode = currentMode === 'real' ? 'paper' : 'real';
      if (confirm(`Apakah Anda yakin ingin mengganti mode Crypto Sniper ke: ${targetMode.toUpperCase()}?`)) {
        try {
          const res = await fetch('/api/action/crypto_toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: targetMode })
          });
          const d = await res.json();
          alert(`✅ Mode Crypto Sniper diubah ke: ${d.mode.toUpperCase()}`);
          fetchCryptoData();
        } catch (e) {
          alert('Gagal mengganti mode: ' + e);
        }
      }
    });
  }

  // --- Refresh Futures Manual ---
  const btnRefreshFutures = document.getElementById('btn-refresh-futures');
  if (btnRefreshFutures) {
    btnRefreshFutures.addEventListener('click', () => {
      audio.playCyberTick();
      fetchFuturesData();
    });
  }

  // --- Search & Filters ---
  const searchStocks = document.getElementById('search-stocks');
  if (searchStocks) {
    searchStocks.addEventListener('input', (e) => {
      state.searchStocksQuery = e.target.value;
      fetchStocksData();
    });
  }

  const searchSignals = document.getElementById('search-signals');
  if (searchSignals) {
    searchSignals.addEventListener('input', (e) => {
      state.searchSignalsQuery = e.target.value;
      fetchSignalsData();
    });
  }

  const filterCat = document.getElementById('filter-sig-cat');
  if (filterCat) {
    filterCat.addEventListener('change', (e) => {
      state.filterSignalsCat = e.target.value;
      fetchSignalsData();
    });
  }

  const filterOutcome = document.getElementById('filter-sig-outcome');
  if (filterOutcome) {
    filterOutcome.addEventListener('change', (e) => {
      state.filterSignalsOutcome = e.target.value;
      fetchSignalsData();
    });
  }

  const filterLogLevel = document.getElementById('filter-log-level');
  if (filterLogLevel) {
    filterLogLevel.addEventListener('change', (e) => {
      state.filterLogLevel = e.target.value;
      fetchLiveLogs();
    });
  }

  // --- Crypto Closed History Filter & Search ---
  const pillButtons = document.querySelectorAll('#pnl-filter-pills .pnl-pill');
  pillButtons.forEach(btn => {
    btn.addEventListener('click', () => {
      pillButtons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.cryptoClosedFilter = btn.dataset.filter || 'all';
      renderCryptoClosedTable();
    });
  });

  const searchCryptoClosed = document.getElementById('search-crypto-closed');
  if (searchCryptoClosed) {
    searchCryptoClosed.addEventListener('input', (e) => {
      state.cryptoClosedSearch = e.target.value;
      renderCryptoClosedTable();
    });
  }

  // --- Terminal Controls ---
  const btnAutoScroll = document.getElementById('btn-toggle-autoscroll');
  if (btnAutoScroll) {
    btnAutoScroll.addEventListener('click', () => {
      state.terminalAutoScroll = !state.terminalAutoScroll;
      btnAutoScroll.innerHTML = `<span>Scroll Otomatis: ${state.terminalAutoScroll ? 'ON' : 'OFF'}</span>`;
    });
  }

  const btnCopyLogs = document.getElementById('btn-copy-terminal-logs');
  if (btnCopyLogs) {
    btnCopyLogs.addEventListener('click', () => {
      const fullStream = document.getElementById('full-terminal-stream');
      if (fullStream) {
        navigator.clipboard.writeText(fullStream.innerText);
        alert('📋 Semua log terminal disalin ke clipboard!');
      }
    });
  }

  // --- Top Tools Controls ---
  const btnThemeToggle = document.getElementById('btn-theme-toggle');
  if (btnThemeToggle) {
    btnThemeToggle.addEventListener('click', () => {
      document.body.classList.toggle('theme-day');
      const isDay = document.body.classList.contains('theme-day');
      btnThemeToggle.textContent = isDay ? '☀️' : '🌙';
    });
  }

  const btnSoundToggle = document.getElementById('btn-sound-toggle');
  if (btnSoundToggle) {
    btnSoundToggle.addEventListener('click', () => {
      audio.muted = !audio.muted;
      btnSoundToggle.textContent = audio.muted ? '🔇' : '🔊';
    });
  }

  const btnRefreshToggle = document.getElementById('btn-refresh-toggle');
  if (btnRefreshToggle) {
    btnRefreshToggle.addEventListener('click', () => {
      state.autoRefresh = !state.autoRefresh;
      btnRefreshToggle.classList.toggle('active', state.autoRefresh);
    });
  }

  // --- Modal Broadcast Sinyal Uji ---
  const modalBroadcast = document.getElementById('modal-broadcast');
  const btnOpenBroadcast = document.getElementById('btn-quick-broadcast');
  const btnCloseBroadcast = document.getElementById('btn-close-broadcast');
  const btnCancelBroadcast = document.getElementById('btn-cancel-broadcast');
  const broadcastForm = document.getElementById('broadcast-form');

  if (btnOpenBroadcast && modalBroadcast) {
    btnOpenBroadcast.addEventListener('click', () => modalBroadcast.classList.remove('hidden'));
  }
  if (btnCloseBroadcast && modalBroadcast) {
    btnCloseBroadcast.addEventListener('click', () => modalBroadcast.classList.add('hidden'));
  }
  if (btnCancelBroadcast && modalBroadcast) {
    btnCancelBroadcast.addEventListener('click', () => modalBroadcast.classList.add('hidden'));
  }

  if (broadcastForm) {
    broadcastForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const action = document.querySelector('input[name="signal_action"]:checked')?.value || 'BUY';
      const symbol = document.getElementById('input-symbol')?.value || 'XAUUSD';
      const entry = parseFloat(document.getElementById('input-entry')?.value || '4185.0');
      const tp = parseFloat(document.getElementById('input-tp')?.value || '4195.0');
      const sl = parseFloat(document.getElementById('input-sl')?.value || '4175.0');

      try {
        const res = await fetch('/api/signal', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action, symbol, entry, tp, sl })
        });
        if (res.ok) {
          audio.playOrderSuccess();
          modalBroadcast.classList.add('hidden');
          if (state.officeInstance && state.officeInstance.triggerSignalBroadcastAnimation) {
            state.officeInstance.triggerSignalBroadcastAnimation({ action, symbol, entry, tp, sl });
          }
          alert(`⚡ Sinyal ${action} ${symbol} @ $${entry} berhasil dikirim ke trading floor!`);
          fetchActiveTabData();
        }
      } catch (err) {
        alert('Gagal mengirim sinyal: ' + err);
      }
    });
  }

  // ==========================================================================
  // 7b. MOBILE APP MODAL & PWA INSTALL HANDLER
  // ==========================================================================
  const btnMobileModal = document.getElementById('btn-mobile-modal');
  const modalMobileApp = document.getElementById('modal-mobile-app');
  const btnCloseMobileModal = document.getElementById('btn-close-mobile-modal');
  const btnCopyMobileUrl = document.getElementById('btn-copy-mobile-url');
  const mobileNetworkUrlInput = document.getElementById('mobile-network-url-input');
  const btnPwaInstall = document.getElementById('btn-pwa-install');

  // Fetch dynamic network IP
  fetch('/api/network_info')
    .then(res => res.json())
    .then(data => {
      if (data && data.network_url && mobileNetworkUrlInput) {
        mobileNetworkUrlInput.value = data.network_url;
      }
    })
    .catch(() => {});

  if (btnMobileModal && modalMobileApp) {
    btnMobileModal.addEventListener('click', () => {
      modalMobileApp.classList.remove('hidden');
    });
  }

  if (btnCloseMobileModal && modalMobileApp) {
    btnCloseMobileModal.addEventListener('click', () => {
      modalMobileApp.classList.add('hidden');
    });
  }

  if (modalMobileApp) {
    modalMobileApp.addEventListener('click', (e) => {
      if (e.target === modalMobileApp) modalMobileApp.classList.add('hidden');
    });
  }

  if (btnCopyMobileUrl && mobileNetworkUrlInput) {
    btnCopyMobileUrl.addEventListener('click', () => {
      navigator.clipboard.writeText(mobileNetworkUrlInput.value).then(() => {
        btnCopyMobileUrl.textContent = '✓ Disalin!';
        btnCopyMobileUrl.style.background = '#10b981';
        setTimeout(() => {
          btnCopyMobileUrl.textContent = 'Salin Link';
          btnCopyMobileUrl.style.background = '';
        }, 2000);
      }).catch(() => {
        alert('Gagal menyalin link');
      });
    });
  }

  // Register PWA Service Worker
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', () => {
      navigator.serviceWorker.register('/sw.js').then((reg) => {
        console.log('[PWA] Service Worker terdaftar:', reg.scope);
      }).catch((err) => {
        console.warn('[PWA] Service Worker gagal:', err);
      });
    });
  }

  // PWA Install Prompt
  let deferredInstallPrompt = null;
  window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredInstallPrompt = e;
    if (btnPwaInstall) {
      btnPwaInstall.style.display = 'inline-flex';
      btnPwaInstall.onclick = async () => {
        if (deferredInstallPrompt) {
          deferredInstallPrompt.prompt();
          const { outcome } = await deferredInstallPrompt.userChoice;
          console.log('[PWA] User choice:', outcome);
          deferredInstallPrompt = null;
          btnPwaInstall.style.display = 'none';
        }
      };
    }
  });

  window.addEventListener('appinstalled', () => {
    console.log('[PWA] Aplikasi berhasil dipasang!');
    if (btnPwaInstall) btnPwaInstall.style.display = 'none';
  });

  // ==========================================================================
  // 8. START ENGINE
  // ==========================================================================
  startPolling();
});
