'use strict';
// Проверка эмуляции ПЛК и модели установки. Запуск: node tests/test_plc.js
// Зависимостей нет. Ожидаемые значения выписаны из расшифровки проекта
// CODESYS (docs/plc/*.txt), а не сгенерированы из кода эмулятора.
const path = require('node:path');
const assert = require('node:assert/strict');

const ROOT = path.join(__dirname, '..', 'frontend', 'js');
let passed = 0;
const results = [];
function test(name, fn) {
  try { fn(); passed++; results.push(['ok', name]); }
  catch (e) { results.push(['FAIL', name, e.message]); }
}
function fresh() {
  for (const k of Object.keys(require.cache)) if (k.startsWith(ROOT)) delete require.cache[k];
  delete globalThis.PLC; delete globalThis.PLANT;
  globalThis.window = globalThis;
  require(path.join(ROOT, 'plc.js'));
  require(path.join(ROOT, 'plant.js'));
  globalThis.PLANT.S.autoTrucks = false;             // автотранспорт проверяется отдельно
  return globalThis.PLANT;
}
const run = (P, sec) => { for (let i = 0; i < Math.round(sec / 0.05); i++) P.tick(0.05); };

/* ---------------------------------------------------- функциональные блоки */
const { _fb: FB } = require(path.join(ROOT, 'plc.js'));
function transportRig() {
  const store = { timer_start: 0, timer_stop: 0, button: false };
  const io = { get: (k) => store[k], set: (k, v) => { store[k] = v; } };
  const fb = { ton_dks: { et: 0, q: false }, ton_dks_2: { et: 0, q: false }, ton_dsl_1: { et: 0, q: false },
    ton_dsl_2: { et: 0, q: false }, ton_start: { et: 0, q: false }, ton_stop: { et: 0, q: false },
    err_dks: false, err_dp: false, err_dsl: false, start: false, run: false };
  const I = { dks: false, dp: false, dsl_1: false, dsl_2: false, off_dks: false, off_dp: false, off_dsl_1: false,
    off_dsl_2: false, cycle: false, next: false, prev: false, m_mode: false, m_pusk: false, m_stop: false,
    m_stop_up: false, hand_mode: false, protect: false, off_next_m: false };
  const G = { gemer: false, reset_err: false };
  let t = 0;
  const step = (sec, pulse) => {
    for (let i = 0; i < Math.round(sec / 0.01); i++) {
      t += 0.01;
      if (pulse) I.dks = Math.floor(t * 2) % 2 === 0;
      FB.transport(fb, I, io, 0.01, G);
    }
  };
  return { fb, I, G, store, step };
}

