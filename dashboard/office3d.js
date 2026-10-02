/**
 * BOTRADING 3D ISOMETRIC TRADING OFFICE
 * Three.js Isometric Low-Poly Office Floor Plan
 * Faithful reproduction of the virtual office environment
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

    this.agents = {}; // Map of agentId -> { group, mesh, data, labelEl, typingTimer, screenMat }
    this.desks = [];
    this.particles = [];
    this.blinkingLeds = [];
    this.signalBeams = [];

    this.isNight = true;
    this.cameraTarget = new THREE.Vector3(0, 0, 0);
    this.cameraDesiredPos = new THREE.Vector3(36, 30, 36);

    this.clock = new THREE.Clock();

    this.init();
  }

  init() {
    // 1. Scene
    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(this.isNight ? 0x090d16 : 0xccd6e0);
    this.scene.fog = new THREE.FogExp2(this.isNight ? 0x090d16 : 0xccd6e0, 0.008);

    // 2. Camera (Isometric Low FOV)
    const aspect = this.canvas.clientWidth / this.canvas.clientHeight;
    this.camera = new THREE.PerspectiveCamera(34, aspect, 0.5, 500);
    this.camera.position.set(36, 30, 36);
    this.camera.lookAt(0, 0, 0);

    // 3. Renderer
    this.renderer = new THREE.WebGLRenderer({
      canvas: this.canvas,
      antialias: true,
      powerPreference: "high-performance"
    });
    this.renderer.setSize(this.canvas.clientWidth, this.canvas.clientHeight);
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;

    // 4. Orbit Controls
    this.controls = new THREE.OrbitControls(this.camera, this.renderer.domElement);
    this.controls.enableDamping = true;
    this.controls.dampingFactor = 0.05;
    this.controls.maxPolarAngle = Math.PI / 2.15; // Mencegah kamera tembus ke bawah lantai
    this.controls.minDistance = 15;
    this.controls.maxDistance = 85;
    this.controls.target.set(0, 1, 0);

    // 5. Lighting
    this.setupLighting();

    // 6. Build Office Geometry (Floor, Walls, Server Room, Furniture)
    this.buildOfficeEnvironment();

    // 7. Spawn Characters / Traders
    this.spawnAgents();

    // 8. Event Listeners
    window.addEventListener('resize', () => this.onResize());
    this.canvas.addEventListener('click', (e) => this.onCanvasClick(e));
    this.canvas.addEventListener('mousemove', (e) => this.onMouseMove(e));

    // 9. Start Render Loop
    this.animate();
  }

  setupLighting() {
    this.ambientLight = new THREE.AmbientLight(0xffffff, this.isNight ? 0.7 : 1.1);
    this.scene.add(this.ambientLight);

    // Main Directional Sunlight / Office Lighting
    this.dirLight = new THREE.DirectionalLight(0xfffaed, this.isNight ? 1.2 : 1.6);
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

    // Server Room Blue/Cyan Glow Point Light
    this.serverLight = new THREE.PointLight(0x00f0ff, 2.5, 18);
    this.serverLight.position.set(-11, 4, -9);
    this.scene.add(this.serverLight);

    // Office Warm Ceiling Accents
    const ceilingWarm1 = new THREE.PointLight(0xffeedd, 0.8, 25);
    ceilingWarm1.position.set(5, 8, 5);
    this.scene.add(ceilingWarm1);

    const ceilingWarm2 = new THREE.PointLight(0xffeedd, 0.8, 25);
    ceilingWarm2.position.set(-5, 8, 5);
    this.scene.add(ceilingWarm2);
  }

  buildOfficeEnvironment() {
    // === LANTAI UTAMA (Warm Beige Tiles seperti di Gambar 2) ===
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

    // Grid garis ubin lantai halus
    const tileGrid = new THREE.GridHelper(38, 38, 0xdfd4c2, 0xe4dac9);
    tileGrid.position.set(0, 0.01, 0);
    this.scene.add(tileGrid);

    // === DINDING LUAR (Outer Perimeter Walls) ===
    const wallMat = new THREE.MeshStandardMaterial({
      color: 0xdedede,
      roughness: 0.6
    });
    const wallTrimMat = new THREE.MeshStandardMaterial({
      color: 0x9ca3af,
      roughness: 0.4
    });

    // Dinding Belakang Kiri (Z = -13)
    const backWallZGeo = new THREE.BoxGeometry(38, 6, 0.6);
    const backWallZ = new THREE.Mesh(backWallZGeo, wallMat);
    backWallZ.position.set(0, 3, -13);
    backWallZ.castShadow = true;
    backWallZ.receiveShadow = true;
    this.scene.add(backWallZ);

    // Dinding Belakang Kanan (X = -19)
    const backWallXGeo = new THREE.BoxGeometry(0.6, 6, 26);
    const backWallX = new THREE.Mesh(backWallXGeo, wallMat);
    backWallX.position.set(-19, 3, 0);
    backWallX.castShadow = true;
    backWallX.receiveShadow = true;
    this.scene.add(backWallX);

    // Dinding Rendah / Cut-away Depan (Persis Gambar 2 agar tidak menghalangi pandangan)
    const lowWallFrontGeo = new THREE.BoxGeometry(38, 0.8, 0.6);
    const lowWallFront = new THREE.Mesh(lowWallFrontGeo, wallTrimMat);
    lowWallFront.position.set(0, 0.4, 13);
    lowWallFront.receiveShadow = true;
    this.scene.add(lowWallFront);

    const lowWallRightGeo = new THREE.BoxGeometry(0.6, 0.8, 26);
    const lowWallRight = new THREE.Mesh(lowWallRightGeo, wallTrimMat);
    lowWallRight.position.set(19, 0.4, 0);
    lowWallRight.receiveShadow = true;
    this.scene.add(lowWallRight);

    // === RUANG SERVER / MASTER VPS ROOM (Kiri Atas) ===
    this.buildServerRoom();

    // === RUANG RAPAT / CONFERENCE AREA (Round Table) ===
    this.buildConferenceArea();

    // === MEJA EKSEKUTIF / L-SHAPED DESK & BOOKSHELF ===
    this.buildExecutiveDesk();

    // === LOUNGE / BREAK AREA (Sofas & Ping Pong Table) ===
    this.buildLoungeArea();

    // === AKSESORI KANTOR (Potted Plants, Wall Monitor Chart) ===
    this.buildOfficeDecorations();
  }

  buildServerRoom() {
    const serverWallMat = new THREE.MeshStandardMaterial({ color: 0x334155, roughness: 0.5 });
    
    // Dinding partisi server room (Z divider)
    const partZGeo = new THREE.BoxGeometry(8, 5, 0.4);
    const partZ = new THREE.Mesh(partZGeo, serverWallMat);
    partZ.position.set(-15, 2.5, -5);
    partZ.castShadow = true;
    this.scene.add(partZ);

    // Dinding partisi server room (X divider dengan pintu terbuka)
    const partXGeo = new THREE.BoxGeometry(0.4, 5, 5);
    const partX = new THREE.Mesh(partXGeo, serverWallMat);
    partX.position.set(-11, 2.5, -10.5);
    partX.castShadow = true;
    this.scene.add(partX);

    // Lantai metalik gelap server room
    const serverFloorGeo = new THREE.BoxGeometry(8, 0.05, 8);
    const serverFloorMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.2, metalness: 0.6 });
    const sFloor = new THREE.Mesh(serverFloorGeo, serverFloorMat);
    sFloor.position.set(-15, 0.02, -9);
    this.scene.add(sFloor);

    // 2 RAK SERVER BESAR (VPS Master Bot & Database Gateway)
    for (let i = 0; i < 2; i++) {
      const rackGroup = new THREE.Group();
      
      // Bodi Rack Hitam
      const rackGeo = new THREE.BoxGeometry(2, 4.2, 1.6);
      const rackMat = new THREE.MeshStandardMaterial({ color: 0x111827, roughness: 0.3, metalness: 0.8 });
      const rack = new THREE.Mesh(rackGeo, rackMat);
      rack.position.y = 2.1;
      rack.castShadow = true;
      rackGroup.add(rack);

      // Panel Kaca Depan dengan Kisi Server
      const glassGeo = new THREE.BoxGeometry(1.8, 3.8, 0.1);
      const glassMat = new THREE.MeshStandardMaterial({
        color: 0x0f172a,
        roughness: 0.1,
        metalness: 0.9,
        transparent: true,
        opacity: 0.85
      });
      const glass = new THREE.Mesh(glassGeo, glassMat);
      glass.position.set(0, 2.1, 0.85);
      rackGroup.add(glass);

      // Lampu LED Server Berkedip (Blinking LEDs)
      for (let r = 0; r < 7; r++) {
        for (let c = 0; c < 3; c++) {
          const ledGeo = new THREE.BoxGeometry(0.12, 0.08, 0.05);
          const ledColor = (r % 3 === 0) ? 0x00f0ff : (r % 3 === 1) ? 0x10b981 : 0xf59e0b;
          const ledMat = new THREE.MeshBasicMaterial({ color: ledColor });
          const led = new THREE.Mesh(ledGeo, ledMat);
          led.position.set(-0.6 + c * 0.6, 0.8 + r * 0.45, 0.9);
          rackGroup.add(led);

          this.blinkingLeds.push({
            mesh: led,
            origColor: ledColor,
            interval: 0.2 + Math.random() * 0.6,
            lastToggle: 0
          });
        }
      }

      rackGroup.position.set(-16.5 + i * 2.8, 0, -9.5);
      this.scene.add(rackGroup);
    }
  }

  buildConferenceArea() {
    // Meja Bundar Besar Rapat (Kiri Tengah)
    const confGroup = new THREE.Group();
    const tableTopGeo = new THREE.CylinderGeometry(3.2, 3.2, 0.2, 32);
    const woodMat = new THREE.MeshStandardMaterial({ color: 0x926644, roughness: 0.4 });
    const tableTop = new THREE.Mesh(tableTopGeo, woodMat);
    tableTop.position.y = 1.3;
    tableTop.castShadow = true;
    tableTop.receiveShadow = true;
    confGroup.add(tableTop);

    // Kaki meja bundar
    const legGeo = new THREE.CylinderGeometry(0.5, 0.8, 1.3, 16);
    const legMat = new THREE.MeshStandardMaterial({ color: 0x333333, metalness: 0.7 });
    const leg = new THREE.Mesh(legGeo, legMat);
    leg.position.y = 0.65;
    confGroup.add(leg);

    // 5 Kursi Putar di sekeliling meja rapat
    for (let a = 0; a < 5; a++) {
      const angle = (a / 5) * Math.PI * 2;
      const chair = this.createOfficeChair(0x374151);
      chair.position.set(Math.cos(angle) * 4.2, 0, Math.sin(angle) * 4.2);
      chair.rotation.y = -angle - Math.PI / 2;
      confGroup.add(chair);
    }

    confGroup.position.set(-6, 0, -8);
    this.scene.add(confGroup);

    // Meja Bundar Kecil Diskusi (Kanan Depan)
    const smallTable = new THREE.Group();
    const sTopGeo = new THREE.CylinderGeometry(2, 2, 0.15, 24);
    const sTop = new THREE.Mesh(sTopGeo, woodMat);
    sTop.position.y = 1.2;
    sTop.castShadow = true;
    smallTable.add(sTop);

    const sLeg = new THREE.Mesh(new THREE.CylinderGeometry(0.3, 0.5, 1.2, 16), legMat);
    sLeg.position.y = 0.6;
    smallTable.add(sLeg);

    const chair1 = this.createOfficeChair(0x1e293b);
    chair1.position.set(2.5, 0, 0);
    chair1.rotation.y = -Math.PI / 2;
    smallTable.add(chair1);

    const chair2 = this.createOfficeChair(0x1e293b);
    chair2.position.set(-2.5, 0, 0);
    chair2.rotation.y = Math.PI / 2;
    smallTable.add(chair2);

    smallTable.position.set(13, 0, 4);
    this.scene.add(smallTable);
  }

  buildExecutiveDesk() {
    const execGroup = new THREE.Group();
    const darkWoodMat = new THREE.MeshStandardMaterial({ color: 0x6e4726, roughness: 0.4 });

    // Meja L-Shaped
    const mainDeskGeo = new THREE.BoxGeometry(4.5, 1.3, 1.8);
    const mainDesk = new THREE.Mesh(mainDeskGeo, darkWoodMat);
    mainDesk.position.set(0, 0.65, 0);
    mainDesk.castShadow = true;
    execGroup.add(mainDesk);

    const sideDeskGeo = new THREE.BoxGeometry(1.8, 1.3, 2.8);
    const sideDesk = new THREE.Mesh(sideDeskGeo, darkWoodMat);
    sideDesk.position.set(1.8, 0.65, 1.4);
    sideDesk.castShadow = true;
    execGroup.add(sideDesk);

    // Kursi Direktur
    const bossChair = this.createOfficeChair(0x111827, true);
    bossChair.position.set(0, 0, -1.6);
    execGroup.add(bossChair);

    // Rak Buku / Lemari File di belakang meja
    const shelfGeo = new THREE.BoxGeometry(5.5, 4.5, 1.2);
    const shelf = new THREE.Mesh(shelfGeo, darkWoodMat);
    shelf.position.set(0, 2.25, -4);
    shelf.castShadow = true;
    execGroup.add(shelf);

    // Laptop & Aksesori Meja Bos
    const laptop = this.createLaptop(0x00f0ff);
    laptop.position.set(-0.6, 1.35, 0);
    execGroup.add(laptop);

    execGroup.position.set(5, 0, -7.5);
    this.scene.add(execGroup);
  }

  buildLoungeArea() {
    const loungeGroup = new THREE.Group();

    // 1. Sofa Panjang Biru (3-Seater)
    const sofaBlueMat = new THREE.MeshStandardMaterial({ color: 0x2563eb, roughness: 0.6 });
    const sofaBase = new THREE.Mesh(new THREE.BoxGeometry(4.2, 0.6, 1.6), sofaBlueMat);
    sofaBase.position.set(0, 0.3, 0);
    sofaBase.castShadow = true;
    loungeGroup.add(sofaBase);

    const sofaBack = new THREE.Mesh(new THREE.BoxGeometry(4.2, 1.1, 0.5), sofaBlueMat);
    sofaBack.position.set(0, 0.85, 0.6);
    sofaBack.castShadow = true;
    loungeGroup.add(sofaBack);

    // 2. Sofa Ungu / Navy Kecil (2-Seater)
    const sofaPurpleMat = new THREE.MeshStandardMaterial({ color: 0x4f46e5, roughness: 0.6 });
    const s2Base = new THREE.Mesh(new THREE.BoxGeometry(2.8, 0.6, 1.5), sofaPurpleMat);
    s2Base.position.set(-1, 0.3, -4.5);
    s2Base.castShadow = true;
    loungeGroup.add(s2Base);

    const s2Back = new THREE.Mesh(new THREE.BoxGeometry(2.8, 1.1, 0.4), sofaPurpleMat);
    s2Back.position.set(-1, 0.85, -4.5 + 0.6);
    s2Back.castShadow = true;
    loungeGroup.add(s2Back);

    // 3. Kursi Armchair Orange
    const orangeMat = new THREE.MeshStandardMaterial({ color: 0xea580c, roughness: 0.6 });
    const armChair = new THREE.Mesh(new THREE.BoxGeometry(1.6, 0.6, 1.5), orangeMat);
    armChair.position.set(3.2, 0.3, -1.8);
    armChair.castShadow = true;
    loungeGroup.add(armChair);

    // 4. Meja Kopi Rendah
    const coffeeTable = new THREE.Mesh(
      new THREE.BoxGeometry(2.4, 0.4, 1.2),
      new THREE.MeshStandardMaterial({ color: 0x38bdf8, roughness: 0.2, transparent: true, opacity: 0.7 })
    );
    coffeeTable.position.set(0.8, 0.2, -1.6);
    loungeGroup.add(coffeeTable);

    // 5. MEJA PING PONG (Table Tennis Hijau seperti di Gambar 2)
    const pingPongGroup = new THREE.Group();
    // Meja Hijau
    const tableGeo = new THREE.BoxGeometry(4.8, 0.15, 2.6);
    const tableMat = new THREE.MeshStandardMaterial({ color: 0x15803d, roughness: 0.3 });
    const pTable = new THREE.Mesh(tableGeo, tableMat);
    pTable.position.y = 1.2;
    pTable.castShadow = true;
    pingPongGroup.add(pTable);

    // Garis Putih Ping Pong
    const lineMat = new THREE.MeshBasicMaterial({ color: 0xffffff });
    const centerLine = new THREE.Mesh(new THREE.BoxGeometry(4.8, 0.16, 0.04), lineMat);
    centerLine.position.y = 1.21;
    pingPongGroup.add(centerLine);

    // Jaring Net Putih
    const netGeo = new THREE.BoxGeometry(0.04, 0.4, 2.8);
    const netMat = new THREE.MeshStandardMaterial({ color: 0xffffff, transparent: true, opacity: 0.85 });
    const net = new THREE.Mesh(netGeo, netMat);
    net.position.y = 1.45;
    pingPongGroup.add(net);

    // Kaki meja ping pong
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
    // 1. Layar TV Monitor Dinding Besar (Grafik Trading Candlestick)
    const tvGroup = new THREE.Group();
    const frameGeo = new THREE.BoxGeometry(5.5, 3.2, 0.2);
    const frameMat = new THREE.MeshStandardMaterial({ color: 0x111827 });
    const frame = new THREE.Mesh(frameGeo, frameMat);
    tvGroup.add(frame);

    // Layar Chart Candlestick Berpendar
    const screenGeo = new THREE.PlaneGeometry(5.2, 2.9);
    const chartTex = this.generateCandlestickCanvasTexture();
    const screenMat = new THREE.MeshBasicMaterial({ map: chartTex });
    const screen = new THREE.Mesh(screenGeo, screenMat);
    screen.position.z = 0.11;
    tvGroup.add(screen);

    tvGroup.position.set(11, 4, -12.8);
    this.scene.add(tvGroup);

    // 2. Tanaman Hias Hijau dalam Pot (Potted Plants)
    const plantCoords = [
      [-17, -3],
      [-8, -12.5],
      [17, -12.5],
      [17, 11],
      [-5, 11]
    ];
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

    // Dudukan
    const seatGeo = new THREE.BoxGeometry(0.9, 0.12, 0.9);
    const seat = new THREE.Mesh(seatGeo, cushionMat);
    seat.position.y = 0.75;
    seat.castShadow = true;
    chairGroup.add(seat);

    // Sandaran punggung
    const backHeight = isHighBack ? 1.4 : 0.9;
    const backGeo = new THREE.BoxGeometry(0.85, backHeight, 0.12);
    const back = new THREE.Mesh(backGeo, cushionMat);
    back.position.set(0, 0.75 + backHeight / 2, -0.42);
    back.castShadow = true;
    chairGroup.add(back);

    // Kaki tiang & roda
    const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.08, 0.08, 0.75, 12), metalMat);
    stem.position.y = 0.375;
    chairGroup.add(stem);

    const baseStar = new THREE.Mesh(new THREE.CylinderGeometry(0.45, 0.45, 0.06, 5), metalMat);
    baseStar.position.y = 0.06;
    chairGroup.add(baseStar);

    return chairGroup;
  }

  createLaptop(screenColor = 0x00f0ff) {
    const lapGroup = new THREE.Group();
    const bodyMat = new THREE.MeshStandardMaterial({ color: 0x94a3b8, metalness: 0.7, roughness: 0.3 });

    // Keyboard Base
    const base = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.04, 0.55), bodyMat);
    base.castShadow = true;
    lapGroup.add(base);

    // Monitor Layar Miring
    const lidGroup = new THREE.Group();
    const lid = new THREE.Mesh(new THREE.BoxGeometry(0.8, 0.55, 0.03), bodyMat);
    lid.position.set(0, 0.27, 0);
    lidGroup.add(lid);

    // Layar Berpendar Glow
    const screenMat = new THREE.MeshBasicMaterial({ color: screenColor });
    const screen = new THREE.Mesh(new THREE.PlaneGeometry(0.74, 0.48), screenMat);
    screen.position.set(0, 0.27, 0.02);
    lidGroup.add(screen);

    lidGroup.position.set(0, 0.02, -0.27);
    lidGroup.rotation.x = 0.25; // Sudut buka laptop
    lapGroup.add(lidGroup);

    lapGroup.screenMat = screenMat;
    return lapGroup;
  }

  createPottedPlant() {
    const plantGroup = new THREE.Group();
    // Pot Putih Keramik
    const potGeo = new THREE.CylinderGeometry(0.4, 0.3, 0.7, 16);
    const potMat = new THREE.MeshStandardMaterial({ color: 0xf8fafc, roughness: 0.3 });
    const pot = new THREE.Mesh(potGeo, potMat);
    pot.position.y = 0.35;
    pot.castShadow = true;
    plantGroup.add(pot);

    // Daun Hijau Rimbun (Spheres)
    const leafMat = new THREE.MeshStandardMaterial({ color: 0x16a34a, roughness: 0.5 });
    for (let i = 0; i < 5; i++) {
      const leaf = new THREE.Mesh(new THREE.DodecahedronGeometry(0.35 + Math.random() * 0.15), leafMat);
      leaf.position.set(
        (Math.random() - 0.5) * 0.4,
        0.8 + Math.random() * 0.5,
        (Math.random() - 0.5) * 0.4
      );
      leaf.castShadow = true;
      plantGroup.add(leaf);
    }
    return plantGroup;
  }

  generateCandlestickCanvasTexture() {
    const canvas = document.createElement('canvas');
    canvas.width = 512;
    canvas.height = 280;
    const ctx = canvas.getContext('2d');

    // Background chart gelap
    ctx.fillStyle = '#0f172a';
    ctx.fillRect(0, 0, 512, 280);

    // Grid garis halus
    ctx.strokeStyle = '#1e293b';
    ctx.lineWidth = 1;
    for (let x = 0; x < 512; x += 40) {
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, 280);
      ctx.stroke();
    }
    for (let y = 0; y < 280; y += 35) {
      ctx.beginPath();
      ctx.moveTo(0, y);
      ctx.lineTo(512, y);
      ctx.stroke();
    }

    // Gambar Candlestick Hijau & Merah (XAUUSD Trend Naik)
    const candles = 28;
    let price = 140;
    for (let i = 0; i < candles; i++) {
      const cx = 20 + i * 17;
      const isGreen = Math.random() > 0.38;
      const change = (Math.random() * 24 - 8);
      const open = price;
      const close = Math.max(20, Math.min(260, open + change));
      const high = Math.min(270, Math.max(open, close) + Math.random() * 12);
      const low = Math.max(10, Math.min(open, close) - Math.random() * 12);

      ctx.strokeStyle = isGreen ? '#10b981' : '#ef4444';
      ctx.fillStyle = isGreen ? '#10b981' : '#ef4444';

      // Sumbu
      ctx.beginPath();
      ctx.moveTo(cx, high);
      ctx.lineTo(cx, low);
      ctx.stroke();

      // Bodi
      const topY = Math.min(open, close);
      const h = Math.max(3, Math.abs(open - close));
      ctx.fillRect(cx - 5, topY, 10, h);

      price = close;
    }

    // Judul Chart
    ctx.font = 'bold 16px monospace';
    ctx.fillStyle = '#f59e0b';
    ctx.fillText('XAUUSD M1 • MASTER SIGNAL ENGINE (9 BUKU PDF)', 20, 30);

    return new THREE.CanvasTexture(canvas);
  }

  // ==========================================================================
  // SPAWN AGENT CHARACTERS & DESKS (Seperti di Gambar 2)
  // ==========================================================================

  spawnAgents() {
    // Definisi anggota trading floor sesuai Gambar 2 & User Request:
    // Master di VPS / Server Desk, Deden di Meja Depan (Lokal MT5), Cory, Luke, Ben, Allan, Susie, Andrew
    const agentConfigs = [
      {
        id: 'master',
        name: 'Master Bot (VPS)',
        role: 'Master Signal Provider',
        account: 'Telegram @selo_saham_bot',
        server: 'Ubuntu 24.04 VPS (Cloud)',
        lot: 'Provider',
        balance: 'VPS Active',
        equity: 'Signals 142',
        shirtColor: 0x9333ea, // Ungu Master
        pos: [-12, -2.5],
        rot: 0,
        isMaster: true
      },
      {
        id: 'deden',
        name: 'Deden (You - Local MT5)',
        role: 'Client Copier (Lokal Windows)',
        account: 'HFMarkets #114201000',
        server: 'HFMarketsGlobal-Live7',
        lot: '0.05 Lot Cent',
        balance: '$475.26 USC',
        equity: '$476.31 USC',
        shirtColor: 0x0284c7, // Biru Cyan
        pos: [-1.5, 4.5],
        rot: Math.PI,
        isDeden: true
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
        shirtColor: 0x06b6d4, // Cyan
        pos: [-5.5, -0.5],
        rot: 0
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
        shirtColor: 0x2563eb, // Biru Tua
        pos: [-2.5, 0.5],
        rot: 0
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
        shirtColor: 0x0d9488, // Teal
        pos: [1.5, 2.5],
        rot: 0
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
        shirtColor: 0xca8a04, // Beige Khaki
        pos: [5.5, 0.8],
        rot: 0
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
        shirtColor: 0xeab308, // Kuning
        pos: [7.5, -2.5],
        rot: 0
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
        shirtColor: 0xd97706, // Orange/Coral
        pos: [12.5, -1.5],
        rot: 0
      }
    ];

    for (let cfg of agentConfigs) {
      this.createDeskWithAgent(cfg);
    }
  }

  createDeskWithAgent(cfg) {
    const group = new THREE.Group();

    // 1. Meja Komputer Kayu
    const deskGeo = new THREE.BoxGeometry(2.4, 1.3, 1.4);
    const deskMat = new THREE.MeshStandardMaterial({ color: 0xab7a4e, roughness: 0.4 });
    const desk = new THREE.Mesh(deskGeo, deskMat);
    desk.position.set(0, 0.65, 0);
    desk.castShadow = true;
    desk.receiveShadow = true;
    group.add(desk);

    // 2. Laptop dengan Layar Berpendar
    const screenColor = cfg.isMaster ? 0xa855f7 : cfg.isDeden ? 0x00f0ff : 0x10b981;
    const laptop = this.createLaptop(screenColor);
    laptop.position.set(0, 1.32, -0.15);
    group.add(laptop);

    // 3. Kursi Putar di Depan Meja
    const chair = this.createOfficeChair(0x1f2937);
    chair.position.set(0, 0, 1.1);
    chair.rotation.y = Math.PI;
    group.add(chair);

    // 4. Karakter 3D Stylized (Low-poly Voxel Figure)
    const charGroup = new THREE.Group();

    // Kaki / Celana
    const pantsMat = new THREE.MeshStandardMaterial({ color: 0x1e293b, roughness: 0.5 });
    const legs = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.6, 0.6), pantsMat);
    legs.position.set(0, 0.65, 0.9);
    charGroup.add(legs);

    // Badan / Kemeja Berwarna
    const shirtMat = new THREE.MeshStandardMaterial({ color: cfg.shirtColor, roughness: 0.4 });
    const torso = new THREE.Mesh(new THREE.BoxGeometry(0.65, 0.8, 0.4), shirtMat);
    torso.position.set(0, 1.3, 0.9);
    torso.castShadow = true;
    charGroup.add(torso);

    // Lengan Tangan Mengetik ke arah Laptop
    const armLeft = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.16, 0.6), shirtMat);
    armLeft.position.set(-0.35, 1.25, 0.5);
    charGroup.add(armLeft);

    const armRight = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.16, 0.6), shirtMat);
    armRight.position.set(0.35, 1.25, 0.5);
    charGroup.add(armRight);

    // Kepala (Skin tone)
    const skinMat = new THREE.MeshStandardMaterial({ color: 0xfbcfe8, roughness: 0.3 });
    const head = new THREE.Mesh(new THREE.BoxGeometry(0.45, 0.45, 0.42), skinMat);
    head.position.set(0, 1.95, 0.9);
    head.castShadow = true;
    charGroup.add(head);

    // Rambut
    const hairColor = cfg.id === 'susie' ? 0xb45309 : cfg.id === 'deden' ? 0x18181b : 0x451a03;
    const hair = new THREE.Mesh(new THREE.BoxGeometry(0.48, 0.2, 0.45), new THREE.MeshStandardMaterial({ color: hairColor }));
    hair.position.set(0, 2.2, 0.9);
    charGroup.add(hair);

    group.add(charGroup);

    // Posisikan Meja & Karakter di Office Floor
    group.position.set(cfg.pos[0], 0, cfg.pos[1]);
    group.rotation.y = cfg.rot;
    this.scene.add(group);

    // 5. Buat 2D DOM Floating Label Badge
    const labelEl = this.createFloatingLabel(cfg);

    // Simpan data agent untuk kontrol dan animasi
    this.agents[cfg.id] = {
      id: cfg.id,
      name: cfg.name,
      group: group,
      charGroup: charGroup,
      armLeft: armLeft,
      armRight: armRight,
      head: head,
      laptop: laptop,
      screenMat: laptop.screenMat,
      labelEl: labelEl,
      data: cfg,
      basePos: new THREE.Vector3(cfg.pos[0], 0, cfg.pos[1]),
      headWorldPos: new THREE.Vector3()
    };
  }

  createFloatingLabel(cfg) {
    const badge = document.createElement('div');
    badge.className = `agent-3d-badge ${cfg.isMaster ? 'master-tag' : ''} ${cfg.isDeden ? 'deden-tag' : ''}`;
    badge.setAttribute('data-agent-id', cfg.id);

    const avatarIcon = cfg.isMaster ? '👑' : cfg.isDeden ? '💻' : '🧑‍💻';
    const dotClass = cfg.isMaster ? 'dot-purple' : 'dot-green';

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

  showSpeechBubble(agentId, text, type = 'order-success') {
    const agent = this.agents[agentId];
    if (!agent) return;

    const bubble = document.createElement('div');
    bubble.className = `speech-bubble ${type}`;
    bubble.textContent = text;
    this.speechContainer.appendChild(bubble);

    // Auto remove setelah 5 detik
    setTimeout(() => {
      if (bubble.parentNode) bubble.parentNode.removeChild(bubble);
    }, 4500);

    // Update posisi di render loop
    bubble.agentRef = agent;
  }

  // ==========================================================================
  // SIGNAL BROADCAST FX: PULSA DARI RUANG SERVER VPS KE SEMUA MEMBER
  // ==========================================================================

  triggerSignalBroadcastAnimation(signalData) {
    const isBuy = signalData.action === 'BUY';
    const glowColor = isBuy ? 0x10b981 : 0xef4444;

    // 1. Lampu Server Room berkedip terang
    this.serverLight.color.setHex(glowColor);
    this.serverLight.intensity = 6;
    setTimeout(() => {
      this.serverLight.color.setHex(0x00f0ff);
      this.serverLight.intensity = 2.5;
    }, 1200);

    // 2. Buat Gelombang Laser / Pulsa Energi ke seluruh meja member
    const serverOrigin = new THREE.Vector3(-12, 1.5, -6);

    for (let agentId in this.agents) {
      const agent = this.agents[agentId];
      if (agent.data.isMaster) continue;

      const targetPos = agent.basePos.clone().add(new THREE.Vector3(0, 1.4, 0));
      this.spawnSignalBeam(serverOrigin, targetPos, glowColor, () => {
        // Callback saat pulsa sampai di laptop member:
        // Layar laptop berkedip sesuai aksi
        agent.screenMat.color.setHex(glowColor);
        setTimeout(() => {
          agent.screenMat.color.setHex(agent.data.isDeden ? 0x00f0ff : 0x10b981);
        }, 1500);

        // Karakter mengetik cepat & selebrasi
        agent.typingFast = true;
        setTimeout(() => { agent.typingFast = false; }, 2000);

        // Tampilkan speech bubble di atas kepala
        const ticketNum = Math.floor(15248000000 + Math.random() * 99999);
        const lotStr = agent.data.lot;
        const bubbleMsg = `✅ #${ticketNum} ${signalData.action} ${lotStr} @ $${signalData.entry.toFixed(2)}`;
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
      // Lengkungan sedikit melompat ke atas
      p.y += Math.sin(t * Math.PI) * 1.8;
      points.push(p);
    }

    const curve = new THREE.CatmullRomCurve3(points);
    const geom = new THREE.TubeGeometry(curve, 20, 0.08, 8, false);
    const mat = new THREE.MeshBasicMaterial({ color: colorHex, transparent: true, opacity: 0.9 });
    const mesh = new THREE.Mesh(geom, mat);
    this.scene.add(mesh);

    // Animasi pulsa memanjang lalu menghilang
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
  // CAMERA CONTROLS & AGENT FOCUS
  // ==========================================================================

  focusOnAgent(agentId) {
    const agent = this.agents[agentId];
    if (!agent) return;

    const targetPos = agent.basePos.clone();
    this.cameraTarget.copy(targetPos);
    this.cameraDesiredPos.set(targetPos.x + 10, targetPos.y + 10, targetPos.z + 10);
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
    const bg = this.isNight ? 0x090d16 : 0xccd6e0;
    this.scene.background.setHex(bg);
    this.scene.fog.color.setHex(bg);
    this.ambientLight.intensity = this.isNight ? 0.7 : 1.2;
    this.dirLight.intensity = this.isNight ? 1.2 : 1.7;
    return this.isNight;
  }

  // ==========================================================================
  // INTERACTION (CLICK & HOVER)
  // ==========================================================================

  onCanvasClick(e) {
    const rect = this.canvas.getBoundingClientRect();
    this.mouse.x = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    this.mouse.y = -((e.clientY - rect.top) / rect.height) * 2 + 1;

    this.raycaster.setFromCamera(this.mouse, this.camera);
    
    // Cari objek agent yang di-klik
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

  onMouseMove(e) {
    // Hover visual indicator jika diperlukan
  }

  onResize() {
    const width = this.canvas.clientWidth;
    const height = this.canvas.clientHeight;
    this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(width, height);
  }

  // ==========================================================================
  // ANIMATION LOOP
  // ==========================================================================

  animate() {
    requestAnimationFrame(() => this.animate());

    const delta = this.clock.getDelta();
    const elapsedTime = this.clock.getElapsedTime();

    // 1. Update OrbitControls & Smooth Camera Lerp
    this.camera.position.lerp(this.cameraDesiredPos, 0.05);
    this.controls.target.lerp(this.cameraTarget, 0.05);
    this.controls.update();

    // 2. Animasi LED Server Berkedip
    for (let led of this.blinkingLeds) {
      if (elapsedTime - led.lastToggle > led.interval) {
        led.lastToggle = elapsedTime;
        const isOn = led.mesh.material.color.getHex() !== 0x000000;
        led.mesh.material.color.setHex(isOn ? 0x111111 : led.origColor);
      }
    }

    // 3. Animasi Idle Mengetik Karakter Trader
    for (let id in this.agents) {
      const agent = this.agents[id];
      const typingSpeed = agent.typingFast ? 24 : 6;
      
      // Tangan mengetik naik turun bergantian
      const armOffset = Math.sin(elapsedTime * typingSpeed + (id.charCodeAt(0) % 5)) * 0.04;
      agent.armLeft.position.y = 1.25 + armOffset;
      agent.armRight.position.y = 1.25 - armOffset;

      // Gerak kepala halus
      agent.head.rotation.y = Math.sin(elapsedTime * 1.5 + (id.charCodeAt(0) % 3)) * 0.12;

      // Update Proyeksi Label 2D di Layar HTML
      agent.group.getWorldPosition(agent.headWorldPos);
      agent.headWorldPos.y += 2.6; // Di atas kepala
      this.update2DProjection(agent.headWorldPos, agent.labelEl);
    }

    // 4. Update Posisi Speech Bubbles
    const bubbles = this.speechContainer.getElementsByClassName('speech-bubble');
    for (let bubble of bubbles) {
      if (bubble.agentRef) {
        const pos = bubble.agentRef.headWorldPos.clone();
        pos.y += 0.8;
        this.update2DProjection(pos, bubble);
      }
    }

    // 5. Render Scene
    this.renderer.render(this.scene, this.camera);
  }

  update2DProjection(worldPos, domElement) {
    const screenPos = worldPos.clone().project(this.camera);
    const widthHalf = this.canvas.clientWidth / 2;
    const heightHalf = this.canvas.clientHeight / 2;

    const x = (screenPos.x * widthHalf) + widthHalf;
    const y = -(screenPos.y * heightHalf) + heightHalf;

    // Jika objek berada di belakang kamera
    if (screenPos.z > 1) {
      domElement.style.display = 'none';
    } else {
      domElement.style.display = 'flex';
      domElement.style.left = `${x}px`;
      domElement.style.top = `${y}px`;
    }
  }
}

// Expose ke global
window.Office3D = Office3D;
