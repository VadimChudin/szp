/* ЛПЗС «Родина» — интерфейс оператора: окна панели HMI, таблицы, журнал.
   Все команды идут через PLANT и пишут те же переменные, что панель
   оператора пишет в ПЛК (HMI_*, Mode_och, RESET_ERR…). */

(function () {
  "use strict";

  const P = window.PLANT, R = window.RENDER;
  const S = P.S, V = P.V;
  const $ = (s, r) => (r || document).querySelector(s);
  const $$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

  function h(tag, attrs, ...kids) {
    const e = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v == null || v === false) continue;
      if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
      else if (k === "class") e.className = v;
      else if (k === "html") e.innerHTML = v;
      else e.setAttribute(k, v === true ? "" : v);
    }
    for (const c of kids.flat()) if (c != null && c !== false) e.append(c.nodeType ? c : document.createTextNode(String(c)));
    return e;
  }

  let toastT = 0;
  function toast(msg, bad) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = "toast show" + (bad ? " bad" : "");
    clearTimeout(toastT);
    toastT = setTimeout(() => { t.className = "toast" + (bad ? " bad" : ""); }, 2800);
  }
  const run = (r, okMsg) => { if (r && !r.ok) toast(r.error, true); else if (okMsg) toast(okMsg); save(); return r; };

  /* ------------------------------------------------ названия и порядок */
  const ORDER = ["conv_2", "vor", "noria_4", "ost", "ksp_biter", "ksp", "fan_asp_1", "shl_1", "noria_8", "tor_biter", "tor",
    "fan_asp_2", "shl_2", "noria_12", "flow_1", "trier_1", "trier_2_1", "trier_1_2", "trier_2_2", "noria_15", "flow_2",
    "pnev", "fan_pnev", "fan_asp_3", "shl_3", "noria_20", "conv_22_5", "conv_22_1", "noria_23", "conv_22_4", "conv_22_3",
    "conv_22_2", "noria_24"];
  const RELATED = {
    conv_2: ["vor"], vor: ["conv_2"], ksp: ["ksp_biter", "fan_asp_1"], ksp_biter: ["ksp"], tor: ["tor_biter", "fan_asp_2"],
    tor_biter: ["tor"], fan_asp_1: ["shl_1"], fan_asp_2: ["shl_2"], fan_asp_3: ["shl_3"], shl_1: ["fan_asp_1"],
    shl_2: ["fan_asp_2"], shl_3: ["fan_asp_3"], pnev: ["fan_pnev", "fan_asp_3"], fan_pnev: ["pnev"],
    trier_1: ["trier_2_1"], trier_2_1: ["trier_1"], trier_1_2: ["trier_2_2"], trier_2_2: ["trier_1_2"],
    noria_12: ["flow_1"], noria_15: ["flow_2"],
  };
  const SHARED_NOTE = {
    noria_20: "В проекте ПЛК нория 20 использует задержки нории 23 (HMI_timer_start_23 / HMI_timer_stop_23).",
    noria_23: "Эти задержки в проекте ПЛК общие с норией 20.",
    tor_biter: "«Не отслеживать след. мех.» у битера ТОР — общий флаг с ТОР (HMI_off_next_TOR).",
  };
  const title = (id) => S.machines[id].name + " · поз. " + S.machines[id].poz;
  const STATE = {
    fault: ["АВАРИЯ", "bad"], blocked: ["Нет готовности", "bad"], hand: ["Ручной режим", "info"],
    "hand-run": ["Ручной · работа", "info"], local: ["Местный режим", "info"], "local-run": ["Местный · работа", "info"],
    stopping: ["Останов", "warn"], run: ["Работа", "ok"], starting: ["Пуск", "warn"], wait: ["Ждёт след. механизм", "warn"],
    stop: ["Остановлен", ""], pos1: ["", "ok"], pos2: ["", "ok"], moving: ["Переключение", "warn"], mid: ["Не в положении", "warn"],
  };
  const FLAP_POS = { flow_1: ["На триеры (14.1/14.2)", "На норию 15"], flow_2: ["На пневмостол (через БО-3)", "На норию 20"] };
  function stateText(id) {
    const inf = P.info(id);
    let [t, cls] = STATE[inf.state] || ["—", ""];
    if (inf.state === "starting") t = "Пуск через " + Math.ceil(inf.startLeft) + " с";
    if (inf.state === "stopping") t = "Останов через " + Math.ceil(inf.stopLeft) + " с";
    if (inf.state === "fault" && inf.faults.length) t = "АВАРИЯ: " + inf.faults.join(", ");
    if (inf.state === "blocked") t = V.gemer ? "Общая авария" : "Нажат местный стоп";
    if (inf.state === "pos1") t = FLAP_POS[id][0];
    if (inf.state === "pos2") t = FLAP_POS[id][1];
    return [t, cls, inf];
  }
  const ledClass = (id) => {
    const s = P.info(id).state;
    return s === "fault" || s === "blocked" ? "fault" : s === "run" || s === "hand-run" || s === "local-run" || s === "pos1" || s === "pos2"
      ? (s.startsWith("hand") || s.startsWith("local") ? "hand" : "run")
      : s === "starting" || s === "stopping" || s === "wait" || s === "moving" || s === "mid" ? "wait" : s === "hand" || s === "local" ? "hand" : "";
  };

  /* ------------------------------------------------ окна */
  let dlg = null;
  function openDlg(o) {
    const root = $("#modal-root");
    root.innerHTML = "";
    const ups = [];
    const body = h("div", { class: "dlg-b" });
    const box = h("div", { class: "dlg" + (o.wide ? " wide" : ""), role: "dialog", "aria-modal": "true", "aria-label": o.title },
      h("div", { class: "dlg-h" },
        h("button", { class: "dlg-x", type: "button", "aria-label": "Закрыть", onclick: closeDlg }, "✕"),
        h("div", { class: "dlg-title", id: "dlg-title" }, o.title, o.sub ? h("small", {}, o.sub) : null)),
      body);
    root.append(box);
    root.classList.add("open");
    dlg = { id: o.id, ups, box };
    o.build(body, (fn) => ups.push(fn));
    ups.forEach((f) => f());
    const first = box.querySelector(".dlg-b button, .dlg-b input");
    (first || box.querySelector(".dlg-x")).focus({ preventScroll: true });
    R.setSelected(o.node || null);
  }
  function closeDlg() {
    $("#modal-root").classList.remove("open");
    $("#modal-root").innerHTML = "";
    dlg = null;
    R.setSelected(null);
  }
  $("#modal-root").addEventListener("mousedown", (e) => { if (e.target.id === "modal-root") closeDlg(); });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape" && dlg) closeDlg(); });

  // Элементы окна HMI
  const row = (label, ...right) => h("div", { class: "row" }, h("span", {}, label), ...right);
  function toggle(get, set, up, disabled) {
    const b = h("button", { class: "toggle", type: "button", role: "switch" }, h("i"));
    b.addEventListener("click", () => { run(set(!get())); refresh(); });
    up(() => {
      const on = !!get();
      b.classList.toggle("on", on); b.setAttribute("aria-checked", on);
      if (disabled) b.disabled = !!disabled();
    });
    return b;
  }
  function num(get, set, up, unit) {
    const i = h("input", { type: "number", min: 0, step: 1 });
    const commit = () => { const r = set(i.value); if (r && !r.ok) { toast(r.error, true); i.value = get(); } else save(); };
    i.addEventListener("change", commit);
    i.addEventListener("keydown", (e) => { if (e.key === "Enter") { commit(); i.blur(); } });
    up(() => { if (document.activeElement !== i) i.value = Math.round(get() * 100) / 100; });
    return h("span", {}, i, h("span", { class: "unit" }, unit));
  }
  const val = (get, up, fmt) => { const s = h("span", { class: "val" }); up(() => { s.textContent = fmt ? fmt(get()) : get(); }); return s; };
  function lampb(label, get, up, kind) {
    const s = h("span", { class: "lampb", title: label }, label);
    up(() => { const v = get(); s.className = "lampb" + (v ? " " + (kind || "on") : ""); });
    return s;
  }
  function refresh() { if (dlg) dlg.ups.forEach((f) => f()); }

  /* ------------------------------------------------ окно привода */
  function openDrive(id) {
    const d = P.DEF[id], m = S.machines[id];
    if (!d.fb) return openFlapper(id);
    openDlg({
      id, title: m.name, sub: "Поз. " + m.poz + " · блок " + (d.fb === "transport" ? "Transport" : "FB_och") + " · выход " + d.y.toUpperCase(),
      node: nodeOfDrive(id),
      build(b, up) {
        const st = h("div", { class: "row" }, h("span", { class: "status" }));
        up(() => {
          const [t, cls] = stateText(id);
          st.className = "row" + (cls === "bad" ? " bad" : cls === "ok" ? " good" : cls === "warn" ? " warn" : "");
          st.firstChild.textContent = t;
        });
        b.append(st);
        // живые входы блока ПЛК
        const I = () => P.plc.fbs[id].inputs || {};
        b.append(h("div", { class: "cond-grid" },
          lampb("CYCLE", () => I().cycle, up), lampb("NEXT", () => I().next, up), lampb("PREV", () => I().prev, up),
          lampb("RR", () => P.plc.fbs[id].rr, up), lampb("RUN", () => V[d.y], up)));
        b.append(h("div", { class: "note" }, "CYCLE — режим/разрешение, NEXT — следующий механизм в работе, PREV — предыдущий в работе, RR — готовность."));
        (RELATED[id] || []).forEach((rid) => {
          b.append(h("div", { class: "row link", tabindex: 0, onclick: () => openAny(rid), onkeydown: (e) => { if (e.key === "Enter") openAny(rid); } },
            h("span", {}, "Окно: " + S.machines[rid].name), h("span", {}, "»")));
        });
        const SENS = [["offDks", "Выкл. ДКС", "err_dks"], ["offDp", "Выкл. ДП", "err_dp"], ["offDsl1", "Выкл. ДСЛ 1", "err_dsl"], ["offDsl2", "Выкл. ДСЛ 2", "err_dsl"]];
        SENS.forEach(([k, label, err]) => {
          if (!d[k]) return;
          b.append(row(label, lampb("ошибка", () => P.plc.fbs[id][err], up, "bad"),
            toggle(() => V[d[k]], (v) => P.hmi(id, k, v), up)));
        });
        b.append(row("Задержка перед запуском", num(() => P.getTimer(id, "start"), (v) => P.setTimer(id, "start", v), up, "с.")));
        b.append(row("Задержка перед остановом", num(() => P.getTimer(id, "stop"), (v) => P.setTimer(id, "stop", v), up, "с.")));
        if (SHARED_NOTE[id]) b.append(h("div", { class: "note" }, "⚠ " + SHARED_NOTE[id]));
        b.append(row("Время ТО", num(() => m.toHours, (v) => P.setToHours(id, v), up, "ч.")));
        b.append(row("Текущее время работы", val(() => m.hours, up, (x) => x.toFixed(2)), h("span", { class: "unit" }, "ч.")));
        b.append(row("Общее время работы", val(() => m.hoursTotal, up, (x) => x.toFixed(1)), h("span", { class: "unit" }, "ч.")));
        b.append(row("Сброс часов ТО", h("button", { class: "btn-sw", type: "button", onclick: () => run(P.resetHours(id), "Часы ТО сброшены") }, "Сброс")));
        b.append(row("Не отслеживать след. мех.", toggle(() => V[d.offNext], (v) => P.hmi(id, "offNext", v), up)));
        b.append(row("Ручной режим", toggle(() => V[d.hm], (v) => P.hmi(id, "hand", v), up)));
        const go = h("button", { class: "big-go", type: "button", onclick: () => run(P.pressStart(id)) }, "ПУСК");
        const stop = h("button", { class: "big-stop", type: "button", onclick: () => run(P.pressStop(id)) }, "СТОП");
        up(() => {
          const hand = !!V[d.hm];
          go.disabled = !hand; stop.disabled = !hand;
          go.title = hand ? "HMI_BTN := TRUE" : "Кнопки работают в ручном режиме (как в ПЛК)";
          stop.title = go.title;
        });
        b.append(h("div", { class: "btn-row" }, go, stop));
        b.append(h("div", { class: "note" }, "В автоматическом режиме механизм запускается ПЛК: после появления CYCLE и NEXT и выдержки задержки пуска. Останавливается через задержку останова после пропадания CYCLE и PREV, либо сразу при пропадании NEXT."));
        b.append(simSection(id, up));
      },
    });
  }

  // Неисправности и местный пост — входы ПЛК со стороны установки.
  function simSection(id, up) {
    const d = P.DEF[id], m = S.machines[id];
    const inner = h("div", { class: "inner" });
    const simRow = (label, key) => inner.append(row(label, toggle(() => m.sim[key], (v) => P.setSim(id, key, v), up)));
    if (d.prot) simRow("Сработал автомат защиты (" + d.prot.toUpperCase() + ")", "az");
    if (P.PCH[id]) simRow("Авария ПЧ / нет готовности (" + P.PCH[id].ready.toUpperCase() + ")", "pch");
    if (d.dks) simRow("ДКС: нет импульсов (обрыв/пробуксовка)", "dks");
    if (d.dsl1) simRow("ДСЛ 1: сход ленты внизу", "dsl1");
    if (d.dsl2) simRow("ДСЛ 2: сход ленты вверху", "dsl2");
    if (d.dp) simRow("ДП: подпор", "dp");
    const lv = (key) => P.localVar(id, key);
    if (d.loc) {
      inner.append(h("div", { class: "sect" }, "Местный пост"));
      inner.append(row("Местный режим (" + lv("mode").toUpperCase() + ")", toggle(() => V[lv("mode")], (v) => P.setLocal(id, "mode", v), up)));
      const hold = h("button", { class: "btn-sw", type: "button", title: "Удерживайте — как кнопку на посту" }, "Пуск (удерж.)");
      const on = () => P.setLocal(id, "pusk", true), off = () => P.setLocal(id, "pusk", false);
      hold.addEventListener("pointerdown", on); hold.addEventListener("pointerup", off); hold.addEventListener("pointerleave", off);
      up(() => hold.classList.toggle("on", !!V[lv("pusk")]));
      inner.append(row("Местный пуск (" + lv("pusk").toUpperCase() + ")", hold));
      inner.append(row("Местный стоп нажат (" + lv("stop").toUpperCase() + ")", toggle(() => V[lv("stop")], (v) => P.setLocal(id, "stop", v), up)));
      inner.append(row((d.sens === "noria" ? "Верхний стоп нажат (" : "Стоп в конце нажат (") + lv("stopUp").toUpperCase() + ")",
        toggle(() => V[lv("stopUp")], (v) => P.setLocal(id, "stopUp", v), up)));
    }
    if (P.LOCAL_STOP[id]) {
      inner.append(row("Местная аварийная кнопка (" + P.LOCAL_STOP[id].toUpperCase() + ")",
        toggle(() => V[P.LOCAL_STOP[id]], (v) => P.setLocal(id, "estop", v), up)));
    }
    return h("details", {}, h("summary", {}, "Имитация: неисправности и местный пост"), inner);
  }

  function openFlapper(id) {
    const f = P.DEF[id], m = S.machines[id];
    const [l1, l2] = FLAP_POS[id];
    openDlg({
      id, title: "Переключатель потока " + m.poz, sub: m.name + " · блок Flapper", node: id,
      build(b, up) {
        const st = h("div", { class: "row" }, h("span", { class: "status" }));
        up(() => {
          const [t, cls] = stateText(id);
          st.className = "row" + (cls === "bad" ? " bad" : cls === "ok" ? " good" : cls === "warn" ? " warn" : "");
          st.firstChild.textContent = t + " · положение " + Math.round((1 - m.pos) * 100) + "/" + Math.round(m.pos * 100);
        });
        b.append(st);
        const posRow = (label, n, pol, y) => {
          const btn = h("button", { class: "btn-sw", type: "button", onclick: () => run(P.pressPos(id, n)) }, "Переключить");
          up(() => { btn.disabled = !V[f.hm]; btn.title = V[f.hm] ? "" : "Перевод с панели — только в ручном режиме"; });
          return row(label, lampb("концевик", () => V[pol], up), lampb("привод", () => V[y], up, "warn"), btn);
        };
        b.append(posRow(l1, 1, f.pol1, f.y1));
        b.append(posRow(l2, 2, f.pol2, f.y2));
        b.append(row("Время переключения", num(() => P.getTimer(id, "err"), (v) => P.setTimer(id, "err", v), up, "сек.")));
        b.append(row("Ручной режим", toggle(() => V[f.hm], (v) => { V[f.hm] = !!v; return { ok: true }; }, up)));
        b.append(row("Не переключился вовремя", lampb("ERR_SWAP", () => P.plc.fbs[id].err_swap, up, "bad")));
        b.append(row("Оба концевика", lampb("ERR_CONC", () => P.plc.fbs[id].err_conc, up, "bad")));
        b.append(h("div", { class: "note" }, "В автоматическом режиме положение задаёт режим очистки: " +
          (id === "flow_1" ? "«Через триеры»" : "«Через пневмостол»") + ". ПЛК переводит заслонку только при запущенном режиме."));
        const inner = h("div", { class: "inner" });
        inner.append(row("Защита привода (" + f.prot.toUpperCase() + ")", toggle(() => m.sim.az, (v) => P.setSim(id, "az", v), up)));
        inner.append(row("Заклинивание заслонки", toggle(() => m.sim.jam, (v) => P.setSim(id, "jam", v), up)));
        b.append(h("details", {}, h("summary", {}, "Имитация неисправностей"), inner));
      },
    });
  }

  function openTrierBlock(node) {
    const n = S.ND[node];
    openDlg({
      id: node, title: "Триерный блок БТ-7/2 · поз. " + n.poz, node,
      build(b, up) {
        [n.drive, n.drive2].forEach((id, i) => {
          const s = h("small");
          up(() => { s.textContent = stateText(id)[0]; });
          b.append(h("div", { class: "row link", tabindex: 0, onclick: () => openDrive(id) },
            h("span", {}, "Двигатель N" + (i + 1), h("br"), s), h("span", {}, "»")));
        });
        b.append(h("div", { class: "note" }, "Продукт проходит блок, когда работают оба двигателя. N1 ждёт N2 и вентилятор АС-2 (NEXT), N2 ждёт норию 15 и шнек 22.4."));
      },
    });
  }

  const LEVEL_OF = { V: "out_dvy_a", A: "out_dvy_bunk_1", B: "out_dvy_bunk_2", bo_1: "out_dvy_bo_1", bo_2: "out_dvy_bo_2", bo_3: "out_dvy_bo_3" };
  const LEVEL_ID = { V: "A", A: "bunk_1", B: "bunk_2", bo_1: "bo_1", bo_2: "bo_2", bo_3: "bo_3" };
  function openBunker(key, node) {
    const name = { V: "Бункер зерновой БЗ-А-20 (В)", A: "Бункер отходов А", B: "Бункер отходов Б",
      bo_1: "Бункер оперативный БО-1 (поз. 6.1)", bo_2: "Бункер оперативный БО-2 (поз. 9)", bo_3: "Бункер оперативный БО-3 (поз. 16)" }[key];
    const lvl = P.plc.LEVELS.find((l) => l.id === LEVEL_ID[key]);
    openDlg({
      id: "lvl:" + key, title: name, node,
      build(b, up) {
        b.append(row("Уровень", val(() => S.levels[key] * 100, up, (x) => x.toFixed(1)), h("span", { class: "unit" }, "%")));
        b.append(row("Датчик верхнего уровня", lampb("вход", () => V[lvl.input], up, "warn"), lampb(LEVEL_OF[key].toUpperCase(), () => V[LEVEL_OF[key]], up, "bad")));
        b.append(row("Задержка ДВУ", num(() => V[lvl.timer], (v) => P.setDvu(lvl.id, v), up, "с.")));
        b.append(h("div", { class: "note" }, {
          V: "ДВУ сбрасывает режим очистки (Mode_och).", A: "ДВУ сбрасывает режим очистки (Mode_och).", B: "ДВУ сбрасывает режим очистки (Mode_och).",
          bo_1: "ДВУ снимает CYCLE у конвейера 2 (подача).", bo_2: "ДВУ снимает CYCLE у конвейера 2 и остеобрушивателя.",
          bo_3: "ДВУ снимает CYCLE у конвейера 2, ТОР и битера ТОР, триеров, норий 12 и 15.",
        }[key]));
        const tid = { V: "truck_out", A: "truck_A", B: "truck_B" }[key];
        if (tid) {
          const st = h("div", { class: "row" }, h("span", {}, "Автомобиль под бункером"), h("span", { class: "val" }));
          up(() => {
            const t = S.trucks[tid];
            st.lastChild.textContent = { away: "нет", arrive: "подъезжает", work: t.pour ? "загрузка " + Math.round(t.load * 100) + " %" : "на месте", leave: "уезжает" }[t.phase];
          });
          b.append(st);
          b.append(h("div", { class: "btn-row" },
            h("button", { class: "btn-sw", type: "button", onclick: () => run(P.callTruck(tid)) }, "Вызвать автомобиль"),
            h("button", { class: "btn-sw", type: "button", onclick: () => run(P.unload(key)) }, "Выгрузить мгновенно")));
        } else {
          b.append(h("div", { class: "btn-row" }, h("button", { class: "btn-sw", type: "button", onclick: () => run(P.unload(key)) }, "Выгрузить бункер")));
        }
      },
    });
  }
  function openPit() {
    openDlg({
      id: "pit", title: "Завальная яма", node: "intake",
      build(b, up) {
        b.append(row("Уровень зерна", val(() => S.levels.pit * 100, up, (x) => x.toFixed(1)), h("span", { class: "unit" }, "%")));
        b.append(h("div", { class: "row link", onclick: () => openDrive("conv_2") }, h("span", {}, "Окно: конвейер поз. 2"), h("span", {}, "»")));
        b.append(h("div", { class: "row link", onclick: () => openDrive("vor") }, h("span", {}, "Окно: ворошитель поз. 1"), h("span", {}, "»")));
        const st = h("div", { class: "row" }, h("span", {}, "Автомобиль с зерном"), h("span", { class: "val" }));
        up(() => {
          const t = S.trucks.truck_in;
          st.lastChild.textContent = { away: "нет", arrive: "подъезжает", work: t.pour ? "разгрузка, осталось " + Math.round(t.load * 100) + " %" : "на месте", leave: "уезжает" }[t.phase];
        });
        b.append(st);
        b.append(h("div", { class: "btn-row" },
          h("button", { class: "btn-sw", type: "button", onclick: () => run(P.callTruck("truck_in")) }, "Вызвать автомобиль"),
          h("button", { class: "btn-sw", type: "button", onclick: () => run(P.refillPit(100)) }, "Заполнить мгновенно"),
          h("button", { class: "btn-sw", type: "button", onclick: () => run(P.unload("pit")) }, "Очистить")));
        b.append(h("div", { class: "note" }, "При включённом автотранспорте (Настройки → Модель) автомобиль приезжает сам, когда в яме меньше 30 %, а под бункеры В, А, Б — когда они заполнены больше чем на 72 %."));
      },
    });
  }
  function openInfo(t, text, links) {
    openDlg({
      id: "info", title: t,
      build(b) {
        b.append(h("div", { class: "note", style: "font-size:14px" }, text));
        (links || []).forEach((rid) => b.append(h("div", { class: "row link", onclick: () => openAny(rid) }, h("span", {}, "Окно: " + S.machines[rid].name), h("span", {}, "»"))));
      },
    });
  }

  function openClean() {
    openDlg({
      id: "clean", title: "Режим очистки",
      build(b, up) {
        const opt = (label, key, dis) => row(label, toggle(() => V[key], (v) => P.setOption(key, v), up, dis));
        b.append(opt("Через триеры", "with_trier"));
        b.append(h("div", { class: "row-2" }, opt("Триер 14.1", "use_1"), opt("Триер 14.2", "use_2")));
        b.append(opt("Через пневмостол", "with_pnev"));
        b.append(opt("Вкл остеобрушиватель", "on_ost"));
        b.append(opt("Вкл ворошитель", "on_vor"));
        const warn = h("div", { class: "note" });
        up(() => {
          const w = [];
          if (V.with_trier && !V.use_1 && !V.use_2) w.push("⚠ Выбрано «через триеры», но не выбран ни один блок — нория 12 не получит NEXT.");
          if (!V.with_trier && (V.use_1 || V.use_2)) w.push("Триерные блоки включатся по use_1/use_2 даже без «через триеры» — так в программе ПЛК.");
          warn.textContent = w.join(" ");
        });
        b.append(warn);
        const st = h("div", { class: "row" }, h("span", { class: "status" }));
        up(() => {
          st.className = "row" + (V.mode_och ? " good" : V.gemer ? " bad" : "");
          st.firstChild.textContent = V.mode_och ? "Режим очистки запущен" : V.gemer ? "Общая авария — пуск невозможен" : "Режим не запущен";
        });
        b.append(st);
        const go = h("button", { class: "big-go", type: "button", onclick: () => run(P.modeStart(), "Режим очистки: Mode_och := TRUE") }, "ПУСК");
        const stop = h("button", { class: "big-stop", type: "button", onclick: () => run(P.modeStop(), "Режим очистки: Mode_och := FALSE") }, "СТОП");
        up(() => { go.disabled = !!V.mode_och; stop.disabled = !V.mode_och; });
        b.append(h("div", { class: "btn-row" }, go, stop));
        b.append(h("div", { class: "note" }, "Переключатели записываются в ПЛК сразу (RETAIN-переменные with_trier, use_1, use_2, with_pnev, on_ost, on_vor)."));
      },
    });
  }

  const DVU_LABEL = { bo_1: "Задержка ДВУ БО-1 (6.1)", bo_2: "Задержка ДВУ БО-2 (9)", bo_3: "Задержка ДВУ БО-3 (16)",
    A: "Задержка ДВУ бункера В (БЗ-А)", bunk_1: "Задержка ДВУ 1 бункера отходов (А)", bunk_2: "Задержка ДВУ 2 бункера отходов (Б)" };
  function openDvu() {
    openDlg({
      id: "dvu", title: "Настройки",
      build(b, up) {
        P.plc.LEVELS.forEach((l) => b.append(row(DVU_LABEL[l.id], num(() => V[l.timer], (v) => P.setDvu(l.id, v), up, "с."))));
      },
    });
  }

  function openCabinet() {
    openDlg({
      id: "cab", title: "Шкаф управления", sub: "Кнопки и сигналы, входящие в общую аварию GEMER",
      build(b, up) {
        const inp = (label, key) => row(label, toggle(() => V[key], (v) => P.setInput(key, v), up));
        b.append(inp("Кнопка «СТОП» на шкафу (AVAR_STOP)", "avar_stop"));
        [1, 2, 3, 4, 5].forEach((k) => b.append(inp("Аварийный стоп " + k + " (AVAR_STOP_" + k + ")", "avar_stop_" + k)));
        b.append(inp("Пожарная сигнализация (FIRE_ALARM)", "fire_alarm"));
        b.append(row("Реле контроля фаз в норме (x0_8)", toggle(() => V.x0_8, (v) => P.setInput("x0_8", v), up)));
        b.append(row("Авария фаз (PHASE_CONTROL, защёлка)", lampb("PHASE", () => V.phase_control, up, "bad")));
        b.append(inp("Кнопка «ПУСК» на шкафу (PUSK, x0_0)", "pusk"));
        b.append(h("div", { class: "note" }, "⚠ В программе ПЛК сигнал PUSK входит в GEMER вместе с аварийными стопами: нажатие «ПУСК» на шкафу вызывает общую аварию. Эмулятор повторяет это поведение."));
        b.append(row("Общая авария (GEMER)", lampb("GEMER", () => V.gemer, up, "bad")));
      },
    });
  }

  function openJournal(archive) {
    openDlg({
      id: "journal", title: archive ? "Архив сообщений" : "Журнал аварий", wide: true,
      build(b, up) {
        const tb = h("tbody");
        b.append(h("div", { class: "alarm-wrap" }, h("table", { class: "alarm-table" },
          h("thead", {}, h("tr", {}, h("th", {}, "Время запуска"), h("th", {}, "Сообщение"))), tb)));
        let last = "";
        up(() => {
          const list = (archive ? S.archive : S.alarms).slice(0, 200);
          const sig = list.length + ":" + list.filter((a) => a.active).length + ":" + (list[0] ? list[0].ts + list[0].message : "");
          if (sig === last) return;
          last = sig;
          tb.innerHTML = list.map((a) => `<tr class="${a.active ? "act" : ""}"><td>${a.ts}</td><td>${esc(a.message)}</td></tr>`).join("") ||
            "<tr><td colspan=2>Сообщений нет</td></tr>";
        });
        b.append(h("button", { class: "menu-item", type: "button", onclick: () => openJournal(!archive) }, archive ? "Журнал активных сообщений" : "Открыть архив сообщений"));
      },
    });
  }

  function openMenu() {
    openDlg({
      id: "menu", title: "Меню управления",
      build(b) {
        b.append(h("button", { class: "menu-item", type: "button", onclick: openClean }, "Режим очистки"));
        b.append(h("button", { class: "menu-item", type: "button", onclick: openDvu }, "Настройки"));
        b.append(h("button", { class: "menu-item", type: "button", onclick: openCabinet }, "Шкаф управления"));
        b.append(h("button", { class: "menu-item", type: "button", onclick: openAccount }, "Учетная запись"));
      },
    });
  }
  function openAccount() {
    openDlg({
      id: "acc", title: "Учетная запись",
      build(b, up) {
        const i = h("input", { type: "text", value: S.user.login });
        i.addEventListener("change", () => { S.user.login = i.value.trim() || "operator"; save(); });
        b.append(row("Пользователь", i));
        b.append(row("Роль", val(() => S.user.role, up)));
      },
    });
  }

  function nodeOfDrive(id) {
    for (const [nid, n] of Object.entries(S.ND)) if (n.drive === id && n.kind !== "motor") return nid;
    for (const [nid, n] of Object.entries(S.ND)) if (n.drive === id) return nid;
    return null;
  }
  function openAny(id) { if (P.DEF[id]) openDrive(id); }
  function openNode(nid) {
    const n = S.ND[nid];
    if (!n) return;
    if (nid === "intake") return openDrive("conv_2");
    if (n.kind === "trier") return openTrierBlock(nid);
    if (n.drive) return openAny(n.drive);
    if (n.level) return openBunker(n.level, nid);
    if (nid === "truck_in") return openPit();
    if (nid === "truck_out") return openBunker("V", "bun_21");
    if (nid === "truck_A") return openBunker("A", "bun_A");
    if (nid === "truck_B") return openBunker("B", "bun_B");
    if (n.kind === "cyclone") {
      const k = nid.slice(-1);
      return openInfo("Циклон аспирации АС-" + k, "Пассивный узел: пыль из воздуховода оседает в циклоне и выгружается шлюзовым затвором на шнек 22.5.", ["fan_asp_" + k, "shl_" + k]);
    }
    if (nid === "magnet_3") return openInfo("Магнитный сепаратор ПМ-200 · поз. 3", "Пассивный узел: в программе ПЛК не управляется.", ["conv_2", "noria_4"]);
  }

  /* ------------------------------------------------ правая панель */
  function buildRail() {
    const box = $("#rail-machines");
    box.innerHTML = "";
    ORDER.forEach((id) => {
      const m = S.machines[id];
      box.append(h("button", { class: "rail-machine", type: "button", "data-machine": id, onclick: () => openDrive(id) },
        h("span", { class: "led" }), h("span", {}, m.name), h("span", { class: "poz" }, m.poz)));
    });
  }
  $("#rail-search").addEventListener("input", (e) => {
    const q = e.target.value.trim().toLowerCase();
    $$(".rail-machine").forEach((b) => {
      const m = S.machines[b.dataset.machine];
      b.style.display = !q || (m.name + " " + m.poz + " " + b.dataset.machine).toLowerCase().includes(q) ? "" : "none";
    });
  });
  function updateRail() {
    $$(".rail-machine").forEach((b) => { b.querySelector(".led").className = "led " + ledClass(b.dataset.machine); });
  }

  /* ------------------------------------------------ вкладки */
  let tab = "mimic";
  function switchTab(t) {
    tab = t;
    $$(".tab").forEach((b) => b.classList.toggle("active", b.dataset.tab === t));
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-" + t));
    if (t === "signals") buildSignals();
    if (t === "settings") buildSettings();
    updateViews(true);
  }
  $$(".tab").forEach((b) => b.addEventListener("click", () => switchTab(b.dataset.tab)));

  function bits(list) {
    return `<span class="bits">${list.map(([n, v, bad]) => `<span class="bit${v ? " on" : ""}${bad ? " bad" : ""}">${n}</span>`).join("")}</span>`;
  }
  function renderEquip() {
    const q = $("#eq-search").value.trim().toLowerCase(), f = $("#eq-filter").value;
    const rows = ORDER.filter((id) => {
      const m = S.machines[id], s = P.info(id).state;
      if (q && !(m.name + " " + m.poz).toLowerCase().includes(q)) return false;
      if (f === "run") return m.cmd;
      if (f === "stop") return !m.cmd;
      if (f === "fault") return m.fault;
      if (f === "hand") return /hand|local/.test(s);
      if (f === "to") return m.toHours > 0 && m.hours >= m.toHours;
      return true;
    }).map((id) => {
      const m = S.machines[id], d = P.DEF[id];
      const [t, cls, inf] = stateText(id);
      const I = inf.I || {};
      const cond = d.fb ? bits([["C", I.cycle], ["N", I.next], ["P", I.prev], ["RR", inf.fb.rr], ["Y", V[d.y]]])
        : bits([["П1", V[d.pol1]], ["П2", V[d.pol2]], ["Y1", V[d.y1]], ["Y2", V[d.y2]]]);
      const tm = d.fb ? P.getTimer(id, "start") + " / " + P.getTimer(id, "stop") : "ошибка " + P.getTimer(id, "err");
      const due = m.toHours > 0 && m.hours >= m.toHours;
      return `<tr class="${m.fault ? "row-bad" : ""}"><td class="c-poz">${m.poz}</td><td>${esc(m.name)}</td>
        <td><span class="chip ${cls}">${esc(t)}</span></td><td>${cond}</td><td class="c-num">${tm}</td>
        <td class="c-num${due ? " due" : ""}">${m.hours.toFixed(2)} / ${m.toHours}</td>
        <td>${d.fb ? `<div class="bar"><i style="width:${Math.round(m.mat * 100)}%"></i></div>` : ""}</td>
        <td><button class="btn btn-sm" data-open="${id}" type="button">Окно</button></td></tr>`;
    });
    $("#eq-rows").innerHTML = rows.join("") || `<tr><td colspan="8" class="muted">Нет механизмов по фильтру</td></tr>`;
  }
  $("#eq-rows").addEventListener("click", (e) => { const b = e.target.closest("[data-open]"); if (b) openDrive(b.dataset.open); });
  $("#eq-search").addEventListener("input", renderEquip);
  $("#eq-filter").addEventListener("change", renderEquip);

  function renderAlarms() {
    const scope = $("#al-scope").value;
    const list = scope === "archive" ? S.archive : S.alarms;
    const TYPE = { err: ["Авария", "bad"], warn: ["Предупр.", "warn"], ok: ["Событие", "ok"], info: ["Инфо", "info"] };
    $("#al-rows").innerHTML = list.map((a) => {
      const [t, c] = TYPE[a.lvl] || TYPE.info;
      return `<tr class="${a.active ? "row-bad" : ""}"><td class="c-num">${a.ts}</td><td><span class="chip ${c}">${t}</span></td><td>${esc(a.message)}</td><td>${a.active ? '<span class="chip bad">активно</span>' : a.key ? '<span class="chip">снято</span>' : ""}</td></tr>`;
    }).join("") || `<tr><td colspan="4" class="muted">Сообщений нет</td></tr>`;
    const act = S.alarms.filter((a) => a.active && a.lvl === "err");
    $("#al-causes").innerHTML = act.map((a) => `<div class="cause"><span>${esc(a.message)}</span></div>`).join("");
  }
  $("#al-scope").addEventListener("change", renderAlarms);
  $("#al-reset").addEventListener("click", () => run(P.resetErr(), "RESET_ERR — сброс аварий"));

  /* ------------------------------------------------ сигналы ПЛК */
  let sigBuilt = false;
  function buildSignals() {
    if (sigBuilt) return;
    sigBuilt = true;
    const b = $("#signals-body");
    const sig = (name, key, bad) => `<div class="sig-row"><span>${name}</span><span><code>${key.toUpperCase()}</code> <span class="bit${bad ? " bad" : ""}" data-sig="${key}">0</span></span></div>`;
    const general = [["Кнопка «ПУСК» на шкафу", "pusk", 1], ["Кнопка «СТОП» на шкафу", "avar_stop", 1],
      ...[1, 2, 3, 4, 5].map((k) => ["Аварийный стоп " + k, "avar_stop_" + k, 1]), ["Пожарная сигнализация", "fire_alarm", 1],
      ["Реле контроля фаз (вход)", "x0_8"], ["Авария фаз (защёлка)", "phase_control", 1], ["Общая авария", "gemer", 1],
      ["Сброс ошибок", "reset_err"], ["Откл. сирены", "mute"], ["Есть авария механизма", "do_alarm", 1], ["Лампа", "lamp", 1], ["Сирена", "sirena", 1]];
    const modes = [["Режим очистки", "mode_och"], ["Через триеры", "with_trier"], ["Триер 14.1", "use_1"], ["Триер 14.2", "use_2"],
      ["Через пневмостол", "with_pnev"], ["Остеобрушиватель", "on_ost"], ["Ворошитель", "on_vor"]];
    const dvu = P.plc.LEVELS.map((l) => `<div class="sig-row"><span>${DVU_LABEL[l.id].replace("Задержка ", "")}</span><span>вход <span class="bit" data-sig="${l.input}">0</span> <code>${l.out.toUpperCase()}</code> <span class="bit bad" data-sig="${l.out}">0</span></span></div>`).join("");
    const drv = ORDER.filter((id) => P.DEF[id].fb).map((id) => `<tr><td class="c-poz">${S.machines[id].poz}</td><td>${esc(S.machines[id].name)}</td><td><code>${P.DEF[id].y.toUpperCase()}</code></td><td data-drv="${id}"></td><td class="c-num" data-tm="${id}"></td></tr>`).join("");
    const flp = ["flow_1", "flow_2"].map((id) => `<tr><td class="c-poz">${S.machines[id].poz}</td><td>${esc(S.machines[id].name)}</td><td data-flp="${id}"></td></tr>`).join("");
    b.innerHTML = `<div class="sig-grid">
      <section class="panel"><h3>Шкаф, общая авария, сигнализация</h3>${general.map(([n, k, bad]) => sig(n, k, bad)).join("")}</section>
      <section class="panel"><h3>Режим очистки (HMI → ПЛК)</h3>${modes.map(([n, k]) => sig(n, k)).join("")}</section>
      <section class="panel"><h3>Датчики верхнего уровня (DU)</h3>${dvu}</section></div>
      <section class="panel wide"><h3>Блоки Transport / FB_och</h3><div class="table-wrap"><table class="grid-table"><thead><tr><th>Поз.</th><th>Механизм</th><th>Выход</th><th>CYCLE · NEXT · PREV · RR · START · RUN · DA · РУЧН · BTN</th><th>TON_START / TON_STOP, с</th></tr></thead><tbody>${drv}</tbody></table></div></section>
      <section class="panel wide" style="margin-top:14px"><h3>Блоки Flapper</h3><div class="table-wrap"><table class="grid-table"><thead><tr><th>Поз.</th><th>Механизм</th><th>POL_1 · POL_2 · RUN_POL_1 · RUN_POL_2 · ERR_SWAP · ERR_CONC · DA · РУЧН</th></tr></thead><tbody>${flp}</tbody></table></div></section>`;
  }
  function renderSignals() {
    $$("[data-sig]").forEach((e) => { const v = !!V[e.dataset.sig]; e.classList.toggle("on", v); e.textContent = v ? "1" : "0"; });
    $$("[data-drv]").forEach((e) => {
      const id = e.dataset.drv, d = P.DEF[id], fb = P.plc.fbs[id], I = fb.inputs || {};
      e.innerHTML = bits([["C", I.cycle], ["N", I.next], ["P", I.prev], ["RR", fb.rr], ["S", fb.start], ["RUN", fb.run], ["DA", fb.da, 1], ["РУЧ", V[d.hm]], ["BTN", V[d.btn]]]);
    });
    $$("[data-tm]").forEach((e) => {
      const id = e.dataset.tm, fb = P.plc.fbs[id];
      e.textContent = fb.ton_start.et.toFixed(1) + "/" + P.getTimer(id, "start") + " · " + fb.ton_stop.et.toFixed(1) + "/" + P.getTimer(id, "stop");
    });
    $$("[data-flp]").forEach((e) => {
      const id = e.dataset.flp, f = P.DEF[id], fb = P.plc.fbs[id];
      e.innerHTML = bits([["П1", V[f.pol1]], ["П2", V[f.pol2]], ["Y1", fb.run_pol_1], ["Y2", fb.run_pol_2], ["SW", fb.err_swap, 1], ["CC", fb.err_conc, 1], ["DA", fb.da, 1], ["РУЧ", V[f.hm]]]);
    });
  }

  /* ------------------------------------------------ настройки */
  function buildSettings() {
    const dv = $("#set-dvu");
    dv.innerHTML = "";
    P.plc.LEVELS.forEach((l) => {
      const i = h("input", { type: "number", min: 0, max: 3600, value: V[l.timer] });
      i.addEventListener("change", () => { run(P.setDvu(l.id, i.value)); i.value = V[l.timer]; });
      dv.append(h("div", { class: "set-row" }, h("span", {}, DVU_LABEL[l.id].replace("Задержка ", "")), h("span", {}, i, " с")));
    });
    const sim = $("#set-sim");
    sim.innerHTML = "";
    const sp = h("select", {}, ...[1, 2, 5, 10, 20].map((k) => h("option", { value: k, selected: S.timeScale === k }, "×" + k)));
    sp.addEventListener("change", () => { run(P.setTimeScale(sp.value)); $("#speed").value = S.timeScale; });
    sim.append(h("div", { class: "set-row" }, h("span", {}, "Скорость модели (вместе с таймерами ПЛК)"), sp));
    const auto = h("input", { type: "checkbox", checked: S.autoTrucks });
    auto.addEventListener("change", () => run(P.setAutoTrucks(auto.checked)));
    sim.append(h("label", { class: "set-row" }, h("span", {}, "Автотранспорт: подвоз в яму и вывоз из бункеров"), auto));
    sim.append(h("div", { class: "set-row" }, h("span", {}, "Завальная яма"),
      h("button", { class: "btn btn-sm", type: "button", onclick: () => run(P.callTruck("truck_in")) }, "Вызвать автомобиль")));
    sim.append(h("div", { class: "set-row" }, h("span", {}, "Конечные бункеры А, Б, В"),
      h("button", { class: "btn btn-sm", type: "button", onclick: () => { ["A", "B", "V"].forEach((k) => P.unload(k)); save(); } }, "Выгрузить все")));
    const vw = $("#set-view");
    vw.innerHTML = "";
    const vo = R.getViewOpt();
    [["labels", "Подписи механизмов"], ["tags", "Метки состояний (пуск/стоп/авария)"], ["pipes", "Самотёчные трубы"], ["ducts", "Воздуховоды аспирации"]].forEach(([k, label]) => {
      const c = h("input", { type: "checkbox", checked: vo[k] });
      c.addEventListener("change", () => { R.setViewOpt({ [k]: c.checked }); save(); });
      vw.append(h("label", { class: "set-row" }, h("span", {}, label), c));
    });
    const tt = $("#set-timers");
    tt.innerHTML = "";
    const tb = h("tbody");
    ORDER.filter((id) => P.DEF[id].fb).forEach((id) => {
      const cell = (which) => {
        const i = h("input", { type: "number", min: 0, max: 3600, value: P.getTimer(id, which) });
        i.addEventListener("change", () => { run(P.setTimer(id, which, i.value)); i.value = P.getTimer(id, which); });
        return h("td", {}, i);
      };
      tb.append(h("tr", {}, h("td", { class: "c-poz" }, S.machines[id].poz), h("td", {}, S.machines[id].name), cell("start"), cell("stop")));
    });
    tt.append(h("div", { class: "table-wrap" }, h("table", { class: "grid-table timer-table" },
      h("thead", {}, h("tr", {}, h("th", {}, "Поз."), h("th", {}, "Механизм"), h("th", {}, "Пуск, с"), h("th", {}, "Останов, с"))), tb)));
  }
  $("#set-defaults").addEventListener("click", () => {
    localStorage.removeItem(STORE);
    location.reload();
  });

  /* ------------------------------------------------ RETAIN (localStorage) */
  const STORE = "lpzs-rodina-retain-v2";
  const RETAIN = (k) => /^hmi_(timer_|tm_|off_)/.test(k) || P.OPTIONS.includes(k);
  let saveT = 0;
  function save() {
    clearTimeout(saveT);
    saveT = setTimeout(() => {
      const v = {};
      Object.keys(V).forEach((k) => { if (RETAIN(k)) v[k] = V[k]; });
      const hours = {};
      Object.entries(S.machines).forEach(([id, m]) => { hours[id] = [m.hours, m.hoursTotal, m.toHours]; });
      try { localStorage.setItem(STORE, JSON.stringify({ v, hours, user: S.user.login, speed: S.timeScale, autoTrucks: S.autoTrucks, view: R.getViewOpt() })); } catch (e) { /* приватный режим */ }
    }, 300);
  }
  function load() {
    let d;
    try { d = JSON.parse(localStorage.getItem(STORE) || "null"); } catch (e) { d = null; }
    if (!d || typeof d !== "object") return;
    Object.entries(d.v || {}).forEach(([k, x]) => {
      if (!RETAIN(k)) return;
      if (typeof x === "boolean") V[k] = x;
      else if (Number.isFinite(x) && x >= 0 && x <= 3600) V[k] = Math.round(x);
    });
    Object.entries(d.hours || {}).forEach(([id, a]) => {
      const m = S.machines[id];
      if (!m || !Array.isArray(a)) return;
      if (Number.isFinite(a[0]) && a[0] >= 0) m.hours = a[0];
      if (Number.isFinite(a[1]) && a[1] >= 0) m.hoursTotal = a[1];
      if (Number.isFinite(a[2]) && a[2] >= 0) m.toHours = a[2];
    });
    if (typeof d.user === "string" && d.user) S.user.login = d.user.slice(0, 40);
    if (d.speed) P.setTimeScale(d.speed);
    if (typeof d.autoTrucks === "boolean") S.autoTrucks = d.autoTrucks;
    if (d.view && typeof d.view === "object") R.setViewOpt(Object.fromEntries(Object.entries(d.view).filter(([, x]) => typeof x === "boolean")));
  }
  setInterval(save, 10000);

  /* ------------------------------------------------ нижняя и верхняя панели */
  $("#btn-start").addEventListener("click", () => run(P.modeStart(), "Режим очистки запущен: " + P.routeName()));
  $("#btn-stop").addEventListener("click", () => run(P.modeStop(), "Штатный останов: механизмы отключаются по задержкам"));
  $("#btn-ack").addEventListener("click", () => run(P.resetErr(), "RESET_ERR — сброс аварий"));
  $("#btn-mute").addEventListener("click", () => run(P.setMute(!V.mute)));
  $("#btn-estop").addEventListener("click", () => run(P.setInput("avar_stop", !V.avar_stop)));
  $("#speed").addEventListener("change", (e) => run(P.setTimeScale(e.target.value)));
  $("#btn-menu").addEventListener("click", openMenu);
  $("#rail-clean").addEventListener("click", openClean);
  $("#rail-settings").addEventListener("click", openDvu);
  $("#rail-alarms").addEventListener("click", () => openJournal(false));
  $("#rail-cabinet").addEventListener("click", openCabinet);

  function updateChrome() {
    const now = new Date();
    $("#clock").textContent = now.toLocaleTimeString("ru-RU");
    $("#date").textContent = now.toLocaleDateString("ru-RU");
    const lamp = (id, on, cls) => { $(id).className = "lamp" + (on ? " " + cls : ""); };
    lamp("#lamp-mode", V.mode_och, "on-ok");
    lamp("#lamp-gemer", V.gemer, "on-bad");
    lamp("#lamp-siren", V.sirena, "on-warn");
    const es = $("#btn-estop");
    es.classList.toggle("pressed", !!V.avar_stop);
    es.textContent = V.avar_stop ? "ОТЖАТЬ АВАРИЙНЫЙ СТОП" : "АВАРИЙНЫЙ СТОП";
    $("#btn-start").disabled = !!V.mode_och || !!V.gemer;
    $("#btn-start").title = V.gemer ? "Общая авария: сначала снимите причину (аварийный стоп, пожар, фазы)" : "Mode_och := TRUE с текущими настройками режима очистки";
    $("#btn-stop").disabled = !V.mode_och;
    $("#btn-mute").textContent = V.mute ? "Сирена откл." : "Сирена вкл.";
    $("#btn-mute").classList.toggle("active", !!V.mute);
    const line = $("#alarm-line");
    line.textContent = P.statusLine();
    line.className = "alarm-line" + (V.gemer || S.alarms.some((a) => a.active && a.lvl === "err") ? "" : " ok");
    $("#route-line").textContent = P.routeName();
    const n = S.alarms.filter((a) => a.active).length;
    $("#tab-alarm-count").textContent = n ? n : "";
    if ($("#speed").value !== String(S.timeScale)) $("#speed").value = S.timeScale;
  }

  function updateViews(force) {
    if (tab === "equip") renderEquip();
    if (tab === "alarms") renderAlarms();
    if (tab === "signals") renderSignals();
    void force;
  }

  /* ------------------------------------------------ холст */
  function bindCanvas() {
    const cv = $("#plant-canvas"), tip = $("#tooltip");
    let drag = null;
    cv.addEventListener("pointerdown", (e) => { drag = { x: e.clientX, y: e.clientY, moved: false }; cv.setPointerCapture(e.pointerId); });
    cv.addEventListener("pointermove", (e) => {
      if (drag) {
        const dx = e.clientX - drag.x, dy = e.clientY - drag.y;
        if (drag.moved || Math.hypot(dx, dy) > 5) {
          drag.moved = true; cv.classList.add("grab");
          R.panBy(dx, dy); drag.x = e.clientX; drag.y = e.clientY;
          tip.style.display = "none";
          return;
        }
      }
      const [wx, wy] = R.toWorld(e.clientX, e.clientY);
      const id = R.hitAt(wx, wy);
      R.setHover(id);
      cv.classList.toggle("hot", !!id);
      if (!id) { tip.style.display = "none"; return; }
      const n = S.ND[id];
      const ids = [n.drive, n.drive2].filter(Boolean);
      let html = "";
      if (ids.length) html = ids.map((d) => `<b>${esc(S.machines[d].name)}</b> · поз. ${S.machines[d].poz}<br>${esc(stateText(d)[0])}`).join("<hr style='border-color:#2b3d50'>");
      else if (n.level) html = `<b>${n.letter ? "Бункер " + n.letter : "Бункер оперативный " + n.poz}</b><br>Уровень ${(S.levels[n.level] * 100).toFixed(0)} %`;
      else if (id.startsWith("truck")) {
        const t = S.trucks[id];
        html = (id === "truck_in" ? "<b>Автомобиль с зерном</b><br>Осталось в кузове " : "<b>Автомобиль под бункером</b><br>Загружен на ") + Math.round(t.load * 100) + " %";
      }
      else html = { magnet_3: "Магнитный сепаратор ПМ-200 (поз. 3)", cyc_1: "Циклон АС-1", cyc_2: "Циклон АС-2", cyc_3: "Циклон АС-3" }[id] || id;
      tip.innerHTML = html;
      tip.style.display = "block";
      tip.style.left = Math.min(window.innerWidth - 330, e.clientX + 14) + "px";
      tip.style.top = (e.clientY + 14) + "px";
    });
    cv.addEventListener("pointerup", (e) => {
      const was = drag; drag = null; cv.classList.remove("grab");
      if (was && !was.moved) {
        const [wx, wy] = R.toWorld(e.clientX, e.clientY);
        const id = R.hitAt(wx, wy);
        if (id) openNode(id);
      }
    });
    cv.addEventListener("pointerleave", () => { R.setHover(null); tip.style.display = "none"; });
    cv.addEventListener("wheel", (e) => { e.preventDefault(); R.zoomAt(e.clientX, e.clientY, e.deltaY < 0 ? 1.15 : 1 / 1.15); }, { passive: false });
    const center = (k) => { const r = cv.getBoundingClientRect(); R.zoomAt(r.left + r.width / 2, r.top + r.height / 2, k); };
    $("#zoom-in").addEventListener("click", () => center(1.25));
    $("#zoom-out").addEventListener("click", () => center(1 / 1.25));
    $("#zoom-fit").addEventListener("click", () => R.fit());
  }

  /* ------------------------------------------------ запуск */
  function init() {
    load();
    // Как на панели после включения: нажат аварийный стоп на шкафу.
    P.setInput("avar_stop", true);
    buildRail();
    R.init($("#plant-canvas"));
    bindCanvas();
    let last = performance.now(), acc = 0;
    function frame(t) {
      const dt = (t - last) / 1000; last = t;
      P.tick(dt);
      R.render();
      acc += dt;
      if (acc > 0.25) { acc = 0; updateChrome(); updateRail(); refresh(); updateViews(); }
      requestAnimationFrame(frame);
    }
    updateChrome();
    requestAnimationFrame(frame);
    window.UI = { openNode, openDrive, openClean, openCabinet, openJournal, openMenu, closeDlg, switchTab };
  }
  init();
})();