test('Transport: пустые задержки ПЛК заменяет на 3 с и 15 с', () => {
  const r = transportRig(); r.step(0.01);
  assert.equal(r.store.timer_start, 3); assert.equal(r.store.timer_stop, 15);
});
test('Transport: пуск через TIMER_START при CYCLE и NEXT', () => {
  const r = transportRig(); r.I.cycle = true; r.I.next = true;
  r.step(2.9, true); assert.equal(r.fb.run, false);
  r.step(0.2, true); assert.equal(r.fb.run, true);
});
test('Transport: пропадание NEXT останавливает сразу', () => {
  const r = transportRig(); r.I.cycle = true; r.I.next = true; r.step(3.2, true);
  r.I.next = false; r.step(0.02, true); assert.equal(r.fb.run, false);
});
test('Transport: останов через TIMER_STOP после снятия CYCLE и PREV', () => {
  const r = transportRig(); r.I.cycle = true; r.I.next = true; r.step(3.2, true);
  r.I.cycle = false; r.I.prev = true; r.step(30, true); assert.equal(r.fb.run, true, 'PREV держит механизм');
  r.I.prev = false; r.step(14.8, true); assert.equal(r.fb.run, true);
  r.step(0.3, true); assert.equal(r.fb.run, false);
});
test('Transport: ДКС без импульсов 5 с — защёлка ERR_DKS до RESET_ERR', () => {
  const r = transportRig(); r.I.cycle = true; r.I.next = true; r.step(3.2, true);
  r.I.dks = true; r.step(4.8); assert.equal(r.fb.err_dks, false);
  r.step(0.3); assert.equal(r.fb.err_dks, true); assert.equal(r.fb.run, false); assert.equal(r.fb.da, true);
  r.step(1); assert.equal(r.fb.err_dks, true, 'ошибка держится без сброса');
  r.G.reset_err = true; r.step(0.01); r.G.reset_err = false; assert.equal(r.fb.err_dks, false);
});
test('Transport: ДП срабатывает сразу, даже на стоящем механизме; Выкл. ДП блокирует', () => {
  const r = transportRig(); r.I.dp = true; r.step(0.02); assert.equal(r.fb.err_dp, true);
  const q = transportRig(); q.I.dp = true; q.I.off_dp = true; q.step(0.5); assert.equal(q.fb.err_dp, false);
});
test('Transport: ручной режим — RUN от BUTTON, RES_BUTTON без NEXT', () => {
  const r = transportRig(); r.I.hand_mode = true; r.store.button = true; r.step(0.02);
  assert.equal(r.fb.run, true); assert.equal(r.fb.res_button, true, 'без NEXT кнопка сбрасывается');
  r.I.off_next_m = true; r.step(0.02); assert.equal(r.fb.res_button, false, 'Не отслеживать след. мех.');
});
test('Transport: местный режим — RUN от местного пуска', () => {
  const r = transportRig(); r.I.m_mode = true; r.I.m_pusk = true; r.step(0.02); assert.equal(r.fb.run, true);
  r.I.m_stop = true; r.step(0.02); assert.equal(r.fb.run, false, 'местный стоп снимает RR');
});
test('Flapper: не дошёл до концевика за TIMER_ERR — ERR_SWAP', () => {
  const store = { timer_err: 0, button_pol_1: false, button_pol_2: false };
  const io = { get: (k) => store[k], set: (k, v) => { store[k] = v; } };
  const fb = { ton_err: { et: 0, q: false }, tof_pol_1: { et: 0, q: false }, tof_pol_2: { et: 0, q: false }, err_swap: false, err_conc: false };
  const I = { protect: false, pol_1: false, pol_2: true, cycle_pol_1: true, cycle_pol_2: false, hand_mode: false, m_pol_1: false, m_pol_2: false };
  for (let i = 0; i < 1490; i++) FB.flapper(fb, I, io, 0.01, { gemer: false, reset_err: false });
  assert.equal(fb.run_pol_1, true); assert.equal(fb.err_swap, false); assert.equal(store.timer_err, 15);
  for (let i = 0; i < 20; i++) FB.flapper(fb, I, io, 0.01, { gemer: false, reset_err: false });
  assert.equal(fb.err_swap, true); assert.equal(fb.run_pol_1, true, 'TOF держит выход ещё 2 с');
});
test('LevelSensor: задержка на срабатывание и на снятие', () => {
  const fb = { on: { et: 0, q: false }, off: { et: 0, q: false }, out: false };
  for (let i = 0; i < 99; i++) FB.levelSensor(fb, { i_du: true, timer: 1 }, 0.01);
  assert.equal(fb.out, false);
  for (let i = 0; i < 2; i++) FB.levelSensor(fb, { i_du: true, timer: 1 }, 0.01);
  assert.equal(fb.out, true);
  for (let i = 0; i < 99; i++) FB.levelSensor(fb, { i_du: false, timer: 1 }, 0.01);
  assert.equal(fb.out, true);
  for (let i = 0; i < 2; i++) FB.levelSensor(fb, { i_du: false, timer: 1 }, 0.01);
  assert.equal(fb.out, false);
});

/* ---------------------------------------------------- маршруты режима очистки */
const BASE = ['conv_2', 'noria_4', 'ksp_biter', 'ksp', 'fan_asp_1', 'shl_1', 'noria_8', 'tor_biter', 'tor',
  'fan_asp_2', 'shl_2', 'noria_12', 'noria_15', 'fan_asp_3', 'shl_3', 'noria_20', 'conv_22_1', 'conv_22_2',
  'conv_22_5', 'noria_23', 'noria_24'];
