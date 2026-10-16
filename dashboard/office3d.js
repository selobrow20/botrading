/**
 * ==============================================================================
 * BOTRADING 3D ISOMETRIC TRADING OFFICE (v2.0)
 * ==============================================================================
 * Virtual Trading Floor dengan karakter animasi realistis yang bekerja nyata:
 * - Mengetik cepat (typing burst) dengan tangan artikulasi independen
 * - Menganalisis chart & bersandar di kursi ergonomis
 * - Mengambil & meminum kopi dari cangkir di meja
 * - Diskusi & memutar kursi ke arah rekan kerja
 * - Selebrasi profit saat Take Profit / sinyal tercapai
 * - Layar laptop dinamis dengan animasi grafik candlestick & kode terminal
 * - Layar monitor dinding besar dengan live ticker harga & jam bursa
 * - Aliran partikel data cyber dari Server VPS ke seluruh meja
 * ==============================================================================
 */

class Office3D {
  constructor(canvasId, labelsContainerId, speechContainerId) {
    this.canvas = document.getElementById(canvasId);
    this.labelsContainer = document.getElementById(labelsContainerId);
    this.speechContainer = document.getElementById(speechContainerId);

    this.scene = null;
    this.camera = null;
    this.renderer = null;
    this.controls = null;
    this.raycaster = new THREE.Raycaster();
    this.mouse = new THREE.Vector2();

    this.agents = {}; // Map of agentId -> agent object
    this.desks = [];
    this.particles = [];
    this.blinkingLeds = [];
    this.steamParticles = [];
    this.dataPackets = [];

    this.isNight = true;
    this.cameraTarget = new THREE.Vector3(0, 0, 0);
    this.cameraDesiredPos = new THREE.Vector3(36, 30, 36);

    this.clock = new THREE.Clock();
    this.lastDialogueTime = 0;
    this.dialogueInterval = 10; // Setiap 10 detik ada yang berbicara

    // Wall Chart & Animated Canvas Textures
    this.wallCanvas = null;
    this.wallCtx = null;
    this.wallTexture = null;
    this.wallLastUpdate = 0;
    this.wallPrice = 4185.80;

    this.init();
  }

