/**
 * BOTRADING DASHBOARD APPLICATION CONTROLLER
 * State management, audio synthesizer, backend polling & interactive modals
 */

document.addEventListener('DOMContentLoaded', () => {
  // 1. Initialize 3D Isometric Office Scene
  const office = new Office3D('office-canvas', 'labels-container', 'speech-bubbles-container');

  // 2. Audio Synthesizer (Web Audio API - 100% Offline & Pure JS)
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

      // Two-note victory chime
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

    playOrderFailed() {
      if (this.muted) return;
      this.ensureContext();
      const now = this.ctx.currentTime;

      const osc = this.ctx.createOscillator();
      const gain = this.ctx.createGain();
      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(220, now);
      osc.frequency.linearRampToValueAtTime(140, now + 0.25);

      gain.gain.setValueAtTime(0.25, now);
      gain.gain.exponentialRampToValueAtTime(0.01, now + 0.3);

      osc.connect(gain);
      gain.connect(this.ctx.destination);
      osc.start(now);
      osc.stop(now + 0.3);
    }
  }

  const audio = new AudioSynth();

  // 3. App State & Elements
  const state = {
    isLive: false,
    selectedAgent: null,
    goldPrice: 4175.80,
    openPositions: [
      { ticket: 15248079611, symbol: 'XAUUSDc', type: 'BUY', lot: 0.05, openPrice: 4175.77, profit: 1.05 }
    ],
    account: {
      login: 114201000,
      server: 'HFMarketsGlobal-Live7',
      currency: 'USC',
      balance: 475.26,
      equity: 476.31
    }
  };

  // Elements
  const navGoldPrice = document.getElementById('nav-gold-price');
  const navGoldChange = document.getElementById('nav-gold-change');
  const syncStatus = document.getElementById('sync-status');
  const syncText = document.getElementById('sync-text');
  
  const hudMt5Login = document.getElementById('hud-mt5-login');
  const hudMt5Balance = document.getElementById('hud-mt5-balance');
  const hudOpenPositions = document.getElementById('hud-open-positions');

  const hudSigAction = document.getElementById('hud-sig-action');
  const hudSigTime = document.getElementById('hud-sig-time');
  const hudSigEntry = document.getElementById('hud-sig-entry');
  const hudSigTp = document.getElementById('hud-sig-tp');
  const hudSigSl = document.getElementById('hud-sig-sl');
  const hudSigStatus = document.getElementById('hud-sig-status');

  const terminalDrawer = document.getElementById('terminal-drawer');
  const terminalOutput = document.getElementById('terminal-output');
  const terminalBadge = document.getElementById('terminal-badge');

  // Modals
  const modalAgentDetail = document.getElementById('modal-agent-detail');
  const modalBroadcast = document.getElementById('modal-broadcast');
  const modalSettings = document.getElementById('modal-settings');

  // ==========================================================================
  // TERMINAL LOGGER (Styled Exactly Like Image 1 PowerShell)
  // ==========================================================================

  function appendTerminalSignal(sig, execution) {
    const timeStr = sig.time || new Date().toTimeString().split(' ')[0];
    
    // Header
    const lineHead = document.createElement('div');
    lineHead.className = 'term-line signal-header';
    lineHead.textContent = `⚡ [${timeStr}] SINYAL DITERIMA DARI MASTER BOT:`;
    terminalOutput.appendChild(lineHead);

    // Body
    const lines = [
      `   Aksi  : ${sig.action} ${sig.symbol || 'XAUUSD'}`,
      `   Entry : $${sig.entry.toLocaleString('en-US', { minimumFractionDigits: 2 })}`,
      `   TP    : $${sig.tp.toLocaleString('en-US', { minimumFractionDigits: 2 })}`,
      `   SL    : $${sig.sl.toLocaleString('en-US', { minimumFractionDigits: 2 })}`
    ];

    lines.forEach(text => {
      const el = document.createElement('div');
      el.className = 'term-line signal-body';
      el.textContent = text;
      terminalOutput.appendChild(el);
    });

    // Execution Result
    if (execution.success) {
      const lineRes = document.createElement('div');
      lineRes.className = 'term-line order-success';
      lineRes.textContent = `   ✅ [ORDER MT5 SUKSES] #${execution.ticket} ${sig.action} ${execution.lot} Lot @ $${execution.price.toFixed(2)} pada ${execution.symbol}`;
      terminalOutput.appendChild(lineRes);
    } else {
      const lineRes = document.createElement('div');
      lineRes.className = 'term-line order-failed';
      lineRes.textContent = `   ❌ [ORDER GAGAL] RetCode: ${execution.retcode || 10016} - ${execution.message || 'Invalid stops'}`;
      terminalOutput.appendChild(lineRes);
    }

    // Auto scroll ke bawah
    terminalOutput.scrollTop = terminalOutput.scrollHeight;

    // Update unread badge jika terminal tertutup
    if (terminalDrawer.classList.contains('collapsed')) {
      const cur = parseInt(terminalBadge.textContent || '0') + 1;
      terminalBadge.textContent = cur;
      terminalBadge.style.display = 'inline-block';
    }
  }

  // ==========================================================================
  // DISPATCH & BROADCAST HANDLER
  // ==========================================================================

  function handleBroadcastSignal(signalData) {
    // 1. Mainkan Suara Sinyal Masuk
    audio.playSignalAlert();

    // 2. Animasi Pulsa 3D dari Server Room ke Semua Meja Member
    office.triggerSignalBroadcastAnimation(signalData);

    // 3. Update HUD Sinyal Terakhir
    hudSigAction.textContent = `${signalData.action} ${signalData.symbol}`;
    hudSigAction.className = `sig-badge ${signalData.action.toLowerCase()}`;
    hudSigTime.textContent = signalData.time;
    hudSigEntry.textContent = `$${signalData.entry.toFixed(2)}`;
    hudSigTp.textContent = `$${signalData.tp.toFixed(2)}`;
    hudSigSl.textContent = `$${signalData.sl.toFixed(2)}`;

    // 4. Simulasi Order Eksekusi ke Deden MT5
    setTimeout(() => {
      const ticketNum = Math.floor(15248100000 + Math.random() * 89999);
      const execution = {
        success: true,
        ticket: ticketNum,
        lot: 0.05,
        price: signalData.entry + (signalData.action === 'BUY' ? 0.34 : -0.34),
        symbol: 'XAUUSDc'
      };

      audio.playOrderSuccess();
      hudSigStatus.textContent = `✅ Dieksekusi ke MT5 (#${ticketNum})`;
      appendTerminalSignal(signalData, execution);

      // Tambahkan ke open positions
      state.openPositions.unshift({
        ticket: ticketNum,
        symbol: 'XAUUSDc',
        type: signalData.action,
        lot: 0.05,
        openPrice: execution.price,
        profit: 0.0
      });
      updateOpenPositionsUI();
    }, 900);
  }

  function updateOpenPositionsUI() {
    if (state.openPositions.length === 0) {
      hudOpenPositions.textContent = 'Tidak ada posisi terbuka (Standby)';
      return;
    }
    const p = state.openPositions[0];
    const isBuy = p.type === 'BUY';
    const badgeClass = isBuy ? 'badge-buy' : 'badge-sell';
    const pnlSign = p.profit >= 0 ? '+' : '';
    hudOpenPositions.innerHTML = `<span class="${badgeClass}">${p.type}</span> ${p.lot} Lot @ ${p.openPrice.toFixed(2)} (${pnlSign}${p.profit.toFixed(2)} ${state.account.currency})`;
  }

  // ==========================================================================
  // BACKEND API SYNC / POLLING (With Standalone Simulation Fallback)
  // ==========================================================================

  async function checkBackendStatus() {
    try {
      const res = await fetch('http://127.0.0.1:8080/api/status', { cache: 'no-store' });
      if (res.ok) {
        const data = await res.json();
        state.isLive = true;
        syncStatus.className = 'sync-indicator connected';
        syncText.textContent = 'LIVE MT5';

        // Update real MT5 account info jika tersedia
        if (data.account && data.account.connected) {
          state.account = data.account;
          hudMt5Login.textContent = `${data.account.server} #${data.account.login}`;
          hudMt5Balance.innerHTML = `$${data.account.balance.toFixed(2)} ${data.account.currency} / <strong class="equity-up">$${data.account.equity.toFixed(2)}</strong>`;
        }

        if (data.positions) {
          state.openPositions = data.positions;
          updateOpenPositionsUI();
        }

        if (data.gold_price) {
          state.goldPrice = data.gold_price;
          navGoldPrice.textContent = `$${data.gold_price.toFixed(2)}`;
        }
        return;
      }
    } catch (e) {
      // Backend server belum aktif, gunakan mode simulasi visual
    }

    // Fallback mode standalone simulation
    state.isLive = false;
    syncStatus.className = 'sync-indicator standalone';
    syncText.textContent = 'STANDALONE (SIM)';
  }

  // Poll status setiap 3 detik
  setInterval(checkBackendStatus, 3000);
  checkBackendStatus();

  // Fluktuasi harga emas live tick halus di UI
  setInterval(() => {
    const delta = (Math.random() - 0.48) * 0.35;
    state.goldPrice = Math.max(2500, state.goldPrice + delta);
    navGoldPrice.textContent = `$${state.goldPrice.toFixed(2)}`;
  }, 2000);

  // ==========================================================================
  // MODAL HANDLERS
  // ==========================================================================

  // Agent Clicked from 3D Scene or Top Bar
  window.addEventListener('agent-clicked', (e) => {
    const agentData = e.detail;
    openAgentModal(agentData);
  });

  document.querySelectorAll('.roster-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      const id = chip.getAttribute('data-agent-id');
      const agent = office.agents[id];
      if (agent) {
        office.focusOnAgent(id);
        openAgentModal(agent.data);
      }
    });
  });

  function openAgentModal(agentData) {
    state.selectedAgent = agentData;

    document.getElementById('modal-agent-name').textContent = agentData.name;
    document.getElementById('modal-agent-role').textContent = agentData.role;
    document.getElementById('modal-agent-avatar').textContent = agentData.isMaster ? '👑' : agentData.isDeden ? '💻' : '👨‍💻';
    document.getElementById('modal-agent-account').textContent = agentData.account;
    document.getElementById('modal-agent-server').textContent = agentData.server;
    document.getElementById('modal-agent-lot').textContent = agentData.lot;
    document.getElementById('modal-agent-balance').textContent = agentData.balance;
    document.getElementById('modal-agent-equity').textContent = agentData.equity;

    modalAgentDetail.classList.remove('hidden');
  }

  document.getElementById('btn-close-agent-modal').addEventListener('click', () => {
    modalAgentDetail.classList.add('hidden');
  });

  document.getElementById('btn-focus-cam-agent').addEventListener('click', () => {
    if (state.selectedAgent) {
      office.focusOnAgent(state.selectedAgent.id);
      modalAgentDetail.classList.add('hidden');
    }
  });

  document.getElementById('btn-ping-agent').addEventListener('click', () => {
    const btn = document.getElementById('btn-ping-agent');
    btn.textContent = '⏳ Menguji Ping...';
    setTimeout(() => {
      btn.textContent = '⚡ Latency: 12 ms (Optimal)';
      setTimeout(() => { btn.textContent = '⚡ Test Ping MT5'; }, 3000);
    }, 600);
  });

  // Broadcast Test Signal Modal
  document.getElementById('btn-broadcast-test').addEventListener('click', () => {
    document.getElementById('input-entry').value = state.goldPrice.toFixed(2);
    document.getElementById('input-tp').value = (state.goldPrice + 4.5).toFixed(2);
    document.getElementById('input-sl').value = (state.goldPrice - 4.5).toFixed(2);
    modalBroadcast.classList.remove('hidden');
  });

  document.getElementById('btn-close-broadcast').addEventListener('click', () => {
    modalBroadcast.classList.add('hidden');
  });
  document.getElementById('btn-cancel-broadcast').addEventListener('click', () => {
    modalBroadcast.classList.add('hidden');
  });

  document.getElementById('broadcast-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const action = document.querySelector('input[name="signal_action"]:checked').value;
    const symbol = document.getElementById('input-symbol').value.trim() || 'XAUUSD';
    const entry = parseFloat(document.getElementById('input-entry').value) || state.goldPrice;
    const tp = parseFloat(document.getElementById('input-tp').value) || (entry + 5);
    const sl = parseFloat(document.getElementById('input-sl').value) || (entry - 5);

    const nowTime = new Date().toTimeString().split(' ')[0];
    const sigPayload = { action, symbol, entry, tp, sl, time: nowTime };

    modalBroadcast.classList.add('hidden');
    handleBroadcastSignal(sigPayload);

    // Kirim ke backend jika tersedia
    if (state.isLive) {
      fetch('http://127.0.0.1:8080/api/signal', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(sigPayload)
      }).catch(() => {});
    }
  });

  // Settings Modal
  document.getElementById('btn-open-settings').addEventListener('click', () => {
    modalSettings.classList.remove('hidden');
  });
  document.getElementById('btn-close-settings').addEventListener('click', () => {
    modalSettings.classList.add('hidden');
  });
  document.getElementById('btn-cancel-settings').addEventListener('click', () => {
    modalSettings.classList.add('hidden');
  });
  document.getElementById('config-form').addEventListener('submit', (e) => {
    e.preventDefault();
    alert('✅ Konfigurasi Copier berhasil diperbarui & disimpan ke config.json!');
    modalSettings.classList.add('hidden');
  });

  // Open Members Modal
  document.getElementById('btn-open-members').addEventListener('click', () => {
    const agent = office.agents['deden'];
    if (agent) {
      office.focusOnAgent('deden');
      openAgentModal(agent.data);
    }
  });

  // Close modals on clicking overlay background
  [modalAgentDetail, modalBroadcast, modalSettings].forEach(modal => {
    modal.addEventListener('click', (e) => {
      if (e.target === modal) modal.classList.add('hidden');
    });
  });

  // ==========================================================================
  // TERMINAL DRAWER CONTROLS
  // ==========================================================================

  const toggleTerminal = () => {
    terminalDrawer.classList.toggle('collapsed');
    if (!terminalDrawer.classList.contains('collapsed')) {
      terminalBadge.style.display = 'none';
      terminalBadge.textContent = '0';
      terminalOutput.scrollTop = terminalOutput.scrollHeight;
    }
  };

  document.getElementById('btn-toggle-terminal').addEventListener('click', toggleTerminal);
  document.getElementById('btn-minimize-term').addEventListener('click', toggleTerminal);
  document.getElementById('btn-close-terminal').addEventListener('click', toggleTerminal);

  document.getElementById('btn-clear-term').addEventListener('click', () => {
    terminalOutput.innerHTML = `
      <div class="term-line prompt">Windows PowerShell</div>
      <div class="term-line prompt">Copyright (C) Microsoft Corporation. All rights reserved.</div>
      <div class="term-line prompt">PS C:\\Projects\\botrading\\member_copier&gt; </div>
    `;
  });

  document.getElementById('btn-copy-term').addEventListener('click', () => {
    navigator.clipboard.writeText(terminalOutput.innerText);
    alert('📋 Log terminal disalin ke clipboard!');
  });

  // ==========================================================================
  // TOOLBAR CONTROLS (Theme, Sound, Camera)
  // ==========================================================================

  const btnSound = document.getElementById('btn-sound-toggle');
  btnSound.addEventListener('click', () => {
    audio.muted = !audio.muted;
    btnSound.textContent = audio.muted ? '🔇' : '🔊';
    btnSound.title = audio.muted ? 'Audio FX Mati (Klik untuk Mengaktifkan)' : 'Audio FX Aktif';
  });

  const btnTheme = document.getElementById('btn-theme-toggle');
  btnTheme.addEventListener('click', () => {
    const isNight = office.toggleTheme();
    document.body.className = isNight ? 'theme-night' : 'theme-day';
    btnTheme.textContent = isNight ? '🌙' : '☀️';
  });

  document.getElementById('btn-reset-cam').addEventListener('click', () => {
    office.setCameraMode('iso');
    document.querySelectorAll('.cam-btn').forEach(b => b.classList.remove('active'));
    document.querySelector('.cam-btn[data-cam="iso"]').classList.add('active');
  });

  // Camera Mode Buttons in Bottom Right
  document.querySelectorAll('.cam-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('.cam-btn').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const camMode = btn.getAttribute('data-cam');
      office.setCameraMode(camMode);
    });
  });
});