function expected(o) {
  const s = new Set(BASE);
  if (o.on_ost) s.add('ost');
  if (o.on_vor) s.add('vor');
  if (o.with_trier) { ['trier_1', 'trier_2_1', 'trier_1_2', 'trier_2_2', 'conv_22_4', 'conv_22_3'].forEach((x) => s.add(x)); }
  if (o.with_pnev) { ['pnev', 'fan_pnev', 'conv_22_3'].forEach((x) => s.add(x)); }
  return s;
}
const ROUTES = [
  { with_trier: true, with_pnev: true, on_ost: true, on_vor: false },
  { with_trier: false, with_pnev: true, on_ost: true, on_vor: false },
  { with_trier: true, with_pnev: false, on_ost: false, on_vor: true },
  { with_trier: false, with_pnev: false, on_ost: true, on_vor: false },
];
for (const o of ROUTES) {
  const name = (o.with_trier ? 'через БТ' : 'мимо БТ') + ', ' + (o.with_pnev ? 'через СП' : 'мимо СП') + (o.on_ost ? ', ОП' : '') + (o.on_vor ? ', ворошитель' : '');
  test('Маршрут ' + name + ': пуск, продукт до бункера В, штатный останов', () => {
    const P = fresh(), S = P.S, V = P.V;
    Object.entries(o).forEach(([k, v]) => P.setOption(k, v));
    run(P, 0.5);
    assert.equal(P.modeStart().ok, true);
    const order = [];
    for (let i = 0; i < 2400; i++) {
      P.tick(0.05);
      for (const [id, m] of Object.entries(S.machines)) if (m.cmd && !order.includes(id) && P.DEF[id].fb) order.push(id);
    }
    const exp = expected(o);
    assert.deepEqual(new Set(order), exp, 'набор механизмов: ' + order.join(','));
    // Хвост линии стартует первым, подача (конвейер 2) — последней среди основного тракта.
    assert.ok(order.indexOf('noria_20') < order.indexOf('noria_15'));
    assert.ok(order.indexOf('noria_15') < order.indexOf('noria_12'));
    assert.ok(order.indexOf('noria_4') < order.indexOf('conv_2'));
    assert.ok(order.indexOf('ksp') < order.indexOf('ksp_biter'), 'битер ждёт МУЗ (NEXT = Y_ksp)');
    // заслонки в положении маршрута
    assert.equal(!!V.in_fw_1_1, o.with_trier); assert.equal(!!V.in_fw_2_1, !o.with_trier);
    assert.equal(!!V.in_fw_1_2, o.with_pnev); assert.equal(!!V.in_fw_2_2, !o.with_pnev);
    const v0 = S.levels.V, a0 = S.levels.A, b0 = S.levels.B;
    run(P, 60);
    assert.ok(S.levels.V > v0 + 0.002, 'чистое зерно поступает в бункер В');
    assert.ok(S.levels.A > a0, 'отходы и аспирация — в бункер А');
    if (o.with_trier || o.with_pnev) assert.ok(S.levels.B > b0, 'отходы БТ/СП — в бункер Б');
    assert.deepEqual(Object.values(S.machines).filter((m) => m.fault).map((m) => m.id), []);
    // штатный останов: голова линии отключается первой
    P.modeStop();
    const stopOrder = [];
    for (let i = 0; i < 4000; i++) {
      P.tick(0.05);
      for (const [id, m] of Object.entries(S.machines)) if (!m.cmd && order.includes(id) && !stopOrder.includes(id)) stopOrder.push(id);
    }
    assert.equal(stopOrder.length, order.length, 'всё остановлено');
    assert.ok(stopOrder.indexOf('conv_2') < stopOrder.indexOf('noria_4'));
    assert.ok(stopOrder.indexOf('noria_12') < stopOrder.indexOf('noria_20'));
  });
}

