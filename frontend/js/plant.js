/* ЛПЗС «Родина» — модель установки вокруг программы ПЛК.
   PLC (plc.js) решает, какие приводы включить. Здесь — всё, что в реальности
   находится за клеммами ПЛК: двигатели с разгоном и выбегом, импульсные ДКС,
   концевики переключателей потока, уровни бункеров, движение продукта,
   а также кнопки и поля панели оператора (переменные HMI_*). */

(function (global) {
  "use strict";

  const PLCLIB = global.PLC;
  const plc = PLCLIB.createPLC();
  const V = plc.v;

  const W = 3600, H = 1800;

  /* пропорции спрайтов (w/h), замерены по обрезанным файлам */
  const AR = {
    cyclone: 0.473, debearder: 0.818, diverter: 1.015, fan: 0.969,
    hopper: 0.631, intake: 1.845, magnet: 0.842, muz: 1.487,
    noria: 0.347, pneumo: 1.902, screw: 3.851, silo: 0.479,
    tor: 0.852, trier: 1.459, truck: 2.279,
  };
  const byW = (sp, x, y, w) => ({ x, y, w, h: Math.round(w / AR[sp]), sprite: sp });
  const byH = (sp, x, y, h) => ({ x, y, w: Math.round(h * AR[sp]), h, sprite: sp });
  const motor = (x, y, drive) => ({ x, y, w: 58, h: 58, kind: "motor", drive });

  /* ------------------------------------------------------------ узлы схемы */
  // drive — привод ПЛК, по которому анимируется узел.
  const ND = {
    truck_in:  { ...byW("truck", 40, 250, 300), kind: "truck" },
    intake:    { ...byW("intake", 40, 450, 420), kind: "intake", drive: "conv_2", poz: "1–2" },
    m_vor:     { ...motor(70, 700, "vor"), poz: "1", parent: "intake" },
    magnet_3:  { ...byW("magnet", 488, 600, 64), kind: "magnet", poz: "3" },
    noria_4:   { ...byH("noria", 590, 200, 470), kind: "noria", drive: "noria_4", poz: "4" },
    ost:       { ...byW("debearder", 800, 190, 130), kind: "op", drive: "ost", poz: "5" },
    bun_61:    { ...byW("hopper", 822, 395, 90), kind: "hopper", level: "bo_1", poz: "6.1" },
    ksp:       { ...byW("muz", 760, 560, 300), kind: "muz", drive: "ksp", poz: "6" },
    m_biter:   { ...motor(1070, 575, "ksp_biter"), poz: "6", parent: "ksp" },
    fan_asp_1: { ...byW("fan", 975, 120, 100), kind: "fan", drive: "fan_asp_1", poz: "7" },
    noria_8:   { ...byH("noria", 1170, 200, 470), kind: "noria", drive: "noria_8", poz: "8" },
    bun_9:     { ...byW("hopper", 1392, 196, 90), kind: "hopper", level: "bo_2", poz: "9" },
    tor:       { ...byW("tor", 1370, 380, 270), kind: "tor", drive: "tor", poz: "10" },
    m_tor_biter: { ...motor(1652, 560, "tor_biter"), poz: "10", parent: "tor" },
    fan_asp_2: { ...byW("fan", 1535, 110, 100), kind: "fan", drive: "fan_asp_2", poz: "11" },
    noria_12:  { ...byH("noria", 1760, 200, 470), kind: "noria", drive: "noria_12", poz: "12" },
    flow_1:    { ...byW("diverter", 1958, 200, 90), kind: "diverter", drive: "flow_1", poz: "13.1" },
    bt_14_1:   { ...byW("trier", 1960, 330, 300), kind: "trier", drive: "trier_1", drive2: "trier_2_1", poz: "14.1" },
    m_trier_1: { ...motor(2270, 372, "trier_1"), poz: "14.1 N1", parent: "bt_14_1" },
    m_trier_2_1: { ...motor(2336, 372, "trier_2_1"), poz: "14.1 N2", parent: "bt_14_1" },
    bt_14_2:   { ...byW("trier", 1960, 580, 300), kind: "trier", drive: "trier_1_2", drive2: "trier_2_2", poz: "14.2" },
    m_trier_1_2: { ...motor(2270, 622, "trier_1_2"), poz: "14.2 N1", parent: "bt_14_2" },
    m_trier_2_2: { ...motor(2336, 622, "trier_2_2"), poz: "14.2 N2", parent: "bt_14_2" },
    noria_15:  { ...byH("noria", 2390, 200, 470), kind: "noria", drive: "noria_15", poz: "15" },
    flow_2:    { ...byW("diverter", 2588, 200, 90), kind: "diverter", drive: "flow_2", poz: "13.2" },
    bun_16:    { ...byW("hopper", 2618, 318, 90), kind: "hopper", level: "bo_3", poz: "16" },
    pnev:      { ...byW("pneumo", 2560, 505, 350), kind: "sp", drive: "pnev", poz: "18" },
    fan_pnev:  { ...byW("fan", 2842, 380, 82), kind: "fan", drive: "fan_pnev", poz: "18" },
    fan_asp_3: { ...byW("fan", 2745, 110, 100), kind: "fan", drive: "fan_asp_3", poz: "19" },
    noria_20:  { ...byH("noria", 3035, 200, 470), kind: "noria", drive: "noria_20", poz: "20" },
    bun_21:    { ...byH("silo", 3265, 225, 360), kind: "silo", level: "V", poz: "21", letter: "В" },
    truck_out: { ...byW("truck", 3250, 640, 300), kind: "truck" },

    cyc_1:     { ...byH("cyclone", 60, 905, 290), kind: "cyclone", poz: "7" },
    cyc_2:     { ...byH("cyclone", 265, 905, 290), kind: "cyclone", poz: "11" },
    cyc_3:     { ...byH("cyclone", 470, 905, 290), kind: "cyclone", poz: "19" },
    shl_1:     { x: 94, y: 1206, w: 70, h: 62, kind: "sluice", drive: "shl_1", poz: "7" },
    shl_2:     { x: 299, y: 1206, w: 70, h: 62, kind: "sluice", drive: "shl_2", poz: "11" },
    shl_3:     { x: 504, y: 1206, w: 70, h: 62, kind: "sluice", drive: "shl_3", poz: "19" },
    conv_22_5: { ...byW("screw", 60, 1340, 500), kind: "screw", drive: "conv_22_5", poz: "22.5" },
    conv_22_1: { ...byW("screw", 700, 1185, 480), kind: "screw", drive: "conv_22_1", poz: "22.1" },
    noria_23:  { ...byH("noria", 1290, 1060, 460), kind: "noria", drive: "noria_23", poz: "23" },
    bun_A:     { ...byH("silo", 1500, 1150, 330), kind: "silo", level: "A", poz: "25", letter: "А" },
    bun_B:     { ...byH("silo", 1700, 1150, 330), kind: "silo", level: "B", poz: "25", letter: "Б" },
    noria_24:  { ...byH("noria", 1905, 1060, 460), kind: "noria", drive: "noria_24", poz: "24" },
    truck_A:   { ...byW("truck", 1470, 1560, 220), kind: "truck" },
    truck_B:   { ...byW("truck", 1700, 1560, 220), kind: "truck" },
    conv_22_4: { ...byW("screw", 2040, 905, 440), kind: "screw", drive: "conv_22_4", poz: "22.4" },
    conv_22_2: { ...byW("screw", 2180, 1255, 480), kind: "screw", drive: "conv_22_2", poz: "22.2" },
    conv_22_3: { ...byW("screw", 2780, 1080, 480), kind: "screw", drive: "conv_22_3", poz: "22.3" },
  };

  /* -------------------------------------------------- точки присоединения */
  const A = {};
  for (const [id, n] of Object.entries(ND)) {
    const a = {};
    const px = (u) => n.x + u * n.w, py = (v) => n.y + v * n.h;
    switch (n.kind) {
      case "noria":
        a.in = [px(0.10), py(0.93)]; a.out = [px(0.90), py(0.16)];
        a.col = px(0.50); a.top = py(0.14); a.bot = py(0.88);
        a.win = [0.40, 0.12, 0.20, 0.76];
        break;
      case "intake":
        a.beltY = py(0.50); a.bx1 = px(0.14); a.bx2 = px(0.88);
        a.out = [px(0.92), py(0.52)];
        break;
      case "magnet": a.in = [px(0.5), py(0.02)]; a.out = [px(0.5), py(0.98)]; break;
      case "op": a.in = [px(0.28), py(0.04)]; a.out = [px(0.86), py(0.84)]; break;
      case "hopper": a.in = [px(0.5), py(0.02)]; a.out = [px(0.5), py(0.97)];
        a.body = [0.16, 0.10, 0.68, 0.46]; a.cone = [0.20, 0.58, 0.60, 0.30]; break;
      case "muz":
        a.in = [px(0.30), py(0.02)]; a.out = [px(0.52), py(0.96)];
        a.waste = [px(0.80), py(0.94)]; a.duct = [px(0.90), py(0.02)];
        break;
      case "tor":
        a.in = [px(0.22), py(0.03)]; a.out = [px(0.50), py(0.96)];
        a.waste = [px(0.80), py(0.94)]; a.duct = [px(0.86), py(0.03)];
        break;
      case "trier":
        a.in = [px(0.10), py(0.14)]; a.out = [px(0.92), py(0.52)]; a.waste = [px(0.50), py(0.96)];
        break;
      case "sp":
        a.in = [px(0.08), py(0.14)]; a.out = [px(0.78), py(0.82)];
        a.waste = [px(0.58), py(0.96)]; a.duct = [px(0.82), py(0.04)];
        break;
      case "silo":
        a.in = [px(0.5), py(0.03)]; a.out = [px(0.5), py(0.98)];
        a.body = [0.10, 0.13, 0.80, 0.53]; a.cone = [0.12, 0.66, 0.76, 0.24];
        break;
      case "cyclone": a.in = [px(0.04), py(0.20)]; a.out = [px(0.50), py(0.99)]; break;
      case "sluice": a.in = [px(0.5), py(0)]; a.out = [px(0.5), py(1)]; break;
      case "diverter": a.in = [px(0.5), py(0.04)]; a.oa = [px(0.24), py(0.94)]; a.ob = [px(0.78), py(0.94)]; break;
      case "screw": a.l = px(0.10); a.r = px(0.90); a.y = py(0.40); break;
      case "fan": a.c = [px(0.5), py(0.5)]; break;
      default: break;
    }
    A[id] = a;
  }

  // Воздуховоды аспирации: от машины через вентилятор к циклону.
  const DUCTS = [
    { id: "fan_asp_1", poz: "АС-1", pts: [A.ksp.duct, [A.ksp.duct[0], 172], [ND.fan_asp_1.x + 10, 172],
      [ND.fan_asp_1.x + 50, 70], [30, 70], [30, 960], A.cyc_1.in] },
    { id: "fan_asp_2", poz: "АС-2", pts: [A.tor.duct, [A.tor.duct[0], 160], [ND.fan_asp_2.x + 10, 160],
      [ND.fan_asp_2.x + 50, 56], [236, 56], [236, 960], A.cyc_2.in] },
    { id: "fan_asp_3", poz: "АС-3", pts: [A.pnev.duct, [A.pnev.duct[0], 160], [ND.fan_asp_3.x + 10, 160],
      [ND.fan_asp_3.x + 50, 42], [442, 42], [442, 960], A.cyc_3.in] },
  ];

  /* ------------------------------------------------------------ приводы */
  const NAMES = {
    conv_2: ["Конвейер SBT-LR-T168 (завальная яма)", "2"],
    vor: ["Ворошитель ямы завальной ЯЗТ-10", "1"],
    noria_4: ["Нория НС-В.10.10", "4"],
    ost: ["Остеобрушиватель ОП-11", "5"],
    ksp_biter: ["МУЗ-8М — битер (ПЧ)", "6"],
    ksp: ["Машина зерноочистительная МУЗ-8М", "6"],
    fan_asp_1: ["Вентилятор аспирации АС-1", "7"],
    shl_1: ["Затвор шлюзовый ЗШ-17 АС-1", "7"],
    noria_8: ["Нория НС-А.10.08", "8"],
    tor: ["Машина решётная ТОР-18", "10"],
    tor_biter: ["ТОР-18 — битер (ПЧ)", "10"],
    fan_asp_2: ["Вентилятор аспирации АС-2", "11"],
    shl_2: ["Затвор шлюзовый ЗШ-17 АС-2", "11"],
    noria_12: ["Нория НС-А.10.08", "12"],
    flow_1: ["Переключатель потока ППМ-2.160", "13.1"],
    trier_1: ["Триерный блок БТ-7/2 — двигатель N1", "14.1"],
    trier_2_1: ["Триерный блок БТ-7/2 — двигатель N2", "14.1"],
    trier_1_2: ["Триерный блок БТ-7/2 — двигатель N1", "14.2"],
    trier_2_2: ["Триерный блок БТ-7/2 — двигатель N2", "14.2"],
    noria_15: ["Нория НС-А.10.11", "15"],
    flow_2: ["Переключатель потока ППМ-2.160", "13.2"],
    pnev: ["Стол пневмосортировальный СП-200", "18"],
    fan_pnev: ["Вентилятор стола СП-200", "18"],
    fan_asp_3: ["Вентилятор аспирации АС-3", "19"],
    shl_3: ["Затвор шлюзовый ЗШ-17 АС-3", "19"],
    noria_20: ["Нория Н3-В.10.10", "20"],
    conv_22_1: ["Конвейер шнековый КШИ-200 10М/10", "22.1"],
    conv_22_2: ["Конвейер шнековый КШИ-200 9М/15", "22.2"],
    conv_22_3: ["Конвейер шнековый КШИ-150 8М/5", "22.3"],
    conv_22_4: ["Конвейер шнековый КШИ-150 9М/5", "22.4"],
    conv_22_5: ["Конвейер шнековый КШИ-150 6М/5", "22.5"],
    noria_23: ["Нория НС-А.10.11", "23"],
    noria_24: ["Нория НС-А.20.11", "24"],
  };
  // Приводы с ПЧ: вход готовности, вход аварии ПЧ и выход разрешения от ПЛК.
  const PCH = {
    conv_2: { ready: "in_pch_ready_2", az: "in_az_pch_2", en: "y_run_pch_2" },
    ksp_biter: { ready: "in_pch_ready_biter", az: "in_az_pch_ksp", en: "y_pch_biter" },
    tor_biter: { ready: "in_pch_tor_ready", az: "in_tor_pch_az", en: "y_run_pch_tor" },
    trier_1: { ready: "in_pch_ready_trier_1", az: "in_az_pch_trier_1", en: "y_pch_trier_1" },
    trier_2_1: { ready: "in_pch_ready_trier_2", az: "in_az_pch_trier_2", en: "y_pch_trier_2" },
    trier_1_2: { ready: "in_pch_ready_trier_1_2", az: "in_az_pch_trier_1_2", en: "y_pch_trier_1_2" },
    trier_2_2: { ready: "in_pch_ready_trier_2_2", az: "in_az_pch_trier_2_2", en: "y_pch_trier_2_2" },
    pnev: { ready: "in_pch_ready_pnev", az: "in_az_pch_pnev", en: "y_pch_pnev" },
  };
  // Местные аварийные кнопки у машин (IN_stop_*).
  const LOCAL_STOP = { ost: "in_stop_ost", ksp_biter: "in_stop_biter", tor: "in_m_stop_tor", tor_biter: "in_m_stop_tor",
    trier_1: "in_stop_trier_1", trier_2_1: "in_stop_trier_2", trier_1_2: "in_stop_trier_1_2",
    trier_2_2: "in_stop_trier_2_2", pnev: "in_stop_pnev" };

  const DEF = {};
  plc.DRIVES.forEach((d) => { DEF[d.id] = d; });
  plc.FLAPPERS.forEach((f) => { DEF[f.id] = f; });

  const S = {
    W, H, ND, A, DUCTS, V, plc,
    machines: {},
    levels: { pit: 0.86, bo_1: 0, bo_2: 0, bo_3: 0, V: 0.18, A: 0.34, B: 0.22 },
    clock: 0, timeScale: 1, scanDt: 0.02,
    alarms: [], archive: [],
    user: { login: "operator", role: "Оператор" },
  };

  function mkMachine(id) {
    const d = DEF[id];
    const [name, poz] = NAMES[id];
    const m = {
      id, name, poz, fb: d.fb || "flapper",
      w: 0, spin: 0, vib: 0, mat: 0, pos: 0,
      running: false, cmd: false, fault: false,
      hours: 0, hoursTotal: 800 + ((id.length * 137) % 900), toHours: 200,
      sim: { az: false, dks: false, dsl1: false, dsl2: false, dp: false, pch: false, jam: false },
      dksPhase: (id.length * 0.13) % 1,
    };
    m.sensors = d.fb === "transport" ? ["dks", "dp", "dsl1", "dsl2"].filter((k) => d[k]) : [];
    return m;
  }
  Object.keys(NAMES).forEach((id) => { S.machines[id] = mkMachine(id); });

  /* ------------------------------------------------------- тракт продукта */
  const FEED = 3.4;                 // кг/с при номинале 12,4 т/ч
  const CAP = { pit: 10000, bo_1: 700, bo_2: 700, bo_3: 700, V: 15000, A: 5000, B: 5000 };
  const L = (k) => S.levels[k] * CAP[k];
  const addLevel = (k, kg) => { S.levels[k] = Math.max(0, Math.min(1, S.levels[k] + kg / CAP[k])); };

  const chuteTo = (a, b) => [a, [a[0], Math.min(a[1] + 30, b[1])], [b[0], Math.min(a[1] + 30, b[1])], b];
  const lift = (id) => { const a = A[id]; return [a.in, [a.col, a.bot], [a.col, a.top], a.out]; };
  const screw = (id, rightToLeft) => {
    const a = A[id];
    return rightToLeft ? [[a.r, a.y], [a.l, a.y]] : [[a.l, a.y], [a.r, a.y]];
  };
  const through = (id) => [A[id].in, [(A[id].in[0] + A[id].out[0]) / 2, (A[id].in[1] + A[id].out[1]) / 2], A[id].out];

  // Элемент тракта — транспортная задержка из N ячеек. С приводом движется
  // только при вращении, без привода — самотёк.
  const ELEM = {};
  function el(id, cfg) {
    const e = { id, T: 2, N: 18, drive: null, dp: false, ...cfg };
    e.cells = new Array(e.N).fill(0);
    e.acc = 0; e.fill = 0; e.jam = false;
    ELEM[id] = e;
    return e;
  }
  const pos1 = (id) => S.machines[id].pos <= 0.02;
  const pos2 = (id) => S.machines[id].pos >= 0.98;

  el("conv_2", { drive: "conv_2", T: 6, pts: [[A.intake.bx1, A.intake.beltY], [A.intake.bx2, A.intake.beltY], A.intake.out] });
  el("c_2_4", { T: 1.2, pts: [A.intake.out, A.magnet_3.in, A.magnet_3.out, [A.magnet_3.out[0], A.noria_4.in[1]], A.noria_4.in] });
  el("noria_4", { drive: "noria_4", T: 5, pts: lift("noria_4") });
  el("c_4_ost", { T: 1, pts: chuteTo(A.noria_4.out, A.ost.in) });
  el("c_4_61", { T: 1.2, pts: [A.noria_4.out, [A.noria_4.out[0] + 20, A.noria_4.out[1] + 30], [A.bun_61.in[0] - 50, A.bun_61.in[1] - 30], A.bun_61.in] });
  el("ost", { drive: "ost", T: 3, pts: through("ost") });
  el("c_ost_61", { T: 0.8, pts: [A.ost.out, [A.ost.out[0], A.bun_61.in[1] - 16], [A.bun_61.in[0], A.bun_61.in[1] - 16], A.bun_61.in] });
  el("ksp", { drive: "ksp", T: 5, pts: [A.ksp.in, [A.ksp.in[0] + 40, ND.ksp.y + 90], [A.ksp.out[0], ND.ksp.y + 150], A.ksp.out] });
  el("c_ksp_8", { T: 1.2, pts: [A.ksp.out, [A.ksp.out[0], ND.ksp.y + ND.ksp.h + 30], [A.noria_8.in[0], ND.ksp.y + ND.ksp.h + 30], A.noria_8.in] });
  el("c_ksp_221", { T: 2, pts: [A.ksp.waste, [A.ksp.waste[0], 1090], [A.conv_22_1.l + 60, 1090], [A.conv_22_1.l + 60, A.conv_22_1.y]] });
  el("c_ksp_222", { T: 3, pts: [A.ksp.waste, [A.ksp.waste[0] + 20, 1050], [A.conv_22_2.r - 40, 1050], [A.conv_22_2.r - 40, A.conv_22_2.y]] });
  el("noria_8", { drive: "noria_8", T: 5, pts: lift("noria_8") });
  el("c_8_9", { T: 1, pts: chuteTo(A.noria_8.out, A.bun_9.in) });
  el("tor", { drive: "tor", T: 6, pts: [A.tor.in, [A.tor.in[0] + 30, ND.tor.y + 120], [A.tor.out[0], ND.tor.y + 220], A.tor.out] });
  el("c_tor_12", { T: 1.2, pts: [A.tor.out, [A.tor.out[0], ND.tor.y + ND.tor.h + 26], [A.noria_12.in[0], ND.tor.y + ND.tor.h + 26], A.noria_12.in] });
  el("c_tor_222", { T: 3, pts: [A.tor.waste, [A.tor.waste[0], 1010], [A.conv_22_2.r - 90, 1010], [A.conv_22_2.r - 90, A.conv_22_2.y]] });
  el("noria_12", { drive: "noria_12", T: 5, pts: lift("noria_12") });
  el("c_12_f1", { T: 0.8, pts: chuteTo(A.noria_12.out, A.flow_1.in) });
  el("c_f1_t1", { T: 0.8, pts: [A.flow_1.oa, [A.flow_1.oa[0], A.bt_14_1.in[1] - 20], A.bt_14_1.in] });
  el("c_f1_t2", { T: 1.6, pts: [A.flow_1.oa, [ND.bt_14_1.x - 20, A.flow_1.oa[1] + 20], [ND.bt_14_1.x - 20, A.bt_14_2.in[1]], A.bt_14_2.in] });
  el("c_f1_15", { T: 1.8, pts: [A.flow_1.ob, [A.flow_1.ob[0] + 40, A.flow_1.ob[1] + 22], [ND.bt_14_1.x + ND.bt_14_1.w + 100, A.flow_1.ob[1] + 22],
    [ND.bt_14_1.x + ND.bt_14_1.w + 100, A.noria_15.in[1] - 30], [A.noria_15.in[0], A.noria_15.in[1] - 30], A.noria_15.in] });
  el("bt_14_1", { drive: "trier_1", drive2: "trier_2_1", T: 6, pts: through("bt_14_1") });
  el("bt_14_2", { drive: "trier_1_2", drive2: "trier_2_2", T: 6, pts: through("bt_14_2") });
  el("c_t1_15", { T: 1.6, pts: [A.bt_14_1.out, [ND.bt_14_1.x + ND.bt_14_1.w + 70, A.bt_14_1.out[1]],
    [ND.bt_14_1.x + ND.bt_14_1.w + 70, A.noria_15.in[1]], A.noria_15.in] });
  el("c_t2_15", { T: 1.2, pts: [A.bt_14_2.out, [ND.bt_14_2.x + ND.bt_14_2.w + 70, A.bt_14_2.out[1]],
    [ND.bt_14_2.x + ND.bt_14_2.w + 70, A.noria_15.in[1]], A.noria_15.in] });
  el("c_t1_224", { T: 2, pts: [A.bt_14_1.waste, [ND.bt_14_1.x - 45, A.bt_14_1.waste[1]],
    [ND.bt_14_1.x - 45, 880], [A.conv_22_4.l + 40, 880], [A.conv_22_4.l + 40, A.conv_22_4.y]] });
  el("c_t2_224", { T: 1.2, pts: [A.bt_14_2.waste, [A.bt_14_2.waste[0], A.conv_22_4.y]] });
  el("noria_15", { drive: "noria_15", T: 5, pts: lift("noria_15") });
  el("c_15_f2", { T: 0.8, pts: chuteTo(A.noria_15.out, A.flow_2.in) });
  el("c_f2_16", { T: 0.8, pts: [A.flow_2.oa, [A.flow_2.oa[0], A.bun_16.in[1] - 16], [A.bun_16.in[0], A.bun_16.in[1] - 16], A.bun_16.in] });
  el("c_f2_20", { T: 1.8, pts: [A.flow_2.ob, [A.flow_2.ob[0] + 20, 330], [ND.noria_20.x - 40, 330], [ND.noria_20.x - 40, A.noria_20.in[1]], A.noria_20.in] });
  el("pnev", { drive: "pnev", T: 6, pts: through("pnev") });
  el("c_sp_20", { T: 1, pts: [A.pnev.out, [A.pnev.out[0], A.noria_20.in[1] + 10], A.noria_20.in] });
  el("c_sp_223", { T: 2, pts: [A.pnev.waste, [A.pnev.waste[0], A.conv_22_3.y - 60], [A.conv_22_3.r - 40, A.conv_22_3.y - 60], [A.conv_22_3.r - 40, A.conv_22_3.y]] });
  el("noria_20", { drive: "noria_20", T: 5, pts: lift("noria_20") });
  el("c_20_21", { T: 1, pts: chuteTo(A.noria_20.out, A.bun_21.in) });

  // аспирация: воздуховод → циклон → шлюз → шнек 22.5
  DUCTS.forEach((d, i) => el("d_" + (i + 1), { drive: d.id, T: 2.2, pts: d.pts, dust: true }));
  [1, 2, 3].forEach((k) => {
    el("shl_" + k, { drive: "shl_" + k, T: 1.2, pts: [A["cyc_" + k].out, A["shl_" + k].in, A["shl_" + k].out], dust: true });
    el("c_shl" + k + "_225", { T: 0.8, pts: [A["shl_" + k].out, [A["shl_" + k].out[0], A.conv_22_5.y]], dust: true });
  });
  el("conv_22_5", { drive: "conv_22_5", T: 7, pts: screw("conv_22_5") });
  el("c_225_221", { T: 1, pts: [[A.conv_22_5.r, A.conv_22_5.y], [A.conv_22_5.r + 40, A.conv_22_5.y], [A.conv_22_1.l + 20, A.conv_22_1.y]] });
  el("conv_22_1", { drive: "conv_22_1", T: 7, pts: screw("conv_22_1") });
  el("c_221_23", { T: 1, pts: [[A.conv_22_1.r, A.conv_22_1.y], [A.noria_23.in[0] - 10, A.conv_22_1.y + 40], [A.noria_23.in[0] - 10, A.noria_23.in[1]], A.noria_23.in] });
  el("noria_23", { drive: "noria_23", T: 5, pts: lift("noria_23") });
  el("c_23_A", { T: 1, pts: chuteTo(A.noria_23.out, A.bun_A.in) });
  el("conv_22_4", { drive: "conv_22_4", T: 7, pts: screw("conv_22_4") });
  el("c_224_223", { T: 1.2, pts: [[A.conv_22_4.r, A.conv_22_4.y], [A.conv_22_4.r + 60, A.conv_22_4.y], [A.conv_22_3.l + 30, A.conv_22_3.y]] });
  el("conv_22_3", { drive: "conv_22_3", T: 7, pts: screw("conv_22_3", true) });
  el("c_223_222", { T: 1.2, pts: [[A.conv_22_3.l, A.conv_22_3.y], [A.conv_22_3.l - 40, A.conv_22_3.y + 40], [A.conv_22_2.r - 20, A.conv_22_2.y]] });
  el("conv_22_2", { drive: "conv_22_2", T: 7, pts: screw("conv_22_2", true) });
  el("c_222_24", { T: 1, pts: [[A.conv_22_2.l, A.conv_22_2.y], [A.noria_24.in[0] + 140, A.noria_24.in[1] - 10], A.noria_24.in] });
  el("noria_24", { drive: "noria_24", T: 5, pts: lift("noria_24") });
  el("c_24_B", { T: 1, pts: [A.noria_24.out, [A.noria_24.out[0], A.noria_24.out[1] - 20], [A.bun_B.in[0], A.noria_24.out[1] - 20], A.bun_B.in] });
  // Датчик подпора стоит у норий и шнеков — у них же накапливается продукт.
  ["noria_4", "noria_8", "noria_12", "noria_15", "noria_20", "noria_23", "noria_24", "conv_2",
    "conv_22_1", "conv_22_2", "conv_22_3", "conv_22_4", "conv_22_5"].forEach((k) => { ELEM[k].dp = true; });

  // Куда уходит продукт с выхода элемента: [[элемент | "lvl:ключ", доля], ...]
  function routesOf(id) {
    const run = (k) => S.machines[k].w > 0.5;
    switch (id) {
      case "conv_2": return [["c_2_4", 1]];
      case "c_2_4": return [["noria_4", 1]];
      case "noria_4": return V.on_ost ? [["c_4_ost", 1]] : [["c_4_61", 1]];
      case "c_4_ost": return [["ost", 1]];
      case "ost": return [["c_ost_61", 1]];
      case "c_ost_61": case "c_4_61": return [["lvl:bo_1", 1]];
      case "ksp": return run("fan_asp_1") ? [["c_ksp_8", 0.90], ["c_ksp_221", 0.04], ["c_ksp_222", 0.04], ["d_1", 0.02]]
        : [["c_ksp_8", 0.92], ["c_ksp_221", 0.04], ["c_ksp_222", 0.04]];
      case "c_ksp_8": return [["noria_8", 1]];
      case "c_ksp_221": return [["conv_22_1", 1]];
      case "c_ksp_222": case "c_tor_222": case "c_223_222": return [["conv_22_2", 1]];
      case "noria_8": return [["c_8_9", 1]];
      case "c_8_9": return [["lvl:bo_2", 1]];
      case "tor": return run("fan_asp_2") ? [["c_tor_12", 0.92], ["c_tor_222", 0.06], ["d_2", 0.02]]
        : [["c_tor_12", 0.94], ["c_tor_222", 0.06]];
      case "c_tor_12": return [["noria_12", 1]];
      case "noria_12": return [["c_12_f1", 1]];
      case "c_12_f1":
        if (pos1("flow_1")) {
          const u1 = !!V.use_1, u2 = !!V.use_2;
          if (u1 && u2) return [["c_f1_t1", 0.5], ["c_f1_t2", 0.5]];
          return u2 ? [["c_f1_t2", 1]] : [["c_f1_t1", 1]];
        }
        return pos2("flow_1") ? [["c_f1_15", 1]] : null;   // заслонка в движении — продукт задерживается
      case "c_f1_t1": return [["bt_14_1", 1]];
      case "c_f1_t2": return [["bt_14_2", 1]];
      case "c_f1_15": case "c_t1_15": case "c_t2_15": return [["noria_15", 1]];
      case "bt_14_1": return [["c_t1_15", 0.95], ["c_t1_224", 0.05]];
      case "bt_14_2": return [["c_t2_15", 0.95], ["c_t2_224", 0.05]];
      case "c_t1_224": case "c_t2_224": return [["conv_22_4", 1]];
      case "noria_15": return [["c_15_f2", 1]];
      case "c_15_f2": return pos1("flow_2") ? [["c_f2_16", 1]] : pos2("flow_2") ? [["c_f2_20", 1]] : null;
      case "c_f2_16": return [["lvl:bo_3", 1]];
      case "c_f2_20": case "c_sp_20": return [["noria_20", 1]];
      case "pnev": return run("fan_asp_3") ? [["c_sp_20", 0.93], ["c_sp_223", 0.05], ["d_3", 0.02]]
        : [["c_sp_20", 0.95], ["c_sp_223", 0.05]];
      case "c_sp_223": case "c_224_223": return [["conv_22_3", 1]];
      case "noria_20": return [["c_20_21", 1]];
      case "c_20_21": return [["lvl:V", 1]];
      case "d_1": return [["cyc:cyc_1", 1]];
      case "d_2": return [["cyc:cyc_2", 1]];
      case "d_3": return [["cyc:cyc_3", 1]];
      case "shl_1": return [["c_shl1_225", 1]];
      case "shl_2": return [["c_shl2_225", 1]];
      case "shl_3": return [["c_shl3_225", 1]];
      case "c_shl1_225": case "c_shl2_225": case "c_shl3_225": return [["conv_22_5", 1]];
      case "conv_22_5": return [["c_225_221", 1]];
      case "c_225_221": return [["conv_22_1", 1]];
      case "conv_22_1": return [["c_221_23", 1]];
      case "c_221_23": return [["noria_23", 1]];
      case "noria_23": return [["c_23_A", 1]];
      case "c_23_A": return [["lvl:A", 1]];
      case "conv_22_4": return [["c_224_223", 1]];
      case "conv_22_3": return [["c_223_222", 1]];
      case "conv_22_2": return [["c_222_24", 1]];
      case "c_222_24": return [["noria_24", 1]];
      case "noria_24": return [["c_24_B", 1]];
      case "c_24_B": return [["lvl:B", 1]];
      default: return null;
    }
  }
  const cyclone = { cyc_1: 0, cyc_2: 0, cyc_3: 0 };

  function speedOf(e) {
    if (!e.drive) return 1;
    let w = S.machines[e.drive].w;
    if (e.drive2) w = Math.min(w, S.machines[e.drive2].w);
    return w;
  }
  function deliver(target, kg) {
    if (kg <= 0) return;
    if (target.startsWith("lvl:")) { addLevel(target.slice(4), kg); return; }
    if (target.startsWith("cyc:")) { cyclone[target.slice(4)] += kg; return; }
    ELEM[target].cells[0] += kg;
  }
  function stepElement(e, dt) {
    const w = speedOf(e);
    if (w <= 0.001) return;
    e.acc += w * dt * e.N / e.T;
    while (e.acc >= 1) {
      e.acc -= 1;
      const out = e.cells[e.N - 1];
      const r = routesOf(e.id);
      if (!r && out > 0) { e.acc = 0; return; }        // выход закрыт — продукт стоит
      for (let i = e.N - 1; i > 0; i--) e.cells[i] = e.cells[i - 1];
      e.cells[0] = 0;
      if (out > 0) r.forEach(([t, share]) => deliver(t, out * share));
    }
  }
  function sourceFlows(dt) {
    // завальная яма → конвейер 2
    const c2 = S.machines.conv_2.w;
    if (c2 > 0.05) {
      const kg = Math.min(L("pit"), FEED * c2 * dt);
      addLevel("pit", -kg); ELEM.conv_2.cells[0] += kg;
    }
    // оперативные бункеры → машины под ними
    const draw = (lvl, id, target) => {
      const w = S.machines[id].w;
      if (w < 0.05) return;
      const kg = Math.min(L(lvl), FEED * 1.15 * w * dt);
      addLevel(lvl, -kg); ELEM[target].cells[0] += kg;
    };
    draw("bo_1", "ksp", "ksp");
    draw("bo_2", "tor", "tor");
    draw("bo_3", "pnev", "pnev");
    // циклоны разгружаются шлюзовыми затворами
    [1, 2, 3].forEach((k) => {
      const w = S.machines["shl_" + k].w, c = "cyc_" + k;
      if (w < 0.05 || cyclone[c] <= 0) return;
      const kg = Math.min(cyclone[c], 0.4 * w * dt);
      cyclone[c] -= kg; ELEM["shl_" + k].cells[0] += kg;
    });
  }
  const ELEM_OF = { trier_1: "bt_14_1", trier_2_1: "bt_14_1", trier_1_2: "bt_14_2", trier_2_2: "bt_14_2" };
  function stepFlow(dt) {
    sourceFlows(dt);
    for (const e of Object.values(ELEM)) stepElement(e, dt);
    for (const e of Object.values(ELEM)) {
      let sum = 0;
      for (const x of e.cells) sum += x;
      e.fill = sum / (FEED * e.T * (e.dust ? 0.05 : 1));
      e.jam = e.dp && e.cells[0] > (FEED * e.T / e.N) * 4;
    }
    for (const [id, m] of Object.entries(S.machines)) {
      const e = ELEM[ELEM_OF[id] || id];
      m.mat = e ? Math.min(1, e.fill) : 0;
    }
  }

  /* ------------------------------------------------------- физика приводов */
  function stepMachines(dt) {
    for (const [id, m] of Object.entries(S.machines)) {
      const d = DEF[id];
      if (!d.fb) continue;                              // переключатели потока ниже
      const pch = PCH[id];
      if (pch) {
        V[pch.az] = m.sim.pch;
        V[pch.ready] = !m.sim.pch;
      }
      m.cmd = !!V[d.y];
      // Разрешение ПЧ (Y_*PCH* := NOT GEMER) снимается при общей аварии.
      const on = m.cmd && (!pch || (V[pch.ready] && V[pch.en]));
      m.w += ((on ? 1 : 0) - m.w) * Math.min(1, dt * (on ? 1.8 : 0.9));
      if (m.w < 0.004) m.w = 0;
      m.spin += m.w * dt;
      m.vib += ((m.w > 0.3 ? 1 : 0) - m.vib) * Math.min(1, dt * 4);
      m.running = m.w > 0.5;
      m.fault = !!V[d.da];
      if (m.cmd) { m.hours += dt / 3600; m.hoursTotal += dt / 3600; }
      // ДКС — импульсный датчик вращения; пропадание импульсов = отказ
      if (d.dks && m.w > 0.6 && !m.sim.dks) {
        m.dksPhase = (m.dksPhase + dt * 1.6) % 1;
        V[d.dks] = m.dksPhase < 0.5;
      }
      if (d.dsl1) V[d.dsl1] = m.sim.dsl1;
      if (d.dsl2) V[d.dsl2] = m.sim.dsl2;
      if (d.dp) V[d.dp] = m.sim.dp || !!(ELEM[id] && ELEM[id].jam);
      if (d.prot) V[d.prot] = m.sim.az;
    }
    // переключатели потока: ход привода и концевики
    plc.FLAPPERS.forEach((f) => {
      const m = S.machines[f.id];
      const up = !!V[f.y1] && !m.sim.jam, dn = !!V[f.y2] && !m.sim.jam;
      const travel = 3.5;                               // с на полный ход
      if (up) m.pos = Math.max(0, m.pos - dt / travel);
      if (dn) m.pos = Math.min(1, m.pos + dt / travel);
      m.cmd = !!V[f.y1] || !!V[f.y2];
      m.w = up || dn ? 1 : 0; m.spin += m.w * dt;
      m.running = up || dn;
      m.fault = !!V[f.da];
      V[f.pol1] = m.pos <= 0.02;
      V[f.pol2] = m.pos >= 0.98;
      V[f.prot] = m.sim.az;
    });
    // датчики верхнего уровня (вход LevelSensor = NOT x5_xx)
    V.lvl_bo_1 = S.levels.bo_1 >= 0.95;
    V.lvl_bo_2 = S.levels.bo_2 >= 0.95;
    V.lvl_bo_3 = S.levels.bo_3 >= 0.95;
    V.lvl_a = S.levels.V >= 0.98;
    V.lvl_bunk_1 = S.levels.A >= 0.98;
    V.lvl_bunk_2 = S.levels.B >= 0.98;
  }

  /* ------------------------------------------------------- сообщения */
  function ts() {
    const d = new Date();
    return [d.getHours(), d.getMinutes(), d.getSeconds()].map((n) => String(n).padStart(2, "0")).join(":");
  }
  function raise(msg, lvl, key) {
    const a = { ts: ts(), message: msg, lvl: lvl || "info", key: key || null, active: !!key };
    S.alarms.unshift(a); S.archive.unshift({ ...a });
    S.alarms = S.alarms.slice(0, 150); S.archive = S.archive.slice(0, 500);
  }
  const ESTOP_TEXT = {
    avar_stop: "Нажат аварийный стоп на шкафу",
    avar_stop_1: "Нажат аварийный стоп 1", avar_stop_2: "Нажат аварийный стоп 2",
    avar_stop_3: "Нажат аварийный стоп 3", avar_stop_4: "Нажат аварийный стоп 4",
    avar_stop_5: "Нажат аварийный стоп 5", fire_alarm: "Пожарная сигнализация",
    pusk: "Кнопка «ПУСК» на шкафу (x0_0) — входит в общую аварию по логике ПЛК",
    phase_control: "Авария контроля фаз",
  };
  const LEVEL_TEXT = {
    out_dvy_bo_1: "ДВУ БО-1 (поз. 6.1): бункер заполнен — подача заблокирована",
    out_dvy_bo_2: "ДВУ БО-2 (поз. 9): бункер заполнен — подача и ОП заблокированы",
    out_dvy_bo_3: "ДВУ БО-3 (поз. 16): бункер заполнен — подача, ТОР, БТ, нории 12/15 заблокированы",
    out_dvy_a: "Бункер В заполнен. Режим остановлен",
    out_dvy_bunk_1: "Бункер А заполнен. Режим остановлен",
    out_dvy_bunk_2: "Бункер Б заполнен. Режим остановлен",
  };
  function faultText(id) {
    const d = DEF[id], fb = plc.fbs[id];
    const out = [];
    if (!d.fb) {
      if (fb.err_swap) out.push("не дошёл до концевика за " + (V[d.timer] || 15) + " с");
      if (fb.err_conc) out.push("сработали оба концевика");
      if (V[d.prot]) out.push("защита привода");
      return out;
    }
    if (fb.err_dks) out.push("ДКС");
    if (fb.err_dp) out.push("подпор (ДП)");
    if (fb.err_dsl) out.push("сход ленты (ДСЛ)");
    if (fb.inputs && fb.inputs.protect) out.push(PCH[id] ? "защита / нет готовности ПЧ" : "защита двигателя");
    return out;
  }
  const prev = {};
  function watch() {
    const edge = (k, val) => { const r = val && !prev[k]; const f = !val && prev[k]; prev[k] = val; return r ? 1 : f ? -1 : 0; };
    const deactivate = (key) => S.alarms.forEach((a) => { if (a.key === key) a.active = false; });
    Object.keys(ESTOP_TEXT).forEach((k) => {
      const e = edge("in_" + k, !!V[k]);
      if (e > 0) raise(ESTOP_TEXT[k], "err", k);
      if (e < 0) deactivate(k);
    });
    Object.keys(LEVEL_TEXT).forEach((k) => {
      const e = edge(k, !!V[k]);
      if (e > 0) raise(LEVEL_TEXT[k], "warn", k);
      if (e < 0) deactivate(k);
    });
    for (const id of Object.keys(S.machines)) {
      const d = DEF[id], m = S.machines[id];
      const e = edge("da_" + id, !!V[d.da]);
      if (e > 0) raise(m.name + " (поз. " + m.poz + "): авария — " + (faultText(id).join(", ") || "причина не определена"), "err", "da_" + id);
      if (e < 0) deactivate("da_" + id);
      const t = edge("to_" + id, m.toHours > 0 && m.hours >= m.toHours);
      if (t > 0) raise(m.name + " (поз. " + m.poz + "): истекло время ТО", "warn", "to_" + id);
      if (t < 0) deactivate("to_" + id);
    }
    const mo = edge("mode", !!V.mode_och);
    if (mo > 0) raise("Режим очистки запущен: " + routeName(), "ok");
    if (mo < 0) raise(V.gemer ? "Режим очистки сброшен общей аварией" : "Режим очистки остановлен", "info");
    if (edge("pit_empty", S.levels.pit <= 0.001 && !!V.y_run_2) > 0) raise("Завальная яма пуста", "warn");
  }

  /* ------------------------------------------------------- цикл */
  let scanAcc = 0;
  function tick(dtReal) {
    if (!Number.isFinite(dtReal) || dtReal <= 0) return;
    scanAcc += Math.min(0.25, dtReal) * S.timeScale;
    const h = S.scanDt;
    let n = 0;
    while (scanAcc >= h && n < 1000) {
      scanAcc -= h; n++;
      S.clock += h;
      stepMachines(h);
      plc.scan(h);
      stepFlow(h);
    }
    watch();
  }

  /* ------------------------------------------------------- команды HMI */
  const ok = () => ({ ok: true });
  const fail = (error) => ({ ok: false, error });
  function routeName(o) {
    o = o || V;
    const t = o.with_trier ? "через БТ" + (o.use_1 && o.use_2 ? " 14.1 и 14.2" : o.use_1 ? " 14.1" : o.use_2 ? " 14.2" : " (блок не выбран)") : "мимо БТ";
    return t + ", " + (o.with_pnev ? "через СП" : "мимо СП") + (o.on_ost ? ", ОП вкл." : ", ОП выкл.") + (o.on_vor ? ", ворошитель вкл." : "");
  }
  const OPTIONS = ["with_trier", "use_1", "use_2", "with_pnev", "on_ost", "on_vor"];
  // Переключатели окна «Режим очистки» — RETAIN-переменные ПЛК, пишутся сразу.
  function setOption(key, val) {
    if (!OPTIONS.includes(key)) return fail("Неизвестный параметр");
    V[key] = !!val;
    return ok();
  }
  function modeStart() {
    if (V.gemer) return fail("Общая авария — ПЛК сбрасывает режим очистки");
    if (V.out_dvy_a || V.out_dvy_bunk_1 || V.out_dvy_bunk_2) return fail("Конечный бункер заполнен — ПЛК сбрасывает режим очистки");
    V.mode_och = true;
    return ok();
  }
  function modeStop() { V.mode_och = false; return ok(); }
  function resetErr() { V.reset_err = true; return ok(); }
  function setMute(on) { V.mute = !!on; return ok(); }
  function setInput(name, val) {
    if (name === "x0_8") { V.x0_8 = !!val; return ok(); }
    if (!(name in ESTOP_TEXT) || name === "phase_control") return fail("Неизвестный вход");
    V[name] = !!val;
    return ok();
  }
  function hmi(id, key, val) {
    const d = DEF[id];
    const map = { hand: d.hm, offNext: d.offNext, offDks: d.offDks, offDp: d.offDp, offDsl1: d.offDsl1, offDsl2: d.offDsl2 };
    if (!map[key]) return fail("Параметр недоступен для этого механизма");
    V[map[key]] = !!val;
    return ok();
  }
  function timerVar(id, which) {
    const d = DEF[id];
    return which === "start" ? d.tStart : which === "stop" ? d.tStop : d.timer;
  }
  function setTimer(id, which, sec) {
    const k = timerVar(id, which);
    const n = Math.round(Number(sec));
    if (!k || String(sec).trim() === "" || !Number.isFinite(n) || n < 0 || n > 3600) return fail("Допустимо 0…3600 с (0 — ПЛК подставит значение по умолчанию)");
    V[k] = n;
    return ok();
  }
  function getTimer(id, which) { return +V[timerVar(id, which)] || 0; }
  // ПУСК/СТОП окна механизма пишут бит HMI_BTN; ПЛК учитывает его только в ручном режиме.
  function pressStart(id) {
    const d = DEF[id];
    if (!V[d.hm]) return fail("ПУСК с панели работает только в ручном режиме");
    V[d.btn] = true;
    return ok();
  }
  function pressStop(id) { V[DEF[id].btn] = false; return ok(); }
  function pressPos(id, n) {
    const f = DEF[id];
    if (!V[f.hm]) return fail("Перевод с панели работает только в ручном режиме");
    V[n === 1 ? f.b1 : f.b2] = true;
    return ok();
  }
  function setSim(id, key, val) {
    const m = S.machines[id];
    if (!(key in m.sim)) return fail("Нет такой неисправности");
    m.sim[key] = !!val;
    return ok();
  }
  function setLocal(id, key, val) {
    const d = DEF[id];
    const name = key === "estop" ? LOCAL_STOP[id] : d.loc && d.loc[key];
    if (!name) return fail("Местный пост не предусмотрен");
    V[name] = !!val;
    return ok();
  }
  function localVar(id, key) { const d = DEF[id]; return key === "estop" ? LOCAL_STOP[id] : d.loc && d.loc[key]; }
  function setDvu(key, sec) {
    const l = plc.LEVELS.find((x) => x.id === key);
    const n = Math.round(Number(sec));
    if (!l || String(sec).trim() === "" || !Number.isFinite(n) || n < 0 || n > 3600) return fail("Допустимо 0…3600 с");
    V[l.timer] = n;
    return ok();
  }
  function resetHours(id) { S.machines[id].hours = 0; return ok(); }
  function setToHours(id, h) {
    const n = Number(h);
    if (String(h).trim() === "" || !Number.isFinite(n) || n < 0 || n > 100000) return fail("Недопустимое значение");
    S.machines[id].toHours = n; return ok();
  }
  function refillPit(pct) {
    S.levels.pit = Math.max(0, Math.min(1, (pct == null ? 100 : pct) / 100));
    raise("Завальная яма загружена до " + Math.round(S.levels.pit * 100) + " %", "ok");
    return ok();
  }
  const LEVEL_NAME = { V: "Бункер В", A: "Бункер А", B: "Бункер Б", bo_1: "БО-1", bo_2: "БО-2", bo_3: "БО-3", pit: "Завальная яма" };
  function unload(key) {
    if (!(key in S.levels)) return fail("Нет такой ёмкости");
    S.levels[key] = 0;
    raise(LEVEL_NAME[key] + " выгружен", "ok");
    return ok();
  }
  function setTimeScale(k) {
    if (![1, 2, 5, 10, 20].includes(+k)) return fail("Недопустимый масштаб");
    S.timeScale = +k; return ok();
  }

  /* ------------------------------------------------------- состояние для UI */
  function info(id) {
    const d = DEF[id], m = S.machines[id], fb = plc.fbs[id];
    const I = fb.inputs || {};
    let state;
    if (!d.fb) {
      state = m.fault ? "fault" : m.cmd ? "moving" : pos1(id) ? "pos1" : pos2(id) ? "pos2" : "mid";
    } else if (m.fault) state = "fault";
    else if (!fb.rr) state = "blocked";
    else if (V[d.hm]) state = m.cmd ? "hand-run" : "hand";
    else if (d.loc && V[d.loc.mode]) state = m.cmd ? "local-run" : "local";
    else if (m.cmd && fb.ton_stop.et > 0) state = "stopping";
    else if (m.cmd) state = "run";
    else if (fb.ton_start.et > 0) state = "starting";
    else if (I.cycle && !I.next) state = "wait";
    else state = "stop";
    const left = (t, which) => (t && t.et > 0 ? Math.max(0, getTimer(id, which) - t.et) : 0);
    return {
      state, fb, I,
      startLeft: left(fb.ton_start, "start"),
      stopLeft: left(fb.ton_stop, "stop"),
      faults: m.fault ? faultText(id) : [],
    };
  }
  function statusLine() {
    if (V.gemer) {
      const k = Object.keys(ESTOP_TEXT).find((x) => V[x]);
      return k ? ESTOP_TEXT[k] : "Общая авария";
    }
    if (V.mode_och) return "Режим очистки: " + routeName();
    if (Object.values(S.machines).some((m) => m.cmd)) return "Останов: механизмы отключаются по задержкам ПЛК";
    const act = S.alarms.find((a) => a.active);
    return act ? act.message : "Линия остановлена";
  }

  global.PLANT = {
    S, V, plc, W, H, ND, A, DUCTS, ELEM, DEF, PCH, LOCAL_STOP, CAP, ESTOP_TEXT, LEVEL_NAME, OPTIONS,
    tick, routeName, setOption, modeStart, modeStop, resetErr, setMute, setInput,
    hmi, setTimer, getTimer, pressStart, pressStop, pressPos, setSim, setLocal, localVar, setDvu,
    resetHours, setToHours, refillPit, unload, setTimeScale, info, statusLine, raise, ts, routesOf,
  };
})(typeof window !== "undefined" ? window : globalThis);