  init() {
    // 1. Scene
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(this.isNight ? 0x070b14 : 0xccd6e0);
    this.scene.fog = new THREE.FogExp2(this.isNight ? 0x070b14 : 0xccd6e0, 0.007);

    // 2. Camera (Isometric Low FOV)
    const aspect = (this.canvas.clientWidth || 800) / (this.canvas.clientHeight || 600);
    this.camera = new THREE.PerspectiveCamera(34, aspect, 0.5, 500);
    this.camera.position.set(36, 30, 36);
    this.camera.lookAt(0, 0, 0);

    // 3. Renderer
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      powerPreference: "high-performance"
    });
    this.renderer.setSize(this.canvas.clientWidth || 800, this.canvas.clientHeight || 600);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    // 4. Orbit Controls
    this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.maxPolarAngle = Math.PI / 2.15;
    this.controls.minDistance = 14;
    this.controls.maxDistance = 85;
    this.controls.target.set(0, 1, 0);

    // 5. Lighting
    this.setupLighting();

    // 6. Build Environment
    this.buildOfficeEnvironment();

    // 7. Spawn Traders
    this.spawnAgents();

    // 8. Setup Data Packet Highways
    this.setupDataPacketSystem();

    // 9. Event Listeners
    window.addEventListener('resize', () => this.onResize());
    this.canvas.addEventListener('click', (e) => this.onCanvasClick(e));

    // 10. Start Animation Loop
    this.animate();
  }

  setupLighting() {
    this.ambientLight = new THREE.AmbientLight(0xffffff, this.isNight ? 0.75 : 1.15);
    this.scene.add(this.ambientLight);

    this.dirLight = new THREE.DirectionalLight(0xfffaed, this.isNight ? 1.25 : 1.6);
    this.dirLight.position.set(25, 40, 20);
    this.dirLight.castShadow = true;
    this.dirLight.shadow.mapSize.width = 2048;
    this.dirLight.shadow.mapSize.height = 2048;
    this.dirLight.shadow.camera.near = 0.5;
    this.dirLight.shadow.camera.far = 120;
    const d = 26;
    this.dirLight.shadow.camera.left = -d;
    this.dirLight.shadow.camera.right = d;
    this.dirLight.shadow.camera.top = d;
    this.dirLight.shadow.camera.bottom = -d;
    this.dirLight.shadow.bias = -0.0005;
    this.scene.add(this.dirLight);

    // Server Room Cyan Glow
    this.serverLight = new THREE.PointLight(0x00f0ff, 2.8, 20);
    this.serverLight.position.set(-11, 4, -9);
    this.scene.add(this.serverLight);

    // Warm Accents
    const warm1 = new THREE.PointLight(0xffeedd, 0.8, 25);
    warm1.position.set(5, 8, 5);
    this.scene.add(warm1);

    const warm2 = new THREE.PointLight(0xffeedd, 0.8, 25);
    warm2.position.set(-5, 8, 5);
    this.scene.add(warm2);
  }

  buildOfficeEnvironment() {
    // 1. Lantai Ubin Hangat
    const floorGeo = new THREE.BoxGeometry(38, 0.6, 26);
    const floorMat = new THREE.MeshStandardMaterial({
      color: 0xede4d5,
      roughness: 0.35,
      metalness: 0.05
    });
    const floor = new THREE.Mesh(floorGeo, floorMat);
    floor.position.set(0, -0.3, 0);
    floor.receiveShadow = true;
    this.scene.add(floor);

    const tileGrid = new THREE.GridHelper(38, 38, 0xdfd4c2, 0xe4dac9);
    tileGrid.position.set(0, 0.01, 0);
    this.scene.add(tileGrid);

    // 2. Dinding Perimeter
    const wallMat = new THREE.MeshStandardMaterial({ color: 0xdedede, roughness: 0.6 });
    const wallTrimMat = new THREE.MeshStandardMaterial({ color: 0x9ca3af, roughness: 0.4 });

    const backWallZ = new THREE.Mesh(new THREE.BoxGeometry(38, 6, 0.6), wallMat);
    backWallZ.position.set(0, 3, -13);
    backWallZ.castShadow = true;
    backWallZ.receiveShadow = true;
    this.scene.add(backWallZ);

    const backWallX = new THREE.Mesh(new THREE.BoxGeometry(0.6, 6, 26), wallMat);
    backWallX.position.set(-19, 3, 0);
    backWallX.castShadow = true;
    backWallX.receiveShadow = true;
    this.scene.add(backWallX);

    const lowWallFront = new THREE.Mesh(new THREE.BoxGeometry(38, 0.8, 0.6), wallTrimMat);
    lowWallFront.position.set(0, 0.4, 13);
    lowWallFront.receiveShadow = true;
    this.scene.add(lowWallFront);

    const lowWallRight = new THREE.Mesh(new THREE.BoxGeometry(0.6, 0.8, 26), wallTrimMat);
    lowWallRight.position.set(19, 0.4, 0);
    lowWallRight.receiveShadow = true;
    this.scene.add(lowWallRight);

    // 3. Ruangan & Furniture
    this.buildServerRoom();
    this.buildConferenceArea();
    this.buildExecutiveDesk();
    this.buildLoungeArea();
    this.buildOfficeDecorations();
  }

  buildServerRoom() {
    const serverWallMat = new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.5 });
    
    const partZ = new THREE.Mesh(new THREE.BoxGeometry(8, 5, 0.4), serverWallMat);
    partZ.position.set(-15, 2.5, -5);
    partZ.castShadow = true;
    this.scene.add(partZ);

    const partX = new THREE.Mesh(new THREE.BoxGeometry(0.4, 5, 5), serverWallMat);
    partX.position.set(-11, 2.5, -10.5);
    partX.castShadow = true;
    this.scene.add(partX);

    const sFloor = new THREE.Mesh(
      new THREE.BoxGeometry(8, 0.05, 8),
      new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.2, metalness: 0.6 })
    );
    sFloor.position.set(-15, 0.02, -9);
    this.scene.add(sFloor);

    // 2 RAK SERVER BESAR
    for (let i = 0; i < 2; i++) {
      const rackGroup = new THREE.Group();
      const rack = new THREE.Mesh(
        new THREE.BoxGeometry(2, 4.2, 1.6),
        new THREE.MeshStandardMaterial({ color: 0x111827, roughness: 0.3, metalness: 0.8 })
      );
      rack.position.y = 2.1;
      rack.castShadow = true;
      rackGroup.add(rack);

      const glass = new THREE.Mesh(
        new THREE.BoxGeometry(1.8, 3.8, 0.1),
        new THREE.MeshStandardMaterial({ color: 0x0f172a, roughness: 0.1, metalness: 0.9, transparent: true, opacity: 0.85 })
      );
      glass.position.set(0, 2.1, 0.85);
      rackGroup.add(glass);

      // LED Server Berkedip
      for (let r = 0; r < 7; r++) {
        for (let c = 0; c < 3; c++) {
          const ledColor = (r % 3 === 0) ? 0x00f0ff : (r % 3 === 1) ? 0x10b981 : 0xf59e0b;
          const led = new THREE.Mesh(new THREE.BoxGeometry(0.12, 0.08, 0.05), new THREE.MeshBasicMaterial({ color: ledColor }));
          led.position.set(-0.6 + c * 0.6, 0.8 + r * 0.45, 0.9);
          rackGroup.add(led);

          this.blinkingLeds.push({
            mesh: led,
            origColor: ledColor,
            interval: 0.15 + Math.random() * 0.5,
            lastToggle: 0
          });
        }
      }

      rackGroup.position.set(-16.5 + i * 2.8, 0, -9.5);
      this.scene.add(rackGroup);
    }
  }

  buildConferenceArea() {
    const confGroup = new THREE.Group();
    const woodMat = new THREE.MeshStandardMaterial({ color: 0x926644, roughness: 0.4 });
    const legMat = new THREE.MeshStandardMaterial({ color: 0x333333, metalness: 0.7 });

    const tableTop = new THREE.Mesh(new THREE.CylinderGeometry(3.2, 3.2, 0.2, 32), woodMat);
    tableTop.position.y = 1.3;
    tableTop.castShadow = true;
    tableTop.receiveShadow = true;
    confGroup.add(tableTop);

    const leg = new THREE.Mesh(new THREE.CylinderGeometry(0.5, 0.8, 1.3, 16), legMat);
    leg.position.y = 0.65;
    confGroup.add(leg);

    for (let a = 0; a < 5; a++) {
      const angle = (a / 5) * Math.PI * 2;
      const chair = this.createOfficeChair(0x374151);
      chair.position.set(Math.cos(angle) * 4.2, 0, Math.sin(angle) * 4.2);
      chair.rotation.y = -angle - Math.PI / 2;
      confGroup.add(chair);
    }

    confGroup.position.set(-6, 0, -8);
    this.scene.add(confGroup);

    // Meja Bundar Kecil Diskusi
    const smallTable = new THREE.Group();
    const sTop = new THREE.Mesh(new THREE.CylinderGeometry(2, 2, 0.15, 24), woodMat);
    sTop.position.y = 1.2;
    sTop.castShadow = true;
    smallTable.add(sTop);

    const sLeg = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.5, 1.2, 16), legMat);
    sLeg.position.y = 0.6;
    smallTable.add(sLeg);

    const c1 = this.createOfficeChair(0x1e293b);
    c1.position.set(2.5, 0, 0);
    c1.rotation.y = -Math.PI / 2;
    smallTable.add(c1);

    const c2 = this.createOfficeChair(0x1e293b);
    c2.position.set(-2.5, 0, 0);
    c2.rotation.y = Math.PI / 2;
    smallTable.add(c2);

    smallTable.position.set(13, 0, 4);
    this.scene.add(smallTable);
  }

  buildExecutiveDesk() {
    const execGroup = new THREE.Group();
    const darkWoodMat = new THREE.MeshStandardMaterial({ color: 0x6e4726, roughness: 0.4 });

    const mainDesk = new THREE.Mesh(new THREE.BoxGeometry(4.5, 1.3, 1.8), darkWoodMat);
    mainDesk.position.set(0, 0.65, 0);
    mainDesk.castShadow = true;
    execGroup.add(mainDesk);

    const sideDesk = new THREE.Mesh(new THREE.BoxGeometry(1.8, 1.3, 2.8), darkWoodMat);
    sideDesk.position.set(1.8, 0.65, 1.4);
    sideDesk.castShadow = true;
    execGroup.add(sideDesk);

    const bossChair = this.createOfficeChair(0x111827, true);
    bossChair.position.set(0, 0, -1.6);
    execGroup.add(bossChair);

    const shelf = new THREE.Mesh(new THREE.BoxGeometry(5.5, 4.5, 1.2), darkWoodMat);
    shelf.position.set(0, 2.25, -4);
    shelf.castShadow = true;
    execGroup.add(shelf);

    const laptop = this.createAnimatedLaptop('master_exec', 0x00f0ff);
    laptop.mesh.position.set(-0.6, 1.35, 0);
    execGroup.add(laptop.mesh);

    execGroup.position.set(5, 0, -7.5);
    this.scene.add(execGroup);
  }

  buildLoungeArea() {
    const loungeGroup = new THREE.Group();
    const sofaBlueMat = new THREE.MeshStandardMaterial({ color: 0x2563eb, roughness: 0.6 });

    const sofaBase = new THREE.Mesh(new THREE.BoxGeometry(4.2, 0.6, 1.6), sofaBlueMat);
    sofaBase.position.set(0, 0.3, 0);
    sofaBase.castShadow = true;
    loungeGroup.add(sofaBase);

    const sofaBack = new THREE.Mesh(new THREE.BoxGeometry(4.2, 1.1, 0.5), sofaBlueMat);
    sofaBack.position.set(0, 0.85, 0.6);
    sofaBack.castShadow = true;
    loungeGroup.add(sofaBack);

    // Meja Ping Pong
    const pingPongGroup = new THREE.Group();
    const pTable = new THREE.Mesh(
      new THREE.BoxGeometry(4.8, 0.15, 2.6),
      new THREE.MeshStandardMaterial({ color: 0x15803d, roughness: 0.3 })
    );
    pTable.position.y = 1.2;
    pTable.castShadow = true;
    pingPongGroup.add(pTable);

    const net = new THREE.Mesh(
      new THREE.BoxGeometry(0.04, 0.4, 2.8),
      new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.85 })
    );
    net.position.y = 1.45;
    pingPongGroup.add(net);

    const pLegMat = new THREE.MeshStandardMaterial({ color: 0x222222 });
    for (let lx of [-2.1, 2.1]) {
      for (let lz of [-1.1, 1.1]) {
        const pleg = new THREE.Mesh(new THREE.BoxGeometry(0.1, 1.2, 0.1), pLegMat);
        pleg.position.set(lx, 0.6, lz);
        pingPongGroup.add(pleg);
      }
    }

    pingPongGroup.position.set(9.5, 0, 9);
    this.scene.add(pingPongGroup);

    loungeGroup.position.set(10.5, 0, 3.5);
    this.scene.add(loungeGroup);
  }

  buildOfficeDecorations() {
    // 1. Monitor TV Dinding Besar dengan LIVE ANIMATED CHART
    const tvGroup = new THREE.Group();
    const frame = new THREE.Mesh(new THREE.BoxGeometry(5.8, 3.4, 0.2), new THREE.MeshStandardMaterial({ color: 0x111827 }));
    tvGroup.add(frame);

    // Setup Canvas Dinamis untuk Layar Dinding
    this.wallCanvas = document.createElement('canvas');
    this.wallCanvas.width = 512;
    this.wallCanvas.height = 280;
    this.wallCtx = this.wallCanvas.getContext('2d');
    this.wallTexture = new THREE.CanvasTexture(this.wallCanvas);

    const screenGeo = new THREE.PlaneGeometry(5.5, 3.1);
    const screenMat = new THREE.MeshBasicMaterial({ map: this.wallTexture });
    const screen = new THREE.Mesh(screenGeo, screenMat);
    screen.position.z = 0.11;
    tvGroup.add(screen);

    tvGroup.position.set(11, 4, -12.8);
    this.scene.add(tvGroup);

    // 2. Tanaman Hias Pot Hijau
    const plantCoords = [[-17, -3], [-8, -12.5], [17, -12.5], [17, 11], [-5, 11]];
    for (let [px, pz] of plantCoords) {
      const plant = this.createPottedPlant();
      plant.position.set(px, 0, pz);
      this.scene.add(plant);
    }
  }

  createOfficeChair(color = 0x374151, isHighBack = false) {
    const chairGroup = new THREE.Group();
    const cushionMat = new THREE.MeshStandardMaterial({ color: color, roughness: 0.6 });
    const metalMat = new THREE.MeshStandardMaterial({ color: 0x1f2937, metalness: 0.8 });

    const seat = new THREE.Mesh(new THREE.BoxGeometry(0.9, 0.12, 0.9), cushionMat);
    seat.position.y = 0.75;
    seat.castShadow = true;
    chairGroup.add(seat);

    const backHeight = isHighBack ? 1.4 : 0.9;
    const back = new THREE.Mesh(new THREE.BoxGeometry(0.85, backHeight, 0.12), cushionMat);
    back.position.set(0, 0.75 + backHeight / 2, -0.42);
    back.castShadow = true;
    chairGroup.add(back);

    const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.75, 12), metalMat);
    stem.position.y = 0.375;
    chairGroup.add(stem);

    const baseStar = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.45, 0.06, 5), metalMat);
    baseStar.position.y = 0.06;
    chairGroup.add(baseStar);

    return chairGroup;
  }

  createAnimatedLaptop(id, glowColorHex = 0x00f0ff) {
    const lapGroup = new THREE.Group();
    const bodyMat = new THREE.MeshStandardMaterial({ color: 0x94a3b8, metalness: 0.7, roughness: 0.3 });

    // Keyboard Base
    const base = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.04, 0.55), bodyMat);
    base.castShadow = true;
    lapGroup.add(base);

    // Keyboard Keys Mock
    const kb = new THREE.Mesh(new THREE.BoxGeometry(0.72, 0.045, 0.32), new THREE.MeshBasicMaterial({ color: 0x1e293b }));
    kb.position.set(0, 0.005, 0.04);
    lapGroup.add(kb);

    // Monitor Lid
    const lidGroup = new THREE.Group();
    const lid = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.55, 0.03), bodyMat);
    lid.position.set(0, 0.27, 0);
    lidGroup.add(lid);

    // Canvas Texture Mini Chart
    const c = document.createElement('canvas');
    c.width = 128;
    c.height = 80;
    const ctx = c.getContext('2d');
    const tex = new THREE.CanvasTexture(c);

    const screenMat = new THREE.MeshBasicMaterial({ map: tex });
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.74, 0.48), screenMat);
    screen.position.set(0, 0.27, 0.02);
    lidGroup.add(screen);

    lidGroup.position.set(0, 0.02, -0.27);
    lidGroup.rotation.x = 0.25;
    lapGroup.add(lidGroup);

    return {
      mesh: lapGroup,
      canvas: c,
      ctx: ctx,
      texture: tex,
      screenMat: screenMat,
      glowColor: glowColorHex,
      codeLines: [
        "M15 EMA20 [OK]",
        "BUY 0.05 lot",
        "TP 4201.05",
        "Spread: 1.1"
      ]
    };
  }

  createCoffeeMug() {
    const mugGroup = new THREE.Group();
    // Keramik Cangkir Putih
    const mugGeo = new THREE.CylinderGeometry(0.12, 0.1, 0.22, 16);
    const mugMat = new THREE.MeshStandardMaterial({ color: 0xffffff, roughness: 0.2 });
    const mug = new THREE.Mesh(mugGeo, mugMat);
    mug.position.y = 0.11;
    mug.castShadow = true;
    mugGroup.add(mug);

    // Isi Kopi Hitam di dalam cangkir
    const coffeeGeo = new THREE.CylinderGeometry(0.11, 0.11, 0.02, 16);
    const coffeeMat = new THREE.MeshBasicMaterial({ color: 0x3d2314 });
    const coffee = new THREE.Mesh(coffeeGeo, coffeeMat);
    coffee.position.y = 0.18;
    mugGroup.add(coffee);

    // Gagang Cangkir
    const handleGeo = new THREE.TorusGeometry(0.06, 0.025, 8, 16, Math.PI);
    const handle = new THREE.Mesh(handleGeo, mugMat);
    handle.position.set(0.12, 0.11, 0);
    handle.rotation.z = -Math.PI / 2;
    mugGroup.add(handle);

    return mugGroup;
  }

  createPottedPlant() {
    const plantGroup = new THREE.Group();
    const pot = new THREE.Mesh(
      new THREE.CylinderGeometry(0.4, 0.3, 0.7, 16),
      new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.3 })
    );
    pot.position.y = 0.35;
    pot.castShadow = true;
    plantGroup.add(pot);

    const leafMat = new THREE.MeshStandardMaterial({ color: 0x16a34a, roughness: 0.5 });
    for (let i = 0; i < 5; i++) {
      const leaf = new THREE.Mesh(new THREE.DodecahedronGeometry(0.35 + Math.random() * 0.15), leafMat);
      leaf.position.set((Math.random() - 0.5) * 0.4, 0.8 + Math.random() * 0.5, (Math.random() - 0.5) * 0.4);
      leaf.castShadow = true;
      plantGroup.add(leaf);
    }
    return plantGroup;
  }

  setupDataPacketSystem() {
    // Jalur partikel data bercahaya dari Server VPS (-12, 1.5, -6) ke meja trader
    this.dataPackets = [];
    const serverOrigin = new THREE.Vector3(-12, 0.2, -6);

    const packetMat = new THREE.MeshBasicMaterial({ color: 0x00f0ff });
    const packetGeo = new THREE.SphereGeometry(0.08, 8, 8);

    for (let i = 0; i < 18; i++) {
      const mesh = new THREE.Mesh(packetGeo, packetMat);
      this.scene.add(mesh);
      this.dataPackets.push({
        mesh: mesh,
        start: serverOrigin.clone(),
        targetIndex: i % 7,
        progress: Math.random(),
        speed: 0.006 + Math.random() * 0.008
      });
    }
  }

  // ==========================================================================
  // SPAWN AGENT CHARACTERS & DESKS DENGAN ANATOMI BERGERAK LENGKAP
  // ==========================================================================

  spawnAgents() {
    const agentConfigs = [
      {
        id: 'master',
        name: 'Master Bot (VPS)',
        role: 'Master Signal Provider',
        account: '@selo_saham_bot',
        server: 'Ubuntu VPS Cloud',
        lot: 'Provider',
        balance: 'VPS Active',
        equity: 'Signals 267',
        shirtColor: 0x9333ea,
        pos: [-12, -2.5],
        rot: 0,
        colleagueId: 'cory',
        dialogues: [
          "M15 Trend Bullish terverifikasi via 9 Buku PDF.",
          "Golden Pocket Fibonacci 61.8% tersentuh di $4,185.",
          "Menyiapkan pending Buy Limit di support EMA 20.",
          "Semua copier terhubung dengan latensi 18ms."
        ]
      },
      {
        id: 'deden',
        name: 'Deden (You - Local MT5)',
        role: 'Client Copier (Lokal Windows)',
        account: 'HFMarkets #114202389',
        server: 'HFMarketsGlobal-Live7',
        lot: '0.05 Lot Cent',
        balance: '377.61 USC',
        equity: '365.86 USC',
        shirtColor: 0x0284c7,
        pos: [-1.5, 4.5],
        rot: Math.PI,
        colleagueId: 'luke',
        dialogues: [
          "MT5 Bridge terkoneksi aktif ke HFMarkets!",
          "Posisi BUY XAUUSDc berjalan dengan SL $4,178.",
          "Margin bebas aman di 350+ USC (Cent).",
          "Auto-BEP siap mengunci profit bila tembus +45 pips."
        ]
      },
      {
        id: 'luke',
        name: 'Luke',
        role: 'Member Copier (Scalper)',
        account: 'XM-UltraLow #339182',
        server: 'XMGlobal-Real',
        lot: '0.05 Lot',
        balance: '$890.00 USC',
        equity: '$895.50 USC',
        shirtColor: 0x2563eb,
        pos: [-2.5, 0.5],
        rot: 0,
        colleagueId: 'deden',
        dialogues: [
          "Scalping M15 candle rejection terpantau bersih.",
          "Spread emas sangat ketat, momentum bagus!",
          "Konfirmasi candle hijau berikutnya siap eksekusi."
        ]
      },
      {
        id: 'cory',
        name: 'Cory',
        role: 'Member Copier',
        account: 'Exness-Cent #9982104',
        server: 'Exness-Real12',
        lot: '0.05 Lot',
        balance: '$520.10 USC',
        equity: '$524.80 USC',
        shirtColor: 0x06b6d4,
        pos: [-5.5, -0.5],
        rot: 0,
        colleagueId: 'master',
        dialogues: [
          "Stop loss otomatis menjaga risiko maksimal 60 pips.",
          "Disiplin manajemen lot 1 layer sesuai buku PDF.",
          "Sinyal dari master VPS diterima tanpa delay."
        ]
      },
      {
        id: 'ben',
        name: 'Ben',
        role: 'Member Copier',
        account: 'ICMarkets #7712490',
        server: 'ICMarketsSC-Live04',
        lot: '0.05 Lot',
        balance: '$340.50 USC',
        equity: '$342.10 USC',
        shirtColor: 0x0d9488,
        pos: [1.5, 2.5],
        rot: 0,
        colleagueId: 'allan',
        dialogues: [
          "Akumulasi saham IDX (BBCA, BMRI) solid hari ini.",
          "Sesi 2 bursa dibuka, volume transaksi meningkat.",
          "Watchlist 27 saham selesai dipindai."
        ]
      },
      {
        id: 'allan',
        name: 'Allan',
        role: 'Member Copier',
        account: 'FBS-Cent #4510928',
        server: 'FBS-Real-Cent',
        lot: '0.05 Lot',
        balance: '$615.20 USC',
        equity: '$618.90 USC',
        shirtColor: 0xca8a04,
        pos: [5.5, 0.8],
        rot: 0,
        colleagueId: 'ben',
        dialogues: [
          "Auto-Pump Sniper mendeteksi volume spike PEPE & AVAX!",
          "Sweet spot pump +6.4% dengan skor scanner 88.",
          "Trailing profit siap kunci TP1 di +11%."
        ]
      },
      {
        id: 'susie',
        name: 'Susie',
        role: 'Member Copier (USD Std)',
        account: 'OctaFX #8829103',
        server: 'OctaFX-Real-1',
        lot: '0.01 Lot Standard',
        balance: '$1,250.00 USD',
        equity: '$1,254.20 USD',
        shirtColor: 0xeab308,
        pos: [7.5, -2.5],
        rot: 0,
        colleagueId: 'andrew',
        dialogues: [
          "News Limit Guard: Tidak ada berita high-impact terdekat.",
          "Akun Standard 0.01 lot disiplin margin aman.",
          "Rasio Risk:Reward 1:2 terjaga dengan baik."
        ]
      },
      {
        id: 'andrew',
        name: 'Andrew',
        role: 'Member Copier',
        account: 'HFMarkets #9812044',
        server: 'HFMarketsGlobal-Live5',
        lot: '0.05 Lot',
        balance: '$410.80 USC',
        equity: '$412.30 USC',
        shirtColor: 0xd97706,
        pos: [12.5, -1.5],
        rot: 0,
        colleagueId: 'susie',
        dialogues: [
          "Sesi London mulai aktif pukul 14:00 WIB.",
          "Likuiditas pasar emas melonjak tinggi.",
          "Semua 7 copier standby eksekusi paralel."
        ]
      }
    ];

    for (let cfg of agentConfigs) {
      this.createArticulatedDeskAgent(cfg);
    }
  }

  createArticulatedDeskAgent(cfg) {
    const group = new THREE.Group();

    // 1. Meja Kayu
    const deskGeo = new THREE.BoxGeometry(2.4, 1.3, 1.4);
    const deskMat = new THREE.MeshStandardMaterial({ color: 0xab7a4e, roughness: 0.4 });
    const desk = new THREE.Mesh(deskGeo, deskMat);
    desk.position.set(0, 0.65, 0);
    desk.castShadow = true;
    desk.receiveShadow = true;
    group.add(desk);

    // Mousepad & Mouse
    const mousepad = new THREE.Mesh(
      new THREE.BoxGeometry(0.35, 0.01, 0.4),
      new THREE.MeshBasicMaterial({ color: 0x1e293b })
    );
    mousepad.position.set(0.6, 1.31, 0.05);
    group.add(mousepad);

    const mouseMesh = new THREE.Mesh(
      new THREE.BoxGeometry(0.12, 0.04, 0.18),
      new THREE.MeshStandardMaterial({ color: 0x64748b })
    );
    mouseMesh.position.set(0.6, 1.33, 0.05);
    group.add(mouseMesh);

    // Cangkir Kopi di Meja
    const mug = this.createCoffeeMug();
    mug.position.set(0.75, 1.3, -0.35);
    group.add(mug);

    // Steam partikel dari kopi
    const steamGroup = new THREE.Group();
    steamGroup.position.set(0.75, 1.55, -0.35);
    group.add(steamGroup);

    // 2. Laptop dengan Animasi Chart & Kode
    const laptop = this.createAnimatedLaptop(cfg.id, cfg.id === 'master' ? 0xa855f7 : cfg.id === 'deden' ? 0x00f0ff : 0x10b981);
    laptop.mesh.position.set(0, 1.32, -0.15);
    group.add(laptop.mesh);

    // 3. Kursi Putar dengan Poros Swivel
    const chairSwivel = new THREE.Group();
    chairSwivel.position.set(0, 0, 1.1);
    const chair = this.createOfficeChair(0x1f2937);
    chair.rotation.y = Math.PI;
    chairSwivel.add(chair);
    group.add(chairSwivel);

    // 4. KARAKTER 3D DENGAN ARTIKULASI TUBUH PENUH
    const charGroup = new THREE.Group();
    charGroup.position.set(0, 0, 1.1); // Duduk di kursi

    // Kaki
    const pantsMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.5 });
    const legs = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.6, 0.6), pantsMat);
    legs.position.set(0, 0.65, -0.2);
    charGroup.add(legs);

    // Torso (Badan dengan pivot pinggang)
    const torsoGroup = new THREE.Group();
    torsoGroup.position.set(0, 0.95, -0.2); // Pinggang
    charGroup.add(torsoGroup);

    const shirtMat = new THREE.MeshStandardMaterial({ color: cfg.shirtColor, roughness: 0.4 });
    const torsoMesh = new THREE.Mesh(new THREE.BoxGeometry(0.65, 0.75, 0.38), shirtMat);
    torsoMesh.position.set(0, 0.375, 0);
    torsoMesh.castShadow = true;
    torsoGroup.add(torsoMesh);

    // Kepala (Head & Neck Group)
    const headGroup = new THREE.Group();
    headGroup.position.set(0, 0.85, 0); // Di atas torso
    torsoGroup.add(headGroup);

    const skinMat = new THREE.MeshStandardMaterial({ color: 0xfbcfe8, roughness: 0.3 });
    const headMesh = new THREE.Mesh(new THREE.BoxGeometry(0.44, 0.44, 0.42), skinMat);
    headMesh.position.set(0, 0.22, 0);
    headMesh.castShadow = true;
    headGroup.add(headMesh);

    const hairColor = cfg.id === 'susie' ? 0xb45309 : cfg.id === 'deden' ? 0x18181b : 0x451a03;
    const hair = new THREE.Mesh(new THREE.BoxGeometry(0.48, 0.18, 0.45), new THREE.MeshStandardMaterial({ color: hairColor }));
    hair.position.set(0, 0.44, 0);
    headGroup.add(hair);

    // LENGAN KIRI (Shoulder Pivot)
    const shoulderLeft = new THREE.Group();
    shoulderLeft.position.set(-0.38, 0.65, 0);
    torsoGroup.add(shoulderLeft);

    const upperArmLeft = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.32, 0.14), shirtMat);
    upperArmLeft.position.set(0, -0.16, 0);
    shoulderLeft.add(upperArmLeft);

    const elbowLeft = new THREE.Group();
    elbowLeft.position.set(0, -0.32, 0);
    shoulderLeft.add(elbowLeft);

    const forearmLeft = new THREE.Mesh(new THREE.BoxGeometry(0.13, 0.13, 0.38), shirtMat);
    forearmLeft.position.set(0, 0, -0.19);
    elbowLeft.add(forearmLeft);

    // LENGAN KANAN (Shoulder Pivot)
    const shoulderRight = new THREE.Group();
    shoulderRight.position.set(0.38, 0.65, 0);
    torsoGroup.add(shoulderRight);

    const upperArmRight = new THREE.Mesh(new THREE.BoxGeometry(0.14, 0.32, 0.14), shirtMat);
    upperArmRight.position.set(0, -0.16, 0);
    shoulderRight.add(upperArmRight);

    const elbowRight = new THREE.Group();
    elbowRight.position.set(0, -0.32, 0);
    shoulderRight.add(elbowRight);

    const forearmRight = new THREE.Mesh(new THREE.BoxGeometry(0.13, 0.13, 0.38), shirtMat);
    forearmRight.position.set(0, 0, -0.19);
    elbowRight.add(forearmRight);

    group.add(charGroup);

    // Posisikan Meja & Karakter
    group.position.set(cfg.pos[0], 0, cfg.pos[1]);
    group.rotation.y = cfg.rot;
    this.scene.add(group);

    // Floating 2D DOM Label Badge
    const labelEl = this.createFloatingLabel(cfg);

    // Simpan objek agen dengan state machine cerdas
    this.agents[cfg.id] = {
      id: cfg.id,
      name: cfg.name,
      group: group,
      charGroup: charGroup,
      chairSwivel: chairSwivel,
      torsoGroup: torsoGroup,
      headGroup: headGroup,
      shoulderLeft: shoulderLeft,
      elbowLeft: elbowLeft,
      shoulderRight: shoulderRight,
      elbowRight: elbowRight,
      mouseMesh: mouseMesh,
      mug: mug,
      steamGroup: steamGroup,
      laptop: laptop,
      screenMat: laptop.screenMat,
      labelEl: labelEl,
      data: cfg,
      basePos: new THREE.Vector3(cfg.pos[0], 0, cfg.pos[1]),
      headWorldPos: new THREE.Vector3(),
      
      // Work State Machine
      workState: 'typing', // 'typing', 'reading_chart', 'sipping_coffee', 'consulting', 'celebrating'
      stateTimer: 0,
      nextStateDuration: 4 + Math.random() * 6,
      typingSpeed: 14 + Math.random() * 12,
      isTypingFast: false,
      coffeeSipProgress: 0
    };
  }

  createFloatingLabel(cfg) {
    const badge = document.createElement('div');
    badge.className = `agent-3d-badge ${cfg.id === 'master' ? 'master-tag' : ''} ${cfg.id === 'deden' ? 'deden-tag' : ''}`;
    badge.setAttribute('data-agent-id', cfg.id);

    const avatarIcon = cfg.id === 'master' ? '👑' : cfg.id === 'deden' ? '💻' : '🧑‍💻';
    const dotClass = cfg.id === 'master' ? 'dot-purple' : 'dot-green';

    badge.innerHTML = `
      <span class="badge-avatar">${avatarIcon}</span>
      <span class="badge-text">${cfg.name.split(' ')[0]}</span>
      <span class="badge-indicator ${dotClass}"></span>
    `;

    badge.addEventListener('click', (e) => {
      e.stopPropagation();
      window.dispatchEvent(new CustomEvent('agent-clicked', { detail: cfg }));
      this.focusOnAgent(cfg.id);
    });

    this.labelsContainer.appendChild(badge);
    return badge;
  }

  showSpeechBubble(agentId, text, type = 'working-chat') {
    const agent = this.agents[agentId];
    if (!agent) return;

    // Bersihkan bubble lama agen ini jika ada
    const existing = document.getElementById(`bubble-${agentId}`);
    if (existing && existing.parentNode) existing.parentNode.removeChild(existing);

    const bubble = document.createElement('div');
    bubble.id = `bubble-${agentId}`;
    bubble.className = `speech-bubble ${type}`;
    bubble.textContent = text;
    this.speechContainer.appendChild(bubble);

    setTimeout(() => {
      if (bubble.parentNode) bubble.parentNode.removeChild(bubble);
    }, 4500);

    bubble.agentRef = agent;
  }

  // ==========================================================================
  // SIGNAL BROADCAST FX & WORK CELEBRATION
  // ==========================================================================

  triggerSignalBroadcastAnimation(signalData) {
    const isBuy = signalData.action === 'BUY';
    const glowColor = isBuy ? 0x10b981 : 0xef4444;

    this.serverLight.color.setHex(glowColor);
    this.serverLight.intensity = 6;
    setTimeout(() => {
      this.serverLight.color.setHex(0x00f0ff);
      this.serverLight.intensity = 2.8;
    }, 1400);

    const serverOrigin = new THREE.Vector3(-12, 1.5, -6);

    for (let agentId in this.agents) {
      const agent = this.agents[agentId];
      if (agent.data.isMaster) continue;

      const targetPos = agent.basePos.clone().add(new THREE.Vector3(0, 1.4, 0));
      this.spawnSignalBeam(serverOrigin, targetPos, glowColor, () => {
        agent.screenMat.color.setHex(glowColor);
        setTimeout(() => {
          agent.screenMat.color.setHex(0xffffff);
        }, 1800);

        // Ubah state agent menjadi CELEBRATING & selebrasi kemenangan
        agent.workState = 'celebrating';
        agent.stateTimer = 0;
        agent.nextStateDuration = 3.5;

        const ticketNum = Math.floor(15248000000 + Math.random() * 99999);
        const lotStr = agent.data.lot;
        const bubbleMsg = `✅ #${ticketNum} ${signalData.action} ${lotStr} @ $${Number(signalData.entry).toFixed(2)}`;
        this.showSpeechBubble(agent.id, bubbleMsg, 'order-success');
      });
    }
  }

  spawnSignalBeam(start, end, colorHex, onArrival) {
    const points = [];
    const segments = 15;
    for (let i = 0; i <= segments; i++) {
      const t = i / segments;
      const p = new THREE.Vector3().lerpVectors(start, end, t);
      p.y += Math.sin(t * Math.PI) * 2.0;
      points.push(p);
    }

    const curve = new THREE.CatmullRomCurve3(points);
    const geom = new THREE.TubeGeometry(curve, 20, 0.09, 8, false);
    const mat = new THREE.MeshBasicMaterial({ color: colorHex, transparent: true, opacity: 0.95 });
    const mesh = new THREE.Mesh(geom, mat);
    this.scene.add(mesh);

    let progress = 0;
    const animateBeam = () => {
      progress += 0.08;
      mat.opacity = 1 - progress;
      if (progress >= 1) {
        this.scene.remove(mesh);
        geom.dispose();
        mat.dispose();
        if (onArrival) onArrival();
      } else {
        requestAnimationFrame(animateBeam);
      }
    };
    animateBeam();
  }

  // ==========================================================================
  // UPDATE TEXTURE LAYAR LAPTOP & MONITOR DINDING
  // ==========================================================================

  updateLaptopScreens(elapsedTime) {
    for (let id in this.agents) {
      const agent = this.agents[id];
      const lap = agent.laptop;
      if (!lap || !lap.ctx) continue;

      const ctx = lap.ctx;
      ctx.fillStyle = '#0a0f1d';
      ctx.fillRect(0, 0, 128, 80);

      // Mini Grid
      ctx.strokeStyle = '#1e293b';
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(0, 40); ctx.lineTo(128, 40);
      ctx.moveTo(64, 0); ctx.lineTo(64, 80);
      ctx.stroke();

      // Mini Candles bergerak
      const tSeed = elapsedTime * 4 + id.charCodeAt(0);
      for (let i = 0; i < 9; i++) {
        const x = 10 + i * 12;
        const isGreen = Math.sin(tSeed + i * 1.5) > 0;
        const h = 8 + Math.abs(Math.sin(tSeed * 0.8 + i) * 16);
        ctx.fillStyle = isGreen ? '#10b981' : '#ef4444';
        ctx.fillRect(x, 40 - h / 2, 7, h);
      }

      // Baris kode terminal berkedip di bagian bawah
      ctx.font = '8px monospace';
      ctx.fillStyle = '#38bdf8';
      const lineIdx = Math.floor(elapsedTime * 1.5) % lap.codeLines.length;
      ctx.fillText(`> ${lap.codeLines[lineIdx]}`, 8, 72);

      lap.texture.needsUpdate = true;
    }
  }

  updateWallDisplay(elapsedTime) {
    if (!this.wallCtx || (elapsedTime - this.wallLastUpdate < 0.2)) return;
    this.wallLastUpdate = elapsedTime;

    const ctx = this.wallCtx;
    ctx.fillStyle = '#070b14';
    ctx.fillRect(0, 0, 512, 280);

    // Grid halus
    ctx.strokeStyle = '#172554';
    ctx.lineWidth = 1;
    for (let x = 0; x < 512; x += 40) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, 280); ctx.stroke();
    }
    for (let y = 0; y < 280; y += 35) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(512, y); ctx.stroke();
    }

    // Top Header Banner
    ctx.fillStyle = '#0284c7';
    ctx.font = 'bold 14px sans-serif';
    ctx.fillText('XAUUSD M15 • MASTER STRATEGY 9 BUKU PDF', 20, 28);

    // Live Clock WIB
    const now = new Date();
    const timeStr = `${String(now.getHours()).padStart(2, '0')}:${String(now.getMinutes()).padStart(2, '0')}:${String(now.getSeconds()).padStart(2, '0')} WIB`;
    ctx.fillStyle = '#10b981';
    ctx.font = 'bold 14px monospace';
    ctx.fillText(`● LIVE ${timeStr}`, 360, 28);

    // Moving Average Curves (Yellow EMA 20 & Cyan EMA 50)
    ctx.strokeStyle = '#f59e0b';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let x = 20; x < 500; x += 15) {
      const y = 160 + Math.sin(x * 0.02 + elapsedTime * 1.5) * 25;
      if (x === 20) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    ctx.strokeStyle = '#00f0ff';
    ctx.lineWidth = 2;
    ctx.beginPath();
    for (let x = 20; x < 500; x += 15) {
      const y = 175 + Math.sin(x * 0.018 + elapsedTime * 1.2) * 22;
      if (x === 20) ctx.moveTo(x, y);
      else ctx.lineTo(x, y);
    }
    ctx.stroke();

    // Candlesticks
    for (let i = 0; i < 24; i++) {
      const cx = 30 + i * 19;
      const isGreen = Math.sin(i * 1.7 + elapsedTime * 0.6) > -0.2;
      const h = 14 + Math.abs(Math.sin(i * 2.3 + elapsedTime) * 45);
      const cy = 150 + Math.sin(i * 0.2 + elapsedTime * 0.5) * 30;

      ctx.fillStyle = isGreen ? '#10b981' : '#ef4444';
      ctx.strokeStyle = isGreen ? '#10b981' : '#ef4444';
      ctx.beginPath();
      ctx.moveTo(cx + 4, cy - h / 2 - 8);
      ctx.lineTo(cx + 4, cy + h / 2 + 8);
      ctx.stroke();

      ctx.fillRect(cx, cy - h / 2, 8, h);
    }

    // Floating Current Price Tag di ujung kanan
    const pulseY = 140 + Math.sin(elapsedTime * 2) * 10;
    ctx.fillStyle = '#10b981';
    ctx.fillRect(430, pulseY - 14, 75, 24);
    ctx.fillStyle = '#070b14';
    ctx.font = 'bold 12px monospace';
    ctx.fillText('$4,185.80', 435, pulseY + 2);

    this.wallTexture.needsUpdate = true;
  }

  // ==========================================================================
  // STATE MACHINE & ANIMASI KERJA REALISTIS (TYPING, SIPPING, CONSULTING)
  // ==========================================================================

  updateAgentWorkAnimations(delta, elapsedTime) {
    for (let id in this.agents) {
      const a = this.agents[id];
      a.stateTimer += delta;

      // 1. Transisi State Otomatis jika durasi habis
      if (a.stateTimer >= a.nextStateDuration && a.workState !== 'celebrating') {
        a.stateTimer = 0;
        const roll = Math.random();
        if (roll < 0.45) {
          a.workState = 'typing';
          a.nextStateDuration = 4 + Math.random() * 6;
          a.isTypingFast = Math.random() > 0.6;
        } else if (roll < 0.70) {
          a.workState = 'reading_chart';
          a.nextStateDuration = 5 + Math.random() * 5;
        } else if (roll < 0.85) {
          a.workState = 'sipping_coffee';
          a.nextStateDuration = 3.5;
        } else {
          a.workState = 'consulting';
          a.nextStateDuration = 4 + Math.random() * 4;
        }
      }

      // 2. Eksekusi Animasi Berdasarkan State
      const t = elapsedTime + (id.charCodeAt(0) % 10);

      // --- STATE: TYPING BURST (Mengetik Cepat) ---
      if (a.workState === 'typing') {
        const speed = a.isTypingFast ? 26 : 14;
        
        // Tubuh membungkuk fokus ke laptop
        a.torsoGroup.rotation.x = THREE.MathUtils.lerp(a.torsoGroup.rotation.x, 0.12, 0.1);
        a.chairSwivel.rotation.y = THREE.MathUtils.lerp(a.chairSwivel.rotation.y, 0, 0.1);

        // Kedua pundak mengarah ke keyboard
        a.shoulderLeft.rotation.x = -0.55 + Math.sin(t * speed) * 0.08;
        a.shoulderLeft.rotation.z = -0.15;
        a.elbowLeft.rotation.x = 0.4 + Math.cos(t * speed) * 0.12;

        a.shoulderRight.rotation.x = -0.55 + Math.cos(t * speed) * 0.08;
        a.shoulderRight.rotation.z = 0.15;
        a.elbowRight.rotation.x = 0.4 + Math.sin(t * speed) * 0.12;

        // Kepala sedikit mengangguk fokus ke layar
        a.headGroup.rotation.x = 0.18 + Math.sin(t * 4) * 0.03;
        a.headGroup.rotation.y = Math.sin(t * 1.5) * 0.06;

        // Posisi cangkir di meja
        a.mug.position.set(0.75, 1.3, -0.35);
      }

      // --- STATE: READING CHART (Menganalisis Grafik & Mengamati Dinding) ---
      else if (a.workState === 'reading_chart') {
        // Bersandar santai di kursi ergonomis
        a.torsoGroup.rotation.x = THREE.MathUtils.lerp(a.torsoGroup.rotation.x, -0.09, 0.05);

        // Tangan kiri istirahat di paha/meja
        a.shoulderLeft.rotation.x = -0.3;
        a.shoulderLeft.rotation.z = -0.25;
        a.elbowLeft.rotation.x = 0.2;

        // Tangan kanan gerak halus menggerakkan mouse komputer
        a.shoulderRight.rotation.x = -0.45;
        a.shoulderRight.rotation.z = 0.25;
        a.elbowRight.rotation.x = 0.35;
        a.mouseMesh.position.x = 0.6 + Math.sin(t * 1.2) * 0.03;

        // Kepala menoleh ke arah monitor besar di dinding
        a.headGroup.rotation.x = -0.15 + Math.sin(t * 0.8) * 0.05;
        a.headGroup.rotation.y = Math.sin(t * 0.6) * 0.35;

        a.mug.position.set(0.75, 1.3, -0.35);
      }

      // --- STATE: SIPPING COFFEE (Meminum Kopi) ---
      else if (a.workState === 'sipping_coffee') {
        // Tangan kanan mengangkat cangkir kopi ke mulut
        a.torsoGroup.rotation.x = THREE.MathUtils.lerp(a.torsoGroup.rotation.x, -0.05, 0.08);

        a.shoulderRight.rotation.x = THREE.MathUtils.lerp(a.shoulderRight.rotation.x, -1.45, 0.1);
        a.shoulderRight.rotation.z = THREE.MathUtils.lerp(a.shoulderRight.rotation.z, -0.35, 0.1);
        a.elbowRight.rotation.x = THREE.MathUtils.lerp(a.elbowRight.rotation.x, 1.1, 0.1);

        // Kepala sedikit mendongak saat minum
        a.headGroup.rotation.x = -0.12;
        a.headGroup.rotation.y = 0.05;

        // Cangkir kopi terangkat mengikuti tangan
        a.mug.position.set(0.25, 1.85, 0.35);

        // Tangan kiri rileks
        a.shoulderLeft.rotation.x = -0.3;
      }

      // --- STATE: CONSULTING (Menoleh & Diskusi dengan Rekan Kerja) ---
      else if (a.workState === 'consulting') {
        const swivelDir = id === 'deden' || id === 'allan' ? 0.45 : -0.45;
        a.chairSwivel.rotation.y = THREE.MathUtils.lerp(a.chairSwivel.rotation.y, swivelDir, 0.08);

        // Kepala menoleh ke arah rekan
        a.headGroup.rotation.y = swivelDir * 0.8 + Math.sin(t * 3) * 0.08;
        a.headGroup.rotation.x = Math.sin(t * 2) * 0.05;

        // Tangan kiri berbicara / gesture
        a.shoulderLeft.rotation.x = -0.7 + Math.sin(t * 3) * 0.15;
        a.shoulderRight.rotation.x = -0.4;

        a.mug.position.set(0.75, 1.3, -0.35);
      }

      // --- STATE: CELEBRATING (Selebrasi Take Profit / Profit Hit!) ---
      else if (a.workState === 'celebrating') {
        // Kedua tangan terangkat ke atas victory pose \o/
        a.shoulderLeft.rotation.x = -2.5;
        a.shoulderLeft.rotation.z = -0.35;
        a.shoulderRight.rotation.x = -2.5;
        a.shoulderRight.rotation.z = 0.35;

        // Tubuh melonjak gembira
        a.torsoGroup.position.y = 0.95 + Math.abs(Math.sin(t * 12)) * 0.12;
        a.headGroup.rotation.x = -0.2;

        if (a.stateTimer >= a.nextStateDuration) {
          a.workState = 'typing';
          a.torsoGroup.position.y = 0.95;
        }
      }

      // 3. Proyeksi Label 2D di Layar HTML
      a.group.getWorldPosition(a.headWorldPos);
      a.headWorldPos.y += 2.65;
      this.update2DProjection(a.headWorldPos, a.labelEl);
    }
  }

  // ==========================================================================
  // AUTONOMOUS TRADER DIALOGUE SYSTEM (SPEECH BUBBLES BERKALA)
  // ==========================================================================

  updateOfficeDialogues(elapsedTime) {
    if (elapsedTime - this.lastDialogueTime > this.dialogueInterval) {
      this.lastDialogueTime = elapsedTime;

      // Pilih agen acak
      const agentKeys = Object.keys(this.agents);
      const randomId = agentKeys[Math.floor(Math.random() * agentKeys.length)];
      const agent = this.agents[randomId];

      if (agent && agent.data.dialogues && agent.data.dialogues.length > 0) {
        const dList = agent.data.dialogues;
        const text = dList[Math.floor(Math.random() * dList.length)];
        const chatType = agent.workState === 'sipping_coffee' ? 'coffee-chat' : 'working-chat';
        this.showSpeechBubble(randomId, text, chatType);
      }
    }
  }

  // ==========================================================================
  // DATA PACKET PARTICLES (VPS TO AGENTS)
  // ==========================================================================

  updateDataPackets() {
    const agentKeys = Object.keys(this.agents);
    if (agentKeys.length === 0) return;

    for (let dp of this.dataPackets) {
      dp.progress += dp.speed;
      if (dp.progress >= 1) {
        dp.progress = 0;
        dp.targetIndex = Math.floor(Math.random() * agentKeys.length);
      }

      const targetAgentId = agentKeys[dp.targetIndex];
      const targetAgent = this.agents[targetAgentId];
      if (!targetAgent) continue;

      const targetPos = targetAgent.basePos.clone().add(new THREE.Vector3(0, 0.7, 0));
      const pos = new THREE.Vector3().lerpVectors(dp.start, targetPos, dp.progress);
      pos.y += Math.sin(dp.progress * Math.PI) * 0.8; // Melengkung sedikit di atas lantai

      dp.mesh.position.copy(pos);
    }
  }

  // ==========================================================================
  // CAMERA & INTERACTION
  // ==========================================================================

  focusOnAgent(agentId) {
    const agent = this.agents[agentId];
    if (!agent) return;
    const targetPos = agent.basePos.clone();
    this.cameraTarget.copy(targetPos);
    this.cameraDesiredPos.set(targetPos.x + 9, targetPos.y + 9, targetPos.z + 9);
  }

  setCameraMode(mode) {
    if (mode === 'iso') {
      this.cameraTarget.set(0, 0, 0);
      this.cameraDesiredPos.set(36, 30, 36);
    } else if (mode === 'deden') {
      this.focusOnAgent('deden');
    } else if (mode === 'server') {
      this.cameraTarget.set(-13, 2, -9);
      this.cameraDesiredPos.set(-2, 10, 2);
    } else if (mode === 'top') {
      this.cameraTarget.set(0, 0, 0);
      this.cameraDesiredPos.set(0.1, 44, 0.1);
    }
  }

  toggleTheme() {
    this.isNight = !this.isNight;
    const bg = this.isNight ? 0x070b14 : 0xccd6e0;
    this.scene.background.setHex(bg);
    this.scene.fog.color.setHex(bg);
    this.ambientLight.intensity = this.isNight ? 0.75 : 1.15;
    this.dirLight.intensity = this.isNight ? 1.25 : 1.6;
    return this.isNight;
  }

  onCanvasClick(e) {
    const rect = this.canvas.getBoundingClientRect();
    this.mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this.mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    this.raycaster.setFromCamera(this.mouse, this.camera);
    
    for (let agentId in this.agents) {
      const agent = this.agents[agentId];
      const intersects = this.raycaster.intersectObjects(agent.group.children, true);
      if (intersects.length > 0) {
        window.dispatchEvent(new CustomEvent('agent-clicked', { detail: agent.data }));
        this.focusOnAgent(agentId);
        break;
      }
    }
  }

  onResize() {
    if (!this.canvas) return;
    const width = this.canvas.clientWidth || 800;
    const height = this.canvas.clientHeight || 600;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  update2DProjection(worldPos, domElement) {
    if (!domElement) return;
    const screenPos = worldPos.clone().project(this.camera);
    const widthHalf = (this.canvas.clientWidth || 800) / 2;
    const heightHalf = (this.canvas.clientHeight || 600) / 2;

    const x = (screenPos.x * widthHalf) + widthHalf;
    const y = -(screenPos.y * heightHalf) + heightHalf;

    if (screenPos.z > 1) {
      domElement.style.display = 'none';
    } else {
      domElement.style.display = 'flex';
      domElement.style.left = `${x}px`;
      domElement.style.top = `${y}px`;
    }
  }

  // ==========================================================================
  // MASTER ANIMATION LOOP
  // ==========================================================================

  animate() {
    requestAnimationFrame(() => this.animate());

    const delta = this.clock.getDelta();
    const elapsedTime = this.clock.getElapsedTime();

    // 1. Smooth Camera Controls
    this.camera.position.lerp(this.cameraDesiredPos, 0.05);
    this.controls.target.lerp(this.cameraTarget, 0.05);
    this.controls.update();

    // 2. Server LEDs Blinking
    for (let led of this.blinkingLeds) {
      if (elapsedTime - led.lastToggle > led.interval) {
        led.lastToggle = elapsedTime;
        const isOn = led.mesh.material.color.getHex() !== 0x000000;
        led.mesh.material.color.setHex(isOn ? 0x111111 : led.origColor);
      }
    }

    // 3. Update Layar Laptop & Monitor Dinding Dinamis
    this.updateLaptopScreens(elapsedTime);
    this.updateWallDisplay(elapsedTime);

    // 4. Update Animasi Kerja Karakter (Mengetik, Minum Kopi, Diskusi)
    this.updateAgentWorkAnimations(delta, elapsedTime);

    // 5. Update Partikel Aliran Data VPS
    this.updateDataPackets();

    // 6. Speech Bubbles Dialog Mandiri
    this.updateOfficeDialogues(elapsedTime);

    // 7. Update Posisi Speech Bubbles
    const bubbles = this.speechContainer.getElementsByClassName('speech-bubble');
    for (let bubble of bubbles) {
      if (bubble.agentRef) {
        const pos = bubble.agentRef.headWorldPos.clone();
        pos.y += 0.85;
        this.update2DProjection(pos, bubble);
      }
    }

    // 8. Render
    this.renderer.render(this.scene, this.camera);
  }
}

window.Office3D = Office3D;