/* ---------------------------------------------------- аварии и блокировки */
function started() {
  const P = fresh();
  run(P, 0.5); P.modeStart(); run(P, 90);
  return P;
}
test('Аварийный стоп: GEMER сбрасывает режим и сразу снимает все выходы', () => {
  const P = started(), V = P.V, S = P.S;
  assert.ok(Object.values(S.machines).some((m) => m.cmd));
  P.setInput('avar_stop_3', true); run(P, 0.1);
  assert.equal(V.gemer, true); assert.equal(V.mode_och, false);
  assert.deepEqual(Object.values(S.machines).filter((m) => m.cmd).map((m) => m.id), []);
  assert.equal(P.modeStart().ok, false, 'пуск при общей аварии отклоняется');
});
test('Кнопка ПУСК на шкафу входит в GEMER (как в программе ПЛК)', () => {
  const P = fresh(); P.setInput('pusk', true); run(P, 0.1);
  assert.equal(P.V.gemer, true);
});
test('Контроль фаз: защёлка PHASE_CONTROL до RESET_ERR', () => {
  const P = fresh(); P.setInput('x0_8', false); run(P, 0.1);
  assert.equal(P.V.phase_control, true);
  P.setInput('x0_8', true); run(P, 0.5); assert.equal(P.V.phase_control, true);
  P.resetErr(); run(P, 0.1); assert.equal(P.V.phase_control, false);
});
test('ДКС нории 20: авария и мгновенный останов вышестоящих по NEXT', () => {
  const P = started(), S = P.S;
  P.setSim('noria_20', 'dks', true); run(P, 6);
  assert.equal(S.machines.noria_20.fault, true);
  assert.equal(S.machines.noria_20.cmd, false);
  assert.equal(S.machines.fan_pnev.cmd, false, 'NEXT вентилятора СП = нория 20');
  assert.equal(S.machines.pnev.cmd, false, 'NEXT пневмостола включает норию 20');
  assert.ok(S.alarms.some((a) => a.active && /Нория Н3-В\.10\.10.*ДКС/.test(a.message)));
  P.setSim('noria_20', 'dks', false); P.resetErr(); run(P, 0.2);
  assert.equal(S.machines.noria_20.fault, false);
});
test('Защита вентилятора АС-1: авария вентилятора, норию 8 останавливает NEXT', () => {
  const P = started(), S = P.S;
  P.setSim('fan_asp_1', 'az', true); run(P, 0.2);
  assert.equal(S.machines.fan_asp_1.fault, true);
  assert.equal(S.machines.noria_8.cmd, false);
  P.setSim('fan_asp_1', 'az', false); run(P, 0.2);
  assert.equal(S.machines.fan_asp_1.fault, false, 'PROTECT не защёлкивается');
});
test('ДВУ бункера В: через задержку ДВУ режим очистки сбрасывается', () => {
  const P = started(), S = P.S, V = P.V;
  P.setDvu('A', 5); S.levels.V = 0.99; run(P, 4.5);
  assert.equal(V.mode_och, true);
  run(P, 1); assert.equal(V.out_dvy_a, true); assert.equal(V.mode_och, false);
  assert.ok(S.alarms.some((a) => a.message === 'Бункер В заполнен. Режим остановлен'));
});
test('ДВУ БО-3: снимает CYCLE у подачи, ТОР, БТ, норий 12 и 15 — они останавливаются', () => {
  const P = started(), S = P.S, V = P.V;
  P.setDvu('bo_3', 1);
  const hold = (sec) => { for (let i = 0; i < sec * 20; i++) { S.levels.bo_3 = 1; P.tick(0.05); } };
  hold(1.2);
  assert.equal(V.out_dvy_bo_3, true);
  hold(120);   // каскад: битер ТОР → ТОР → нория 12 → БТ N1 → БТ N2 → нория 15, по 15 с
  ['conv_2', 'tor', 'noria_12', 'trier_1', 'noria_15'].forEach((id) => assert.equal(S.machines[id].cmd, false, id));
  assert.equal(V.mode_och, true, 'режим не сбрасывается');
});
test('Ручной режим: ПУСК с панели только в ручном, без NEXT кнопка сбрасывается', () => {
  const P = fresh(), S = P.S, V = P.V;
  run(P, 0.2);
  assert.equal(P.pressStart('noria_8').ok, false);
  P.hmi('noria_8', 'hand', true); P.pressStart('noria_8'); run(P, 0.1);
  assert.equal(S.machines.noria_8.cmd, false, 'NEXT (АС-1) не в работе — HMI_BTN сброшен');
  P.hmi('noria_8', 'offNext', true); P.pressStart('noria_8'); run(P, 0.1);
  assert.equal(S.machines.noria_8.cmd, true);
  P.pressStop('noria_8'); run(P, 0.1);
  assert.equal(S.machines.noria_8.cmd, false);
  assert.equal(V.hmi_btn_noria_8, false);
});
test('Ручной режим переключателя 13.1: перевод кнопками', () => {
  const P = fresh(), S = P.S, V = P.V;
  run(P, 0.2);
  assert.equal(V.in_fw_1_1, true);
  V.hmi_hm_fw_1 = true; P.pressPos('flow_1', 2); run(P, 6);
  assert.equal(V.in_fw_2_1, true); assert.equal(S.machines.flow_1.fault, false);
});
test('Заклинивание заслонки: ERR_SWAP через время переключения', () => {
  const P = fresh(), S = P.S;
  P.setOption('with_pnev', false); P.setSim('flow_2', 'jam', true);
  run(P, 0.2); P.modeStart(); run(P, 16);
  assert.equal(S.machines.flow_2.fault, true);
  assert.equal(S.machines.noria_15.cmd, false, 'CYCLE нории 15 требует положения заслонки');
});
test('Местный режим нории 4 без местного пуска: нория стоит, подача остановлена по NEXT', () => {
  const P = started(), S = P.S;
  P.setLocal('noria_4', 'mode', true); run(P, 0.1);
  assert.equal(S.machines.noria_4.cmd, false);
  assert.equal(S.machines.conv_2.cmd, false);
  P.setLocal('noria_4', 'pusk', true); run(P, 0.1);
  assert.equal(S.machines.noria_4.cmd, true, 'местный пуск в местном режиме');
});
test('Датчик подпора нории 4: авария сразу, даже без работы', () => {
  const P = fresh(), S = P.S;
  P.setSim('noria_4', 'dp', true); run(P, 0.1);
  assert.equal(S.machines.noria_4.fault, true);
  P.hmi('noria_4', 'offDp', true); P.setSim('noria_4', 'dp', false); P.resetErr(); run(P, 0.1);
  assert.equal(S.machines.noria_4.fault, false);
});
test('Задержки: 0 в поле ПЛК заменяет значением по умолчанию, ввод вне диапазона отклоняется', () => {
  const P = fresh();
  assert.equal(P.setTimer('noria_4', 'start', -1).ok, false);
  assert.equal(P.setTimer('noria_4', 'start', '').ok, false);
  assert.equal(P.setTimer('noria_4', 'start', 0).ok, true); run(P, 0.1);
  assert.equal(P.getTimer('noria_4', 'start'), 3);
  assert.equal(P.getTimer('noria_20', 'start'), P.getTimer('noria_23', 'start'), 'нория 20 делит таймеры с норией 23');
});

