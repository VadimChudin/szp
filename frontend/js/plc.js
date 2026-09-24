/* ЛПЗС «Родина» — эмуляция программы ПЛК.
   Логика перенесена из проекта CODESYS Rodina (FBD/LD), расшифровка —
   docs/plc/*.txt. Порядок цепей внутри блоков сохранён: он влияет на то,
   какие значения видны в пределах одного цикла.
   Идентификаторы CODESYS регистронезависимы, поэтому все имена здесь
   хранятся в нижнем регистре. */

(function (global) {
  "use strict";

  /* ------------------------------------------------ стандартные блоки */
  function TON() { return { et: 0, q: false }; }
  function ton(t, IN, pt, dt) {
    if (!IN) { t.et = 0; t.q = false; return false; }
    t.et = Math.min(pt, t.et + dt);
    t.q = t.et >= pt;
    return t.q;
  }
  function TOF() { return { et: 0, q: false, inPrev: false }; }
  function tof(t, IN, pt, dt) {
    if (IN) { t.q = true; t.et = 0; }
    else if (t.q) { t.et += dt; if (t.et >= pt) t.q = false; }
    return t.q;
  }
  function TP() { return { et: 0, q: false, prev: false }; }
  function tp(t, IN, pt, dt) {
    if (!t.q && IN && !t.prev) { t.q = true; t.et = 0; }
    if (t.q) { t.et += dt; if (t.et >= pt) t.q = false; }
    t.prev = IN;
    return t.q;
  }
  // Контакты LD с фронтом имеют собственную память у каждого экземпляра.
  function rtrig(o, key, v) { const r = v && !o[key]; o[key] = v; return r; }
  function ftrig(o, key, v) { const r = !v && o[key]; o[key] = v; return r; }

  /* ------------------------------------------------ пользовательские FB */
  // FUNCTION_BLOCK Transport — нории, шнеки, ленточный конвейер, шлюзы.
  function transport(fb, I, io, dt, G) {
    if (io.get("timer_start") <= 0) io.set("timer_start", 3);
    if (io.get("timer_stop") <= 0) io.set("timer_stop", 15);
    const button = io.get("button");
    // «Датчики»: используется RUN прошлого цикла
    ton(fb.ton_dks, fb.run && !I.off_dks && !I.dks, 5, dt);
    ton(fb.ton_dks_2, fb.run && !I.off_dks && I.dks, 5, dt);
    ton(fb.ton_dsl_1, fb.run && !I.off_dsl_1 && I.dsl_1, 5, dt);
    ton(fb.ton_dsl_2, fb.run && !I.off_dsl_2 && I.dsl_2, 5, dt);
    if (fb.ton_dsl_2.q || fb.ton_dsl_1.q) fb.err_dsl = true;
    if (fb.ton_dks.q || fb.ton_dks_2.q) fb.err_dks = true;
    if (I.dp && !I.off_dp) fb.err_dp = true;
    // «Сброс ошибок»
    if (G.reset_err) { fb.err_dsl = false; fb.err_dks = false; fb.err_dp = false; }
    // «Разрешение на работу»
    const n9 = !fb.err_dks && !fb.err_dp && !fb.err_dsl && !I.protect;
    fb.rr = n9 && !G.gemer && !I.m_stop && !I.m_stop_up;
    fb.da = !n9;
    // «Старт автоматического режима»
    const tq = ton(fb.ton_start, fb.rr && !I.hand_mode && I.cycle && I.next, io.get("timer_start"), dt);
    const bumpless = fb.rr && ftrig(fb, "_f_hand", I.hand_mode) && fb.run && I.cycle && I.next;
    if (tq || bumpless) fb.start = true;
    // «Безударный переход…»
    const imp = rtrig(fb, "_r_hand", I.hand_mode) && fb.run;
    fb.imphandon = imp;
    if (imp) fb.start = false;
    // «Импульс на включение бита в ручном»
    fb.r_trig_button = rtrig(fb, "_r_imp", fb.imphandon);
    // «Включение механизма»
    fb.run = fb.rr && ((((fb.start && !I.hand_mode) || (button && I.hand_mode)) && !I.m_mode) || (I.m_pusk && I.m_mode));
    // «Плавная останока» (так в проекте)
    ton(fb.ton_stop, fb.rr && !I.cycle && !I.prev, io.get("timer_stop"), dt);
    // «Сброс автоматического режима»
    if (fb.ton_stop.q || !fb.rr || !I.next || I.m_stop || I.m_stop_up) fb.start = false;
    // «Сброс ручного режима»
    fb.res_button = !I.hand_mode || (I.hand_mode && (!fb.rr || (!I.next && !I.off_next_m)));
  }
  function newTransport() {
    return { ton_dks: TON(), ton_dks_2: TON(), ton_dsl_1: TON(), ton_dsl_2: TON(),
      ton_start: TON(), ton_stop: TON(), err_dks: false, err_dp: false, err_dsl: false,
      rr: false, da: false, start: false, run: false, imphandon: false,
      r_trig_button: false, res_button: true, type: "transport" };
  }

  // FUNCTION_BLOCK FB_och — очистительные машины, битеры, вентиляторы.
  function fbOch(fb, I, io, dt, G) {
    if (io.get("timer_start") <= 0) io.set("timer_start", 3);
    if (io.get("timer_stop") <= 0) io.set("timer_stop", 15);
    const button = io.get("button");
    const n15 = !I.protect;
    fb.rr = n15 && !G.gemer && !I.m_stop;
    fb.da = !n15;
    const tq = ton(fb.ton_start, fb.rr && !I.hand_mode && I.cycle && I.next, io.get("timer_start"), dt);
    const bumpless = fb.rr && ftrig(fb, "_f_hand", I.hand_mode) && fb.run && I.cycle && I.next;
    if (tq || bumpless) fb.start = true;
    const imp = rtrig(fb, "_r_hand", I.hand_mode) && fb.run;
    fb.imphandon = imp;
    if (imp) fb.start = false;
    fb.r_trig_button = rtrig(fb, "_r_imp", fb.imphandon);
    fb.run = fb.rr && ((fb.start && !I.hand_mode) || (button && I.hand_mode));
    ton(fb.ton_stop, fb.rr && !I.cycle && !I.prev, io.get("timer_stop"), dt);
    if (fb.ton_stop.q || !fb.rr || !I.next || I.m_stop) fb.start = false;
    fb.res_button = !I.hand_mode || (I.hand_mode && (!fb.rr || (!I.next && !I.off_next_m)));
  }
  function newOch() {
    return { ton_start: TON(), ton_stop: TON(), rr: false, da: false, start: false, run: false,
      imphandon: false, r_trig_button: false, res_button: true, type: "och" };
  }

  // FUNCTION_BLOCK Flapper — переключатель потока ППМ-2.160.
  function flapper(fb, I, io, dt, G) {
    if (io.get("timer_err") <= 0) io.set("timer_err", 15);
    const b1 = io.get("button_pol_1"), b2 = io.get("button_pol_2");
    if (ton(fb.ton_err, (!I.pol_1 && fb.run_pol_1) || (!I.pol_2 && fb.run_pol_2), io.get("timer_err"), dt)) fb.err_swap = true;
    if (I.pol_2 && I.pol_1) fb.err_conc = true;
    if (G.reset_err) { fb.err_swap = false; fb.err_conc = false; }
    const n10 = !fb.err_swap && !I.protect && !fb.err_conc;
    fb.rr = n10 && !G.gemer;
    fb.da = !n10;
    fb.run_pol_1 = tof(fb.tof_pol_1, fb.rr && ((I.cycle_pol_1 && !I.hand_mode) || (I.hand_mode && b1) ||
      (I.m_pol_1 && !I.m_pol_2)) && !I.pol_1 && !fb.run_pol_2, 2, dt);
    fb.run_pol_2 = tof(fb.tof_pol_2, fb.rr && ((I.cycle_pol_2 && !I.hand_mode) || (I.hand_mode && b2) ||
      (I.m_pol_2 && !I.m_pol_1)) && !I.pol_2 && !fb.run_pol_1, 2, dt);
    fb.res_button_pol_1 = !I.hand_mode || (I.hand_mode && !fb.rr) || rtrig(fb, "_r_b2", b2) || I.pol_1 || I.m_pol_1 || I.m_pol_2;
    fb.res_button_pol_2 = !I.hand_mode || (I.hand_mode && !fb.rr) || rtrig(fb, "_r_b1", b1) || I.pol_2 || I.m_pol_1;
  }
  function newFlapper() {
    return { ton_err: TON(), tof_pol_1: TOF(), tof_pol_2: TOF(), err_swap: false, err_conc: false,
      rr: false, da: false, run_pol_1: false, run_pol_2: false,
      res_button_pol_1: true, res_button_pol_2: true, type: "flapper" };
  }

  // FUNCTION_BLOCK LevelSensor — ДВУ с задержкой на срабатывание и снятие.
  function levelSensor(fb, I, dt) {
    if (ton(fb.on, I.i_du, I.timer, dt)) fb.out = true;
    if (ton(fb.off, !I.i_du, I.timer, dt)) fb.out = false;
    return fb.out;
  }

  /* ------------------------------------------------ состав установки */
  // Экземпляры и подключение входов — программы Noria, Och_mech, Fans,
  // Conveyors, Aspiration_shluz, Flow_changer (docs/plc/*.txt).
  // tag — суффикс переменных HMI, y — выход RUN, da — выход DA.
  const DRIVES = [
    // ---- Noria (Transport)
    { id: "noria_4", fb: "transport", y: "y_noria_4", da: "hmi_da_noria_4", sens: "noria", tag: "4",
      btn: "hmi_btn_noria_4", hm: "hmi_hm_noria_4", offNext: "hmi_off_next_4",
      tStart: "hmi_timer_start_4", tStop: "hmi_timer_stop_4", prot: "in_az_noria_4",
      loc: { mode: "in_m_mode_4", pusk: "in_m_pusk_4", stop: "in_m_stop_4", stopUp: "in_m_stop_up_4" },
      cycle: (v) => v.mode_och,
      next: (v) => v.y_ost || (!v.on_ost && v.y_ksp_biter),
      prev: (v) => v.y_run_2 },
    { id: "noria_8", fb: "transport", y: "y_noria_8", da: "hmi_da_noria_8", sens: "noria", tag: "8",
      btn: "hmi_btn_noria_8", hm: "hmi_hm_noria_8", offNext: "hmi_off_next_8",
      tStart: "hmi_timer_start_8", tStop: "hmi_timer_stop_8", prot: "in_az_noria_8",
      loc: { mode: "in_m_mode_8", pusk: "in_m_pusk_8", stop: "in_m_stop_8", stopUp: "in_m_stop_up_8" },
      cycle: (v) => v.mode_och, next: (v) => v.y_fan_asp_1, prev: (v) => v.y_ksp },
    { id: "noria_12", fb: "transport", y: "y_noria_12", da: "hmi_da_noria_12", sens: "noria", tag: "12",
      btn: "hmi_btn_noria_12", hm: "hmi_hm_noria_12", offNext: "hmi_off_next_12",
      tStart: "hmi_timer_start_12", tStop: "hmi_timer_stop_12", prot: "in_az_noria_12",
      loc: { mode: "in_m_mode_12", pusk: "in_m_pusk_12", stop: "in_m_stop_12", stopUp: "in_m_stop_up_12" },
      cycle: (v) => v.mode_och && !v.out_dvy_bo_3 && !v.hmi_da_flow_1 &&
        ((v.in_fw_1_1 && v.with_trier) || (v.in_fw_2_1 && !v.with_trier)),
      next: (v) => v.y_fan_asp_2 && ((v.in_fw_2_1 && v.y_noria_15) || (v.in_fw_1_1 && (
        (v.use_1 && v.use_2 && v.y_trier_1_2 && v.y_trier_2_2 && v.y_trier_1 && v.y_trier_2) ||
        (v.use_1 && !v.use_2 && v.y_trier_1 && v.y_trier_2) ||
        (v.use_2 && v.y_trier_1_2 && v.y_trier_2_2 && !v.use_1)))),
      prev: (v) => v.y_tor },
    { id: "noria_15", fb: "transport", y: "y_noria_15", da: "hmi_da_noria_15", sens: "noria", tag: "15",
      btn: "hmi_btn_noria_15", hm: "hmi_hm_noria_15", offNext: "hmi_off_next_15",
      tStart: "hmi_timer_start_15", tStop: "hmi_timer_stop_15", prot: "in_az_noria_15",
      loc: { mode: "in_m_mode_15", pusk: "in_m_pusk_15", stop: "in_m_stop_15", stopUp: "in_m_stop_up_15" },
      cycle: (v) => v.mode_och && !v.out_dvy_bo_3 && ((!v.with_pnev && v.in_fw_2_2) || (v.with_pnev && v.in_fw_1_2)),
      next: (v) => v.y_fan_asp_3,
      prev: (v) => (v.y_noria_12 && v.in_fw_1_1) || (v.use_1 && v.y_trier_2) || (v.use_2 && v.y_trier_2_2) },
    // Нория 20 в проекте ПЛК использует таймеры нории 23 (HMI_timer_*_23).
    { id: "noria_20", fb: "transport", y: "y_noria_20", da: "hmi_da_noria_20", sens: "noria", tag: "20",
      btn: "hmi_btn_noria_20", hm: "hmi_hm_noria_20", offNext: "hmi_off_next_20",
      tStart: "hmi_timer_start_23", tStop: "hmi_timer_stop_23", prot: "in_az_noria_20",
      loc: { mode: "in_m_mode_20", pusk: "in_m_pusk_20", stop: "in_m_stop_20", stopUp: "in_m_stop_up_20" },
      cycle: (v) => v.mode_och, next: () => true,
      prev: (v) => (v.y_noria_15 && v.in_fw_2_2) || (v.in_fw_1_2 && v.y_pnev) },
    { id: "noria_23", fb: "transport", y: "y_noria_23", da: "hmi_da_noria_23", sens: "noria", tag: "23",
      btn: "hmi_btn_noria_23", hm: "hmi_hm_noria_23", offNext: "hmi_off_next_23",
      tStart: "hmi_timer_start_23", tStop: "hmi_timer_stop_23", prot: "in_az_noria_23",
      loc: { mode: "in_m_mode_23", pusk: "in_m_pusk_23", stop: "in_m_stop_23", stopUp: "in_m_stop_up_23" },
      cycle: (v) => v.mode_och, next: () => true, prev: (v) => v.y_conv_22_1 },
    { id: "noria_24", fb: "transport", y: "y_noria_24", da: "hmi_da_noria_24", sens: "noria", tag: "24",
      btn: "hmi_btn_noria_24", hm: "hmi_hm_noria_24", offNext: "hmi_off_next_24",
      tStart: "hmi_timer_start_24", tStop: "hmi_timer_stop_24", prot: "in_az_noria_24",
      loc: { mode: "in_m_mode_24", pusk: "in_m_pusk_24", stop: "in_m_stop_24", stopUp: "in_m_stop_up_24" },
      cycle: (v) => v.mode_och, next: () => true, prev: (v) => v.y_conv_22_2 },

    // ---- Och_mech (FB_och)
    { id: "vor", fb: "och", y: "y_vor", da: "hmi_da_vor", btn: "hmi_bnt_vor", hm: "hmi_hm_vor",
      offNext: "hmi_off_next_vor", tStart: "hmi_timer_start_vor", tStop: "hmi_timer_stop_vor",
      prot: "in_az_vor", cycle: (v) => v.mode_och && v.on_vor, next: (v) => v.y_run_2, prev: () => false },
    { id: "ost", fb: "och", y: "y_ost", da: "hmi_da_ost", btn: "hmi_btn_ost", hm: "hmi_hm_ost",
      offNext: "hmi_off_next_ost", tStart: "hmi_timer_start_ost", tStop: "hmi_timer_stop_ost",
      prot: "in_az_ost", mstop: (v) => v.in_stop_ost,
      cycle: (v) => !v.out_dvy_bo_2 && v.mode_och && v.on_ost, next: (v) => v.y_ksp, prev: (v) => v.y_noria_4 },
    { id: "ksp_biter", fb: "och", y: "y_ksp_biter", da: "hmi_da_biter", btn: "hmi_btn_biter", hm: "hmi_hm_biter",
      offNext: "hmi_off_next_biter", tStart: "hmi_timer_start_biter", tStop: "hmi_timer_stop_biter",
      pch: "biter", mstop: (v) => v.in_stop_biter,
      protect: (v) => !v.in_stop_biter && v.in_az_pch_ksp,
      cycle: (v) => v.mode_och && v.in_pch_ready_biter, next: (v) => v.y_ksp,
      prev: (v) => v.y_ost || (v.on_ost && v.y_noria_4) },
    { id: "ksp", fb: "och", y: "y_ksp", da: "hmi_da_ksp", btn: "hmi_btn_ksp", hm: "hmi_hm_ksp",
      offNext: "hmi_off_next_ksp", tStart: "hmi_timer_start_ksp", tStop: "hmi_timer_stop_ksp",
      prot: "in_az_ksp", cycle: (v) => v.mode_och,
      next: (v) => v.y_noria_8 && v.y_conv_22_1 && v.y_conv_22_2, prev: (v) => v.y_ksp_biter },
    { id: "tor", fb: "och", y: "y_tor", da: "hmi_da_tor", btn: "hmi_btn_tor", hm: "hmi_hm_tor",
      offNext: "hmi_off_next_tor", tStart: "hmi_timer_start_tor", tStop: "hmi_timer_stop_tor",
      prot: "in_tor_az", mstop: (v) => v.in_m_stop_tor,
      cycle: (v) => v.mode_och && !v.out_dvy_bo_3, next: (v) => v.y_noria_12 && v.y_conv_22_2,
      prev: (v) => v.y_biter_tor },
    // Битер ТОР в проекте делит «Не отслеживать след. мех.» с ТОР (HMI_off_next_TOR).
    { id: "tor_biter", fb: "och", y: "y_biter_tor", da: "hmi_da_tor_biter", btn: "hmi_btn_tor_biter",
      hm: "hmi_hm_tor_biter", offNext: "hmi_off_next_tor", tStart: "hmi_timer_start_tor_biter",
      tStop: "hmi_timer_stop_tor_biter", pch: "tor", mstop: (v) => v.in_m_stop_tor,
      protect: (v) => v.in_tor_pch_az || !v.in_pch_tor_ready,
      cycle: (v) => !v.out_dvy_bo_3 && v.mode_och, next: (v) => v.y_tor, prev: () => false },
    { id: "trier_1", fb: "och", y: "y_trier_1", da: "hmi_da_trier_1", btn: "hmi_btn_trier_1", hm: "hmi_hm_trier_1",
      offNext: "hmi_off_next_trier_1", tStart: "hmi_timer_start_trier_1_1", tStop: "hmi_timer_stop_trier_1_1",
      pch: "trier_1", mstop: (v) => v.in_stop_trier_1,
      protect: (v) => (!v.in_stop_trier_1 && v.in_az_pch_trier_1) || !v.in_pch_ready_trier_1,
      cycle: (v) => v.in_pch_ready_trier_1 && !v.out_dvy_bo_3 && v.mode_och && v.use_1,
      next: (v) => v.y_trier_2 && v.y_fan_asp_2, prev: (v) => v.y_noria_12 && v.in_fw_1_1 },
    { id: "trier_2_1", fb: "och", y: "y_trier_2", da: "hmi_da_trier_2_1", btn: "hmi_btn_trier_2_1",
      hm: "hmi_hm_trier_2_1", offNext: "hmi_off_next_trier_2_1", tStart: "hmi_timer_start_trier_2_1",
      tStop: "hmi_timer_stop_trier_2_1", pch: "trier_2", mstop: (v) => v.in_stop_trier_2 || v.in_stop_trier_1,
      protect: (v) => (!v.in_stop_trier_1 && v.in_az_pch_trier_2) || !v.in_pch_ready_trier_2,
      cycle: (v) => v.use_1 && !v.out_dvy_bo_3 && v.mode_och,
      next: (v) => v.y_noria_15 && v.y_conv_22_4, prev: (v) => v.y_trier_1 },
    { id: "trier_1_2", fb: "och", y: "y_trier_1_2", da: "hmi_da_trier_1_2", btn: "hmi_btn_trier_1_2",
      hm: "hmi_hm_trier_1_2", offNext: "hmi_off_next_trier_1_2", tStart: "hmi_timer_start_trier_1_2",
      tStop: "hmi_timer_stop_trier_1_2", pch: "trier_1_2", mstop: (v) => v.in_stop_trier_1_2 || v.in_stop_trier_2,
      protect: (v) => (!v.in_stop_trier_1_2 && v.in_az_pch_trier_1_2) || !v.in_pch_ready_trier_1_2,
      cycle: (v) => v.use_2 && !v.out_dvy_bo_3 && v.in_pch_ready_trier_1_2 && v.mode_och,
      next: (v) => v.y_trier_2_2, prev: (v) => v.y_noria_12 && v.in_fw_1_1 },
    { id: "trier_2_2", fb: "och", y: "y_trier_2_2", da: "hmi_da_trier_2_2", btn: "hmi_btn_trier_2_2",
      hm: "hmi_hm_trier_2_2", offNext: "hmi_off_next_trier_2_2", tStart: "hmi_timer_start_trier_2_2",
      tStop: "hmi_timer_stop_trier_2_2", pch: "trier_2_2", mstop: (v) => v.in_stop_trier_2_2 || v.in_stop_trier_1_2,
      protect: (v) => (!v.in_stop_trier_2_2 && v.in_az_pch_trier_2_2) || !v.in_pch_ready_trier_2_2,
      cycle: (v) => v.use_2 && !v.out_dvy_bo_3 && v.mode_och && v.in_pch_ready_trier_2_2,
      next: (v) => v.y_noria_15 && v.y_conv_22_4, prev: (v) => v.y_trier_1_2 },
    { id: "pnev", fb: "och", y: "y_pnev", da: "hmi_da_pnev", btn: "hmi_btn_pnev", hm: "hmi_hm_pnev",
      offNext: "hmi_off_next_pnev", tStart: "hmi_timer_start_pnev", tStop: "hmi_timer_stop_pnev",
      pch: "pnev", mstop: (v) => v.in_stop_pnev,
      protect: (v) => (!v.in_stop_pnev && v.in_az_pch_pnev) || !v.in_pch_ready_pnev,
      cycle: (v) => v.in_pch_ready_pnev && v.mode_och && v.with_pnev,
      next: (v) => v.y_fan_pnev && v.y_conv_22_3 && v.y_noria_20 && v.y_fan_asp_3,
      prev: (v) => v.y_noria_15 && v.in_fw_1_2 },

    // ---- Fans (FB_och)
    { id: "fan_pnev", fb: "och", y: "y_fan_pnev", da: "hmi_da_fan_pnev", btn: "hmi_btn_fan_pnev", hm: "hmi_hm_fan_pnev",
      offNext: "hmi_off_next_fan_pnev", tStart: "hmi_timer_start_fan_pnev", tStop: "hmi_timer_stop_fan_pnev",
      prot: "in_az_fan_pnev", cycle: (v) => v.mode_och && v.with_pnev, next: (v) => v.y_noria_20, prev: (v) => v.y_pnev },
    { id: "fan_asp_1", fb: "och", y: "y_fan_asp_1", da: "hmi_da_fan_asp_1", btn: "hmi_btn_fan_asp_1", hm: "hmi_hm_fan_asp_1",
      offNext: "hmi_off_next_fan_asp_1", tStart: "hmi_timer_start_fan_asp_1", tStop: "hmi_timer_stop_fan_asp_1",
      prot: "in_az_fan_asp_1", cycle: (v) => v.mode_och, next: (v) => v.y_shl_1, prev: (v) => v.y_ksp || v.y_noria_8 },
    { id: "fan_asp_2", fb: "och", y: "y_fan_asp_2", da: "hmi_da_fan_asp_2", btn: "hmi_btn_fan_asp_2", hm: "hmi_hm_fan_asp_2",
      offNext: "hmi_off_next_fan_asp_2", tStart: "hmi_timer_start_fan_asp_2", tStop: "hmi_timer_stop_fan_asp_2",
      prot: "in_az_fan_asp_2", cycle: (v) => v.mode_och, next: (v) => v.y_shl_2,
      prev: (v) => v.y_noria_12 || v.y_tor || (v.y_trier_1 && v.y_trier_2) || (v.y_trier_1_2 && v.y_trier_2_2) },
    { id: "fan_asp_3", fb: "och", y: "y_fan_asp_3", da: "hmi_da_fan_asp_3", btn: "hmi_btn_fan_asp_3", hm: "hmi_hm_fan_asp_3",
      offNext: "hmi_off_next_fan_asp_3", tStart: "hmi_timer_start_fan_asp_3", tStop: "hmi_timer_stop_fan_asp_3",
      prot: "in_az_fan_asp_3", cycle: (v) => v.mode_och, next: (v) => v.y_shl_3, prev: (v) => v.y_noria_15 || v.y_pnev },

    // ---- Conveyors (Transport без ДСЛ)
    { id: "conv_2", fb: "transport", y: "y_run_2", da: "hmi_da_2", sens: "conv", tag: "2", pch: "2",
      btn: "hmi_btn_2", hm: "hmi_hm_2", offNext: "hmi_off_next_2", tStart: "hmi_timer_start_2", tStop: "hmi_timer_stop_2",
      offDks: "hmi_off_dks_2", offDp: "hmi_off_dp_2", dks: "in_dks_2", dp: "in_dp_2",
      loc: { mode: "in_m_mode_2", pusk: "in_m_pusk_2", stop: "in_m_stop_2", stopUp: "in_m_stop_end_2" },
      protect: (v) => !v.in_pch_ready_2 || v.in_az_pch_2,
      cycle: (v) => v.in_pch_ready_2 && !v.out_dvy_bo_1 && !v.out_dvy_bo_2 && !v.out_dvy_bo_3 && v.mode_och && !v.hmi_da_tor_biter,
      next: (v) => v.y_noria_4, prev: () => false },
    { id: "conv_22_1", fb: "transport", y: "y_conv_22_1", da: "hmi_da_conv_22_1", sens: "conv", tag: "22_1",
      btn: "hmi_btn_conv_22_1", hm: "hmi_hm_conv_22_1", offNext: "hmi_off_conv_22_1",
      tStart: "hmi_timer_start_22_1", tStop: "hmi_timer_stop_22_1", prot: "in_az_conv_22_1",
      loc: { mode: "in_m_mode_22_1", pusk: "in_m_pusk_22_1", stop: "in_m_stop_22_1", stopUp: "in_m_stop_end_22_1" },
      cycle: (v) => v.mode_och, next: (v) => v.y_noria_23, prev: (v) => v.y_ksp },
    { id: "conv_22_2", fb: "transport", y: "y_conv_22_2", da: "hmi_da_conv_22_2", sens: "conv", tag: "22_2",
      btn: "hmi_btn_conv_22_2", hm: "hmi_hm_conv_22_2", offNext: "hmi_off_conv_22_2",
      tStart: "hmi_timer_start_22_2", tStop: "hmi_timer_stop_22_2", prot: "in_az_conv_22_2",
      loc: { mode: "in_m_mode_22_2", pusk: "in_m_pusk_22_2", stop: "in_m_stop_22_2", stopUp: "in_m_stop_end_22_2" },
      cycle: (v) => v.mode_och, next: (v) => v.y_noria_24, prev: (v) => v.y_ksp || v.y_tor },
    { id: "conv_22_3", fb: "transport", y: "y_conv_22_3", da: "hmi_da_conv_22_3", sens: "conv", tag: "22_3",
      btn: "hmi_btn_conv_22_3", hm: "hmi_hm_conv_22_3", offNext: "hmi_off_conv_22_3",
      tStart: "hmi_timer_start_22_3", tStop: "hmi_timer_stop_22_3", prot: "in_az_conv_22_3",
      loc: { mode: "in_m_mode_22_3", pusk: "in_m_pusk_22_3", stop: "in_m_stop_22_3", stopUp: "in_m_stop_end_22_3" },
      cycle: (v) => v.mode_och && (v.with_trier || v.with_pnev), next: (v) => v.y_conv_22_2,
      prev: (v) => v.y_conv_22_4 || v.y_pnev },
    { id: "conv_22_4", fb: "transport", y: "y_conv_22_4", da: "hmi_da_conv_22_4", sens: "conv", tag: "22_4",
      btn: "hmi_btn_conv_22_4", hm: "hmi_hm_conv_22_4", offNext: "hmi_off_conv_22_4",
      tStart: "hmi_timer_start_22_4", tStop: "hmi_timer_stop_22_4", prot: "in_az_conv_22_4",
      loc: { mode: "in_m_mode_22_4", pusk: "in_m_pusk_22_4", stop: "in_m_stop_22_4", stopUp: "in_m_stop_end_22_4" },
      cycle: (v) => v.mode_och && v.with_trier, next: (v) => v.y_conv_22_3,
      prev: (v) => v.y_trier_2 || v.y_trier_2_2 },
    { id: "conv_22_5", fb: "transport", y: "y_conv_22_5", da: "hmi_da_conv_22_5", sens: "conv", tag: "22_5",
      btn: "hmi_btn_conv_22_5", hm: "hmi_hm_conv_22_5", offNext: "hmi_off_conv_22_5",
      tStart: "hmi_timer_start_22_5", tStop: "hmi_timer_stop_22_5", prot: "in_az_conv_22_5",
      loc: { mode: "in_m_mode_22_5", pusk: "in_m_pusk_22_5", stop: "in_m_stop_22_5", stopUp: "in_m_stop_end_22_5" },
      cycle: (v) => v.mode_och, next: (v) => v.y_conv_22_1,
      prev: (v) => v.y_fan_asp_1 || v.y_fan_asp_2 || v.y_fan_asp_3 },

    // ---- Aspiration_shluz (Transport, только ДКС)
    { id: "shl_1", fb: "transport", y: "y_shl_1", da: "hmi_da_shl_1", sens: "shl", btn: "hmi_btn_shl_1", hm: "hmi_hm_shl_1",
      offNext: "hmi_off_next_shl_1", tStart: "hmi_timer_start_shl_1", tStop: "hmi_timer_stop_shl_1",
      prot: "in_az_shl_1", dks: "in_dks_shl_1", offDks: "hmi_off_dks_shl_1", errDks: "hmi_err_dks_shl_1",
      cycle: (v) => v.mode_och, next: (v) => v.y_conv_22_5, prev: (v) => v.y_fan_asp_1 },
    { id: "shl_2", fb: "transport", y: "y_shl_2", da: "hmi_da_shl_2", sens: "shl", btn: "hmi_btn_shl_2", hm: "hmi_hm_shl_2",
      offNext: "hmi_off_next_shl_2", tStart: "hmi_timer_start_shl_2", tStop: "hmi_timer_stop_shl_2",
      prot: "in_az_shl_2", dks: "in_dks_shl_2", offDks: "hmi_off_dks_shl_2", errDks: "hmi_err_dks_shl_2",
      cycle: (v) => v.mode_och, next: (v) => v.y_conv_22_5, prev: (v) => v.y_fan_asp_2 },
    { id: "shl_3", fb: "transport", y: "y_shl_3", da: "hmi_da_shl_3", sens: "shl", btn: "hmi_btn_shl_3", hm: "hmi_hm_shl_3",
      offNext: "hmi_off_next_shl_3", tStart: "hmi_timer_start_shl_3", tStop: "hmi_timer_stop_shl_3",
      prot: "in_az_shl_3", dks: "in_dks_shl_3", offDks: "hmi_off_dks_shl_3", errDks: "hmi_err_dks_shl_3",
      cycle: (v) => v.mode_och, next: (v) => v.y_conv_22_5, prev: (v) => v.y_fan_asp_3 },
  ];

  // Имена датчиков и флагов HMI для блоков Transport.
  DRIVES.forEach((d) => {
    if (d.fb !== "transport") return;
    if (d.sens === "noria") {
      const n = d.tag, k = "noria_" + n;
      Object.assign(d, {
        dks: "in_dks_" + k, dp: "in_dp_" + k, dsl1: "in_dsl_1_" + k, dsl2: "in_dsl_2_" + k,
        offDks: "hmi_off_dks_" + n, offDp: "hmi_off_dp_" + n, offDsl1: "hmi_off_dsl_1_" + n, offDsl2: "hmi_off_dsl_2_" + n,
        errDks: "hmi_err_dks_" + n, errDp: "hmi_err_dp_" + n, errDsl: "hmi_err_dsl_" + n,
      });
    } else if (d.sens === "conv" && d.tag !== "2") {
      const n = d.tag;
      Object.assign(d, {
        dks: "in_dks_conv_" + n, dp: "in_dp_conv_" + n, offDks: "hmi_off_dks_" + n, offDp: "hmi_off_dp_" + n,
        errDks: "hmi_err_dks_" + n, errDp: "hmi_err_dp_" + n,
      });
    } else if (d.tag === "2") {
      Object.assign(d, { errDks: "hmi_err_dks_2", errDp: "hmi_err_dp_2" });
    }
  });

  const FLAPPERS = [
    { id: "flow_1", da: "hmi_da_flow_1", prot: "in_protect_flow_1", pol1: "in_fw_1_1", pol2: "in_fw_2_1",
      y1: "y_flow_1_1", y2: "y_flow_2_1", hm: "hmi_hm_fw_1", timer: "hmi_timer_fw_1",
      b1: "hmi_btn_fw_1_1", b2: "hmi_btn_fw_2_1", errSwap: "hmi_err_swap_1", errConc: "hmi_err_conc_1",
      c1: (v) => v.mode_och && v.with_trier, c2: (v) => v.mode_och && !v.with_trier },
    { id: "flow_2", da: "hmi_da_flow_2", prot: "in_protect_flow_2", pol1: "in_fw_1_2", pol2: "in_fw_2_2",
      y1: "y_flow_1_2", y2: "y_flow_2_2", hm: "hmi_hm_fw_2", timer: "hmi_timer_fw_2",
      b1: "hmi_btn_fw_1_2", b2: "hmi_btn_fw_2_2", errSwap: "hmi_err_swap_2", errConc: "hmi_err_conc_2",
      c1: (v) => v.mode_och && v.with_pnev, c2: (v) => v.mode_och && !v.with_pnev },
  ];

  // DU: вход LevelSensor = NOT x5_xx, то есть TRUE — уровень достигнут.
  const LEVELS = [
    { id: "bo_1", out: "out_dvy_bo_1", input: "lvl_bo_1", timer: "hmi_tm_dvy_bo_1" },
    { id: "bo_2", out: "out_dvy_bo_2", input: "lvl_bo_2", timer: "hmi_tm_dvy_bo_2" },
    { id: "bo_3", out: "out_dvy_bo_3", input: "lvl_bo_3", timer: "hmi_tm_dvy_bo_3" },
    { id: "A", out: "out_dvy_a", input: "lvl_a", timer: "hmi_tm_dvy_bunk_23" },
    { id: "bunk_1", out: "out_dvy_bunk_1", input: "lvl_bunk_1", timer: "hmi_tm_dvy_torba" },
    { id: "bunk_2", out: "out_dvy_bunk_2", input: "lvl_bunk_2", timer: "hmi_tm_dny_torba" },
  ];

  const ESTOP_INPUTS = ["pusk", "avar_stop", "avar_stop_1", "avar_stop_2", "avar_stop_3",
    "avar_stop_4", "avar_stop_5", "fire_alarm"];
  const PCH_OUT = ["y_run_pch_2", "y_pch_biter", "y_run_pch_tor", "y_pch_trier_1", "y_pch_trier_1_2",
    "y_pch_pnev", "y_pch_trier_2_2", "y_pch_trier_2"];

  /* ------------------------------------------------ контроллер */
  function createPLC() {
    const v = Object.create(null);
    const fbs = {};
    const levels = {};
    const G = { gemer: false, reset_err: false };
    const misc = { ton_res_err: TON(), blink: { t: 0 }, predpusk: TP(), tp0: TP() };
    const get = (k) => !!v[k];

    DRIVES.forEach((d) => { fbs[d.id] = d.fb === "transport" ? newTransport() : newOch(); });
    FLAPPERS.forEach((f) => { fbs[f.id] = newFlapper(); });
    LEVELS.forEach((l) => { levels[l.id] = { on: TON(), off: TON(), out: false }; });

    // Исходное состояние: всё исправно, режим не запущен.
    v.x0_8 = true;                       // реле контроля фаз в норме
    v.with_trier = true; v.use_1 = true; v.use_2 = true; v.with_pnev = true;
    v.on_ost = true; v.on_vor = false;
    LEVELS.forEach((l) => { v[l.timer] = 15; });

    function ioFor(names) {
      return {
        get: (k) => (names[k] ? (typeof v[names[k]] === "number" ? v[names[k]] : +!!v[names[k]]) : 0),
        set: (k, val) => { if (names[k]) v[names[k]] = val; },
      };
    }
    function ioBool(names) {
      const io = ioFor(names);
      return { get: (k) => (k === "button" || k.startsWith("button_") ? !!v[names[k]] : io.get(k)), set: io.set };
    }

    function scanDrive(d, dt) {
      const fb = fbs[d.id];
      const I = {
        cycle: !!d.cycle(v), next: !!d.next(v), prev: !!d.prev(v),
        hand_mode: get(d.hm), protect: d.protect ? !!d.protect(v) : get(d.prot),
        off_next_m: get(d.offNext),
        m_stop: d.mstop ? !!d.mstop(v) : (d.loc ? get(d.loc.stop) : false),
      };
      const io = ioBool({ timer_start: d.tStart, timer_stop: d.tStop, button: d.btn });
      if (d.fb === "transport") {
        Object.assign(I, {
          dks: get(d.dks), dp: get(d.dp), dsl_1: get(d.dsl1), dsl_2: get(d.dsl2),
          off_dks: get(d.offDks), off_dp: get(d.offDp), off_dsl_1: get(d.offDsl1), off_dsl_2: get(d.offDsl2),
          m_mode: d.loc ? get(d.loc.mode) : false, m_pusk: d.loc ? get(d.loc.pusk) : false,
          m_stop_up: d.loc ? get(d.loc.stopUp) : false,
        });
        transport(fb, I, io, dt, G);
        if (d.errDks) v[d.errDks] = fb.err_dks;
        if (d.errDp) v[d.errDp] = fb.err_dp;
        if (d.errDsl) v[d.errDsl] = fb.err_dsl;
      } else {
        fbOch(fb, I, io, dt, G);
      }
      fb.inputs = I;
      v[d.da] = fb.da;
      v[d.y] = fb.run;
      // Катушки на выходе блока: сначала R (RES_BUTTON), затем S (R_TRIG_BUTTON).
      if (fb.res_button) v[d.btn] = false;
      if (fb.r_trig_button) v[d.btn] = true;
    }

    function scanFlapper(f, dt) {
      const fb = fbs[f.id];
      const I = { protect: get(f.prot), pol_1: get(f.pol1), pol_2: get(f.pol2),
        cycle_pol_1: !!f.c1(v), cycle_pol_2: !!f.c2(v), hand_mode: get(f.hm), m_pol_1: false, m_pol_2: false };
      const io = ioBool({ timer_err: f.timer, button_pol_1: f.b1, button_pol_2: f.b2 });
      flapper(fb, I, io, dt, G);
      fb.inputs = I;
      v[f.da] = fb.da; v[f.y1] = fb.run_pol_1; v[f.y2] = fb.run_pol_2;
      if (fb.res_button_pol_1) v[f.b1] = false;
      if (fb.res_button_pol_2) v[f.b2] = false;
      v[f.errSwap] = fb.err_swap; v[f.errConc] = fb.err_conc;
    }

    function scan(dt) {
      // DU
      LEVELS.forEach((l) => { v[l.out] = levelSensor(levels[l.id], { i_du: get(l.input), timer: +v[l.timer] || 0 }, dt); });
      // Do_Alarm_logic
      v.do_alarm = DRIVES.some((d) => v[d.da]) || FLAPPERS.some((f) => v[f.da]);
      const b = misc.blink;
      if (v.do_alarm) { b.t = (b.t + dt) % 3; v.lamp = b.t < 1; } else { b.t = 0; v.lamp = false; }
      const pre = tp(misc.predpusk, rtrig(misc, "_r_mode", !!v.mode_och), 2, dt);
      v.sirena = (v.lamp && !v.mute) || misc.tp0.q || pre;
      v.phase_control = v.phase_control || false;
      G.gemer = v.gemer = ESTOP_INPUTS.some(get) || get("phase_control");
      const dvyEdge = ["out_dvy_bo_1", "out_dvy_bo_2", "out_dvy_bo_3", "out_dvy_a", "out_dvy_bunk_1", "out_dvy_bunk_2"]
        .map((k) => rtrig(misc, "_r_" + k, get(k))).some(Boolean);
      tp(misc.tp0, dvyEdge, 3, dt);
      // Modes
      if (!v.x0_8) v.phase_control = true;
      if (v.reset_err) v.phase_control = false;
      if (G.gemer || v.out_dvy_a || v.out_dvy_bunk_1 || v.out_dvy_bunk_2) v.mode_och = false;
      G.reset_err = !!v.reset_err;
      if (ton(misc.ton_res_err, !!v.reset_err, 1, dt)) v.reset_err = false;
      PCH_OUT.forEach((k) => { v[k] = !G.gemer; });
      // Программы механизмов в порядке задачи
      DRIVES.forEach((d) => scanDrive(d, dt));
      FLAPPERS.forEach((f) => scanFlapper(f, dt));
      G.reset_err = false;
    }

    return { v, fbs, levels, scan, DRIVES, FLAPPERS, LEVELS, ESTOP_INPUTS };
  }

  const api = { createPLC, DRIVES, FLAPPERS, LEVELS, ESTOP_INPUTS, _fb: { transport, fbOch, flapper, levelSensor, ton, tof, tp } };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  global.PLC = api;
})(typeof window !== "undefined" ? window : globalThis);