/* ---------------------------------------------------- автотранспорт */
test('Автомобиль приезжает, разгружается в яму и уезжает', () => {
  const P = fresh(), S = P.S;
  S.levels.pit = 0.1;
  assert.equal(P.callTruck('truck_in').ok, true);
  assert.equal(P.callTruck('truck_in').ok, false, 'повторный вызов отклоняется');
  run(P, 4); assert.equal(S.trucks.truck_in.phase, 'work');
  run(P, 15);
  assert.ok(S.levels.pit > 0.45, 'яма пополнена: ' + S.levels.pit.toFixed(2));
  run(P, 5); assert.equal(S.trucks.truck_in.phase, 'away');
});
test('Автовывоз из бункера В не даёт сработать ДВУ, пока идёт очистка', () => {
  const P = fresh(), S = P.S;
  S.autoTrucks = true; S.levels.V = 0.9;
  run(P, 20);
  assert.ok(S.levels.V < 0.5, 'бункер В выгружен: ' + S.levels.V.toFixed(2));
  assert.equal(P.V.out_dvy_a, false);
});
test('Автоподвоз: яма пополняется сама, когда меньше 30 %', () => {
  const P = fresh(), S = P.S;
  S.autoTrucks = true; S.levels.pit = 0.2;
  run(P, 20);
  assert.ok(S.levels.pit > 0.5);
});

for (const r of results) console.log(r[0].padEnd(4), r[1] + (r[2] ? '\n     ' + r[2] : ''));
const failed = results.filter((r) => r[0] !== 'ok').length;
console.log(`\n${passed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
