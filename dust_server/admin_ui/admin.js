"use strict";
// Web admin for the DUST 514 revival server (dust_server/admin.py serves this file and the /api/ endpoints).

const $ = (sel, root = document) => root.querySelector(sel);

function h(tag, attrs, ...children) {
  const el = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (value === undefined || value === null || value === false) continue;
    if (key.startsWith("on")) el.addEventListener(key.slice(2), value);
    else if (key === "class") el.className = value;
    else if (key === "text") el.textContent = value;
    else if (key === "value") el.value = value;
    else if (key === "checked") el.checked = true;
    else el.setAttribute(key, value === true ? "" : value);
  }
  for (const child of children.flat()) {
    if (child === null || child === undefined || child === false) continue;
    el.append(child instanceof Node ? child : document.createTextNode(String(child)));
  }
  return el;
}

const fmt = (n) => (n === null || n === undefined || n === "" ? "–" : Number(n).toLocaleString("en-US"));
const ago = (s) => (s === null || s === undefined ? "never" : s < 90 ? `${Math.round(s)} s ago` : s < 5400 ? `${Math.round(s / 60)} min ago` : `${Math.round(s / 3600)} h ago`);
const clone = (o) => JSON.parse(JSON.stringify(o));

class ApiError extends Error {}

async function api(path, body) {
  const options = { credentials: "same-origin", headers: {} };
  if (body !== undefined) {
    options.method = "POST";
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const response = await fetch(path, options);
  let data = null;
  try { data = await response.json(); } catch (e) { /* empty body */ }
  if (response.status === 401 && path !== "/api/login") {
    showLogin();
    throw new ApiError("Not logged in");
  }
  if (!response.ok) throw new ApiError((data && data.error) || `HTTP ${response.status}`);
  return data;
}

let toastTimer = null;
function toast(message, bad = false) {
  const el = $("#toast");
  el.textContent = message;
  el.className = "toast" + (bad ? " bad" : "");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.add("hidden"), bad ? 8000 : 3500);
}

async function run(button, action) {
  if (button) button.disabled = true;
  try { return await action(); } catch (e) { toast(e.message, true); } finally { if (button) button.disabled = false; }
}

// --- catalog --------------------------------------------------------------------------------------

let catalog = null;
async function loadCatalog() {
  if (catalog) return catalog;
  const raw = await api("/api/catalog");
  const c = { root: raw.root, groups: new Map(), items: new Map(), children: new Map(), levels: raw.levels, gameTypes: new Map() };
  for (const g of raw.categories) {
    c.groups.set(g.id, g);
    if (!c.children.has(g.parent)) c.children.set(g.parent, []);
    c.children.get(g.parent).push(g.id);
  }
  for (const ids of c.children.values()) ids.sort((a, b) => (c.groups.get(a).sortOrder - c.groups.get(b).sortOrder) || a - b);
  for (const i of raw.items) c.items.set(i.id, i);
  for (const t of raw.gameTypes) c.gameTypes.set(t.id, t);
  c.subtree = (id) => {
    const out = new Set(), todo = [id];
    while (todo.length) {
      const g = todo.pop();
      if (out.has(g)) continue;
      out.add(g);
      todo.push(...(c.children.get(g) || []));
    }
    return out;
  };
  c.marketGroups = c.subtree(c.root);
  c.groupName = (id) => (c.groups.get(id) || {}).name || String(id);
  c.itemsSorted = [...c.items.values()].sort((a, b) => a.name.localeCompare(b.name));
  catalog = c;
  return c;
}

// --- shell ----------------------------------------------------------------------------------------

let pageTimer = null;
let bannerTimer = null;

function showLogin() {
  clearInterval(pageTimer);
  clearInterval(bannerTimer);
  $("#app").classList.add("hidden");
  $("#login").classList.remove("hidden");
  $("#login-token").focus();
}

async function showApp() {
  $("#login").classList.add("hidden");
  $("#app").classList.remove("hidden");
  route();
  updateBanner();
  clearInterval(bannerTimer);
  bannerTimer = setInterval(updateBanner, 10000);
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#login-error").textContent = "";
  try {
    await api("/api/login", { token: $("#login-token").value });
    $("#login-token").value = "";
    showApp();
  } catch (e) {
    $("#login-error").textContent = e.message;
  }
});

$("#logout").addEventListener("click", async () => {
  await api("/api/logout", {}).catch(() => {});
  showLogin();
});

async function restartHost(button) {
  if (!confirm("Restart the host instance (RPCS3)? Connected players drop out of the battle.")) return;
  await run(button, async () => {
    const r = await api("/api/host/restart", {});
    toast(r.method === "control" ? "Restart requested from the watchdog" : "Restart command started – the host needs about a minute");
    setTimeout(updateBanner, 2000);
  });
}

async function updateBanner() {
  const banner = $("#banner");
  try {
    const s = await api("/api/status");
    banner.replaceChildren();
    if (!s.catma.ok) {
      banner.className = "banner bad";
      banner.append("CATMA service unreachable – market, catalog and CCP's offline answers are missing. ", h("code", { text: s.catma.error || "" }));
    } else if (s.host.restart_needed) {
      banner.className = "banner warn";
      banner.append(h("span", { text: "The running host still uses the old mode or map. It has to restart for the new settings." }),
        s.host.restart_method ? h("button", { class: "primary", text: "Restart host", onclick: (e) => restartHost(e.target) }) : h("span", { class: "muted", text: "(no restart method configured)" }));
    } else {
      banner.className = "banner hidden";
    }
  } catch (e) {
    if (!(e instanceof ApiError)) banner.className = "banner hidden";
  }
}

const PAGES = {
  status: pageStatus, host: pageHost, documents: pageDocuments, market: (el) => pageMarket(el, "isk"),
  aur: (el) => pageMarket(el, "aur"), storefront: pageStorefront, loyalty: pageLoyalty, rewards: pageRewards, wallet: pageWallet,
  characters: pageCharacters,
};

async function route() {
  clearInterval(pageTimer);
  const name = (location.hash || "#status").slice(1);
  const page = PAGES[name] ? name : "status";
  for (const a of document.querySelectorAll(".sidebar a")) a.classList.toggle("active", a.dataset.page === page);
  const el = $("#page");
  el.replaceChildren(h("p", { class: "muted", text: "Loading …" }));
  try {
    await PAGES[page](el);
  } catch (e) {
    el.replaceChildren(h("div", { class: "banner bad", text: e.message }));
  }
}
window.addEventListener("hashchange", route);

function head(title, text) {
  return h("div", { class: "page-head" }, h("h1", { text: title }), text ? h("p", { class: "muted", text }) : null);
}

function field(label, input, hint) {
  return [h("label", { text: label }), hint ? h("div", {}, input, h("div", { class: "muted", text: hint })) : input];
}

function numberInput(value, onchange, attrs = {}) {
  return h("input", { type: "number", min: 0, step: 1, value: value ?? "", oninput: (e) => onchange(e.target.value === "" ? null : Number(e.target.value)), ...attrs });
}

function textInput(value, onchange, attrs = {}) {
  return h("input", { type: "text", value: value ?? "", oninput: (e) => onchange(e.target.value), ...attrs });
}

function checkbox(checked, onchange, label) {
  const input = h("input", { type: "checkbox", checked: !!checked, onchange: (e) => onchange(e.target.checked) });
  return label ? h("label", {}, input, " ", label) : input;
}

function select(options, value, onchange) {
  // options: [[value, label], ...]
  const el = h("select", { onchange: (e) => onchange(e.target.value) },
    options.map(([v, label]) => h("option", { value: v, text: label })));
  el.value = value;
  return el;
}

// --- status ---------------------------------------------------------------------------------------

async function pageStatus(el) {
  const render = async () => {
    const s = await api("/api/status");
    const host = s.host;
    const hostPill = host.online ? h("span", { class: "pill ok", text: "online" }) : h("span", { class: "pill bad", text: "offline" });
    const watchdog = host.watchdog ? `${host.watchdog.state || "?"}${host.watchdog.restarts !== undefined ? `, ${host.watchdog.restarts} restarts` : ""}` : null;
    el.replaceChildren(
      head("Status", "Refreshes every 5 seconds."),
      h("div", { class: "grid" },
        h("div", { class: "card" }, h("h2", {}, "Battle host ", hostPill),
          h("dl", { class: "kv" },
            h("dt", { text: "Last poll" }), h("dd", { text: ago(host.last_poll_age) }),
            h("dt", { text: "Running since" }), h("dd", { text: host.started ? new Date(host.started * 1000).toLocaleString("en-US") : "–" }),
            h("dt", { text: "Revision" }), h("dd", { text: `${host.revision ?? "–"} (file: ${host.file_revision ?? "–"})` }),
            h("dt", { text: "Running" }), h("dd", { class: "mono", text: host.running_start || "–" }),
            h("dt", { text: "Restart" }), h("dd", {}, host.restart_needed ? h("span", { class: "pill warn", text: "needed" }) : h("span", { class: "pill", text: "not needed" }),
              " ", h("span", { class: "muted", text: host.restart_method ? `via ${host.restart_method === "control" ? "watchdog" : "command"}` : "no method configured" })),
            watchdog ? [h("dt", { text: "Watchdog" }), h("dd", { text: watchdog })] : null),
          h("div", { class: "actions" },
            h("button", { text: "Restart map", title: "Same mode: new revision, the host reloads the map (e.g. after the match timer ran out)", onclick: (e) => run(e.target, async () => { const r = await api("/api/host/reload-map", {}); toast(`Revision ${r.revision} – the host reloads the map`); }) }),
            h("button", { text: "Restart host", disabled: !host.restart_method, onclick: (e) => restartHost(e.target) }))),
        h("div", { class: "card" }, h("h2", { text: "Services" }),
          h("dl", { class: "kv" },
            h("dt", { text: "CREST server" }), h("dd", {}, h("span", { class: "pill ok", text: "running" }), ` since ${new Date(s.server_started * 1000).toLocaleString("en-US")}`),
            h("dt", { text: "CATMA service" }), h("dd", {}, s.catma.ok ? h("span", { class: "pill ok", text: "reachable" }) : h("span", { class: "pill bad", text: s.catma.error })),
            h("dt", { text: "Notification streams" }), h("dd", { text: s.notification_streams }),
            h("dt", { text: "Pending connects" }), h("dd", { text: s.pending_connects })))),
      h("div", { class: "card" }, h("h2", { text: `Battle members (${s.members.length})` }),
        s.members.length ? h("div", { class: "table-wrap" }, h("table", {},
          h("tr", {}, ["Name", "Battle ID", "Team", "Credential"].map((t) => h("th", { text: t }))),
          s.members.map((m) => h("tr", {}, h("td", { text: m.name }), h("td", { text: m.characterID }), h("td", { text: m.team === 0 ? "Attacker" : "Defender" }), h("td", { class: "mono", text: m.credential }))))) :
          h("p", { class: "muted", text: "No players have joined through the battle finder." }),
        h("div", { class: "actions" }, h("button", { class: "danger", text: "Clear list", disabled: !s.members.length, onclick: (e) => run(e.target, async () => { await api("/api/members/clear", {}); render(); }) }))),
      h("div", { class: "grid" },
        h("div", { class: "card" }, h("h2", { text: "Missing endpoints" }),
          h("p", { class: "muted", text: "Client requests that neither our handlers nor CCP's offline handlers answer (since server start)." }),
          s.missing.length ? h("table", {}, s.missing.map(([k, n]) => h("tr", {}, h("td", { class: "mono", text: k }), h("td", { class: "num", text: n })))) : h("p", { class: "muted", text: "None." })),
        h("div", { class: "card" }, h("h2", { text: "Recent requests" }),
          h("div", { class: "table-wrap tree" }, h("table", {},
            h("tr", {}, ["Time", "Port", "Request", "Status", "Source"].map((t) => h("th", { text: t }))),
            s.recent.slice().reverse().filter((r) => !/\/dev\/(commands|battle\/members)\/|\/vivox\//.test(r.request || "")).slice(0, 80).map((r) =>
              h("tr", {}, h("td", { text: (r.time || "").slice(11, 19) }), h("td", { text: r.port }), h("td", { class: "mono", text: (r.request || "").replace(/ HTTP\/1\.1$/, "") }),
                h("td", {}, h("span", { class: "pill " + (r.status >= 500 ? "bad" : r.status >= 400 ? "warn" : "ok"), text: r.status })), h("td", { class: "mono", text: r.source })))))),
      ));
  };
  await render();
  pageTimer = setInterval(() => render().catch(() => {}), 5000);
}

// --- host -----------------------------------------------------------------------------------------

async function pageHost(el) {
  const [data, cat] = await Promise.all([api("/api/host"), loadCatalog()]);
  const s = clone(data.settings);
  const tested = data.tested_modes;
  // Live combinations: CATMA marks them production ready and used in matchmaking. The rest are test maps,
  // copies, 48p variants and sublevels that never ran in the live game.
  const official = (m) => m.productionReady && m.matchmaking;
  const officialLevel = (l) => l.modes.some(official);
  let showAll = false;
  const levels = cat.levels.slice().sort((a, b) => (officialLevel(b) - officialLevel(a)) || a.map.localeCompare(b.map) || a.typeName.localeCompare(b.typeName));
  const levelLabel = (l) => `${l.name || l.typeName} – ${l.map} (${l.id})${officialLevel(l) ? "" : l.productionReady ? " · not in live matchmaking" : " · unfinished"}`;
  const modeLabel = (m) => official(m) ? "" : m.productionReady ? " · not in live matchmaking" : " · unfinished";
  const gameTypeName = (id) => { const t = cat.gameTypes.get(id); return t ? (t.name || t.typeName) : String(id); };

  const levelSel = h("select");
  const modeSel = h("select");
  const terraformSel = h("select");
  const lightingSel = h("select");
  const customMap = textInput(s.map, (v) => { s.map = v; });
  const customType = textInput(s.game_type, (v) => { s.game_type = v; });
  const customLevel = textInput(s.game_mode_level, (v) => { s.game_mode_level = v; });
  const modeInfo = h("div", { class: "muted" });

  const levelFor = () => levels.find((l) => l.id === Number(s.bfid));
  const fillOptions = (sel, options, value) => {
    sel.replaceChildren(...options.map(([v, label]) => h("option", { value: v, text: label })));
    if (value !== undefined && options.some(([v]) => String(v) === String(value))) sel.value = value;
  };

  function refreshLevel(keepMode) {
    const level = levelFor();
    if (!level) return;
    s.map = level.map;
    customMap.value = s.map;
    let current = level.modes.findIndex((m) => m.level === s.game_mode_level && (cat.gameTypes.get(m.gameType) || {}).typeName === s.game_type);
    if (current < 0 && keepMode) {
      const pick = (pred) => level.modes.findIndex((m) => (showAll || official(m)) && pred(m));
      current = pick((m) => (cat.gameTypes.get(m.gameType) || {}).typeName === s.game_type);
      if (current < 0) current = pick(() => true);
      if (current < 0) current = 0;
    }
    fillModes(level, current);
    if (current >= 0) applyMode(level.modes[current], !keepMode);
    fillOptions(terraformSel, level.terraforming.map((t) => [t, t]), s.terraform);
    if (!level.terraforming.includes(s.terraform)) { s.terraform = level.terraforming[0] || s.terraform; terraformSel.value = s.terraform; }
    const lighting = [[data.tested_lighting, `${data.tested_lighting} (tested)`], ...level.moods.map((m) => [m, `${m} (untested)`])];
    if (!lighting.some(([v]) => v === s.lighting)) lighting.push([s.lighting, s.lighting]);
    fillOptions(lightingSel, lighting, s.lighting);
  }

  function fillLevels() {
    // The selected level stays in the list even if it is not a live one.
    fillOptions(levelSel, levels.filter((l) => showAll || officialLevel(l) || l.id === Number(s.bfid)).map((l) => [l.id, levelLabel(l)]), s.bfid);
    if (!levelFor()) levelSel.prepend(h("option", { value: s.bfid, text: `bfid ${s.bfid} (not in the catalog)` })), levelSel.value = s.bfid;
  }

  function fillModes(level, current) {
    // The selected mode stays in the list even if it is not a live combination.
    const modes = level.modes.map((m, i) => [m, i]).filter(([m, i]) => showAll || official(m) || i === current).map(([m, i]) => {
      const status = tested[m.level] ? ` · ${tested[m.level]}` : "";
      return [i, `${gameTypeName(m.gameType)} – ${m.level}${modeLabel(m)}${status}`];
    });
    // Initial load with values that are not in the level's list: keep them.
    if (current < 0) modes.unshift([-1, `custom values: ${s.game_type} / ${s.game_mode_level}`]);
    fillOptions(modeSel, modes, current);
  }

  function applyMode(mode, keepName = false) {
    // keepName: initial load, the saved mode name may be a custom one.
    if (!mode) return;
    const t = cat.gameTypes.get(mode.gameType) || {};
    s.game_type = t.typeName || s.game_type;
    s.game_mode_level = mode.level;
    s.mode_id = mode.gameType;
    if (!keepName) s.mode_name = t.name || t.typeName || s.mode_name;
    customType.value = s.game_type;
    customLevel.value = s.game_mode_level;
    modeNameInput.value = s.mode_name;
    applyModeInfo();
  }

  fillLevels();
  const showAllBox = checkbox(showAll, (v) => {
    showAll = v;
    fillLevels();
    if (levelFor()) fillModes(levelFor(), Number(modeSel.value));
  }, "also list combinations that never ran in live matchmaking (test maps, copies, 48p, unfinished)");
  levelSel.addEventListener("change", () => { s.bfid = Number(levelSel.value); refreshLevel(true); });
  modeSel.addEventListener("change", () => { if (Number(modeSel.value) >= 0) applyMode(levelFor().modes[Number(modeSel.value)]); });
  terraformSel.addEventListener("change", () => { s.terraform = terraformSel.value; });
  lightingSel.addEventListener("change", () => { s.lighting = lightingSel.value; });
  const modeNameInput = textInput(s.mode_name, (v) => { s.mode_name = v; });

  const result = h("div");
  async function save(button, apply) {
    await run(button, async () => {
      const r = await api("/api/host", { settings: s, apply });
      startPreview.textContent = r.start_command;
      let message;
      if (r.restart_needed) message = h("div", { class: "banner warn" }, "Saved. The running host has a different mode or map – that needs a restart (switching in place crashes it).",
        h("button", { class: "primary", text: "Restart host", onclick: (e) => restartHost(e.target) }));
      else if (r.applied_in_place) message = h("div", { class: "banner warn" }, `Saved, revision ${r.revision}: the host reloads the map in a few seconds.`);
      else if (!r.host_online) message = h("div", { class: "banner warn" }, "Saved. The host is offline right now – the settings apply on its next start.");
      else message = h("div", { class: "banner warn" }, "Saved. The host picks them up on the next map start (\"Save & apply\" or \"Restart map\").");
      result.replaceChildren(message);
      updateBanner();
    });
  }
  const startPreview = h("div", { class: "preview mono", text: s.start_command || "–" });

  el.replaceChildren(
    head("Battle host", "Map and mode of the listen server (dev_commands.json) and the entry in the battle finder (fake_battle.json)."),
    h("div", { class: "card" }, h("h2", { text: "Map and mode" }),
      h("div", { class: "form" },
        field("Level (bfid)", levelSel),
        field("Unofficial", showAllBox, "By default only the map and mode combinations of the live game (CATMA: production ready and used in matchmaking)."),
        field("Mode", h("div", {}, modeSel, modeInfo)),
        field("Terraform", terraformSel),
        field("Lighting", lightingSel, "Only MOOD_DAY has been tested with the listen server so far."),
        field("Map name", customMap, "Taken from the level; only change it if you know what you are doing."),
        field("gametype", customType),
        field("gameModeLevel", customLevel)),
      h("h3", { text: "Current start command" }), startPreview),
    h("div", { class: "card" }, h("h2", { text: "Battle and teams" }),
      h("div", { class: "form" },
        field("Battle ID", numberInput(s.battle_id, (v) => { s.battle_id = v; }), "The host's ?battleID= and the ID in the battle finder"),
        field("Battle name", textInput(s.battle_name, (v) => { s.battle_name = v; }), "Name in the battle finder; clients started with -autologinbattle=<name> join automatically"),
        field("Mode name", modeNameInput, "Shown on the deploy map"),
        field("Host player name", textInput(s.host_name, (v) => { s.host_name = v; })),
        field("Host team", select([["0", "0 – Attacker"], ["1", "1 – Defender"]], String(s.host_team), (v) => { s.host_team = Number(v); })),
        field("Client team", select([["defender", "Defender"], ["attacker", "Attacker"]], s.client_team, (v) => { s.client_team = v; })))),
    h("div", { class: "card" }, h("h2", { text: "Battle finder" }),
      h("div", { class: "form" },
        field("Show battle", checkbox(s.finder_enabled, (v) => { s.finder_enabled = v; }, "list it in the battle finder")),
        field("Address for clients", textInput(s.listen_address, (v) => { s.listen_address = v; }), "IP or host name players reach the host at (in a data center: the public address)"),
        field("UDP port", numberInput(s.listen_port, (v) => { s.listen_port = v; })),
        field("Theatre name", textInput(s.theatre_name, (v) => { s.theatre_name = v; })),
        field("Theatre description", textInput(s.theatre_description, (v) => { s.theatre_description = v; }))),
      s.variant !== "listen" ? h("p", { class: "error", text: `fake_battle.json uses variant "${s.variant}", not "listen".` }) : null),
    h("div", { class: "actions" },
      h("button", { class: "primary", text: "Save & apply", title: "Same mode: the map restarts right away. Different mode: the host needs a restart.", onclick: (e) => save(e.target, true) }),
      h("button", { text: "Save only", title: "Applies on the next map start or host restart", onclick: (e) => save(e.target, false) })),
    result);
  refreshLevel(false);
  if (!modeInfo.childNodes.length) applyModeInfo();

  function applyModeInfo() {
    const status = tested[s.game_mode_level];
    modeInfo.replaceChildren(status ? h("span", { class: "pill " + (status.startsWith("works") ? "ok" : "warn"), text: status }) : h("span", { class: "pill warn", text: "not tried on the listen server yet" }));
  }
}

// --- documents ------------------------------------------------------------------------------------

async function pageDocuments(el) {
  const data = await api("/api/documents");
  let current = data.documents[0];
  const textarea = h("textarea", { spellcheck: "true" });
  const title = h("h2");
  const list = h("div", { class: "actions" });
  const show = (doc) => {
    current = doc;
    title.textContent = `${doc.label} (${doc.key}.txt)`;
    textarea.value = doc.text;
    for (const b of list.children) b.classList.toggle("primary", b.dataset.key === doc.key);
  };
  for (const doc of data.documents) list.append(h("button", { "data-key": doc.key, text: doc.label, onclick: () => show(doc) }));
  el.replaceChildren(
    head("News & documents", "Texts the client loads at login (message of the day, important message, patch notes …). It fetches changed texts at the next login."),
    list,
    h("div", { class: "card" }, title, textarea,
      h("div", { class: "actions" }, h("button", { class: "primary", text: "Save", onclick: (e) => run(e.target, async () => {
        await api(`/api/documents/${current.key}`, { text: textarea.value });
        current.text = textarea.value;
        toast(`${current.label} saved`);
      }) }))));
  show(current);
}

// --- ISK market and AUR store ---------------------------------------------------------------------

const LOYALTY_ROOT_GROUP = 365995;  // content.LOYALTY_ROOT_GROUP; the AUR store leaves these LP items out

async function pageMarket(el, kind) {
  const isk = kind === "isk";
  const name = isk ? "market" : "aur_store";
  const [cat, config, marketConfig, effective] = await Promise.all([loadCatalog(), api(`/api/content/${name}`), isk ? null : api("/api/content/market"), api("/api/market/effective")]);
  const cfg = clone(config);
  const hiddenGroups = () => new Set((isk ? cfg : marketConfig).hidden_groups.flatMap((g) => [...cat.subtree(g)]));
  const base = (item) => (isk ? item.basePrice : item.baseAurPrice);
  const currency = isk ? "ISK" : "AUR";
  let selected = cat.root, filter = "", show = "all", page = 0;
  const PAGE = 100;

  function excludedSet() {
    return new Set(isk ? cfg.excluded_groups.flatMap((g) => [...cat.subtree(g)]) : cat.subtree(LOYALTY_ROOT_GROUP));
  }
  function state(item, excluded, hidden) {
    // Mirrors content.isk_market / content.aur_store for unsaved changes.
    const o = cfg.items[item.id] || {};
    const def = isk ? item.basePrice > 0 && !item.baseAurPrice && !excluded.has(item.categoryID) : item.baseAurPrice > 0 && !excluded.has(item.categoryID);
    const price = o.price || base(item);
    const enabled = o.enabled ?? def;
    const on = cfg.enabled && enabled && price > 0 && cat.marketGroups.has(item.categoryID) && !hidden.has(item.categoryID);
    return { def, price, enabled, on, overridden: o.enabled !== undefined || o.price !== undefined };
  }

  const tree = h("div", { class: "tree" });
  const table = h("div", { class: "table-wrap" });
  const summary = h("span", { class: "muted" });
  const pager = h("div", { class: "pager" });

  function counts() {
    const excluded = excludedSet(), hidden = hiddenGroups();
    const direct = new Map();
    let total = 0;
    for (const item of cat.items.values()) {
      if (state(item, excluded, hidden).on) {
        direct.set(item.categoryID, (direct.get(item.categoryID) || 0) + 1);
        total++;
      }
    }
    const sum = new Map();
    const walk = (g) => { let n = direct.get(g) || 0; for (const c of cat.children.get(g) || []) n += walk(c); sum.set(g, n); return n; };
    walk(cat.root);
    return { sum, total };
  }

  const open = new Set([cat.root]);
  function renderTree() {
    const { sum, total } = counts();
    const hidden = new Set(isk ? cfg.hidden_groups : marketConfig.hidden_groups);
    const node = (g) => {
      const kids = cat.children.get(g) || [];
      const row = h("div", { class: (g === selected ? "selected " : "") + (hidden.has(g) ? "hiddengroup" : ""), onclick: () => { selected = g; page = 0; renderTree(); renderTable(); } },
        h("span", { class: "twisty", text: kids.length ? (open.has(g) ? "▾" : "▸") : "", onclick: (e) => { e.stopPropagation(); open.has(g) ? open.delete(g) : open.add(g); renderTree(); } }),
        isk && g !== cat.root ? h("input", { type: "checkbox", title: "Show in the market navigation", checked: !hidden.has(g), onclick: (e) => e.stopPropagation(), onchange: (e) => {
          cfg.hidden_groups = e.target.checked ? cfg.hidden_groups.filter((x) => x !== g) : [...cfg.hidden_groups, g];
          renderTree(); renderTable();
        } }) : null,
        h("span", { class: "name", text: cat.groupName(g) }),
        h("span", { class: "count", text: sum.get(g) || "" }));
      return h("li", {}, row, kids.length && open.has(g) ? h("ul", {}, kids.map(node)) : null);
    };
    tree.replaceChildren(h("ul", {}, node(cat.root)));
    summary.textContent = `${fmt(total)} items in the ${isk ? "ISK market" : "AUR store"} (incl. unsaved changes) · server: ${fmt(Object.keys(isk ? effective.isk : effective.aur).length)}`;
  }

  function rows() {
    const groups = cat.subtree(selected);
    const excluded = excludedSet(), hidden = hiddenGroups();
    const q = filter.toLowerCase();
    return cat.itemsSorted.filter((item) => groups.has(item.categoryID) && (!q || item.name.toLowerCase().includes(q) || item.typeName.toLowerCase().includes(q) || String(item.id) === q))
      .map((item) => ({ item, st: state(item, excluded, hidden) }))
      .filter(({ st }) => show === "all" || (show === "on" ? st.on : show === "off" ? !st.on : st.overridden));
  }

  function setOverride(id, key, value) {
    const o = { ...(cfg.items[id] || {}) };
    if (value === null || value === undefined) delete o[key]; else o[key] = value;
    if (Object.keys(o).length) cfg.items[id] = o; else delete cfg.items[id];
  }

  function renderTable() {
    const list = rows();
    const pages = Math.max(1, Math.ceil(list.length / PAGE));
    page = Math.min(page, pages - 1);
    const slice = list.slice(page * PAGE, page * PAGE + PAGE);
    table.replaceChildren(h("table", {},
      h("tr", {}, h("th", { text: "Item" }), h("th", { text: "Group" }), h("th", { class: "num", text: `Base (${currency})` }), h("th", { text: `Price (${currency})` }), h("th", { text: "Offered" }), h("th", { text: "" })),
      slice.map(({ item, st }) => {
        const o = cfg.items[item.id] || {};
        const mode = o.enabled === undefined ? "default" : o.enabled ? "on" : "off";
        return h("tr", { class: (st.on ? "" : "off") + (st.overridden ? " changed" : "") },
          h("td", {}, item.name, h("div", { class: "muted mono", text: `${item.typeName} · ${item.id}` })),
          h("td", { text: cat.groupName(item.categoryID) }),
          h("td", { class: "num", text: fmt(base(item)) }),
          h("td", {}, numberInput(o.price, (v) => { setOverride(item.id, "price", v || null); renderTree(); }, { placeholder: base(item) || "Price", min: 1 })),
          h("td", {}, select([["default", `default (${st.def ? "on" : "off"})`], ["on", "on"], ["off", "off"]], mode, (v) => {
            setOverride(item.id, "enabled", v === "default" ? null : v === "on"); renderTree(); renderTable();
          })),
          h("td", {}, h("span", { class: "pill " + (st.on ? "ok" : ""), text: st.on ? `${fmt(st.price)} ${currency}` : "not offered" })));
      })));
    pager.replaceChildren(
      h("button", { text: "‹", disabled: page === 0, onclick: () => { page--; renderTable(); } }),
      h("span", { text: `Page ${page + 1} / ${pages} · ${fmt(list.length)} items` }),
      h("button", { text: "›", disabled: page >= pages - 1, onclick: () => { page++; renderTable(); } }));
  }

  function bulk(value) {
    for (const { item } of rows()) {
      if (value === "reset") delete cfg.items[item.id];
      else setOverride(item.id, "enabled", value);
    }
    renderTree(); renderTable();
  }

  const excludedChips = h("span");
  function renderExcluded() {
    if (!isk) return;
    excludedChips.replaceChildren(...cfg.excluded_groups.map((g) => h("span", { class: "pill" }, cat.groupName(g), " ",
      h("button", { class: "link", text: "×", title: "remove", onclick: () => { cfg.excluded_groups = cfg.excluded_groups.filter((x) => x !== g); renderExcluded(); renderTree(); renderTable(); } }))));
  }

  el.replaceChildren(
    head(isk ? "ISK market" : "AUR store", isk
      ? "Items with an ISK price in the marketplace. Default: every item with a base price in the game database, except AUR items and loyalty groups."
      : "Offers of the Virtual Goods Store (Aurum). Default: every item with an AUR base price in the game database."),
    h("div", { class: "card" },
      h("div", { class: "toolbar" },
        checkbox(cfg.enabled, (v) => { cfg.enabled = v; renderTree(); renderTable(); }, isk ? "ISK market enabled" : "AUR store enabled"),
        summary),
      isk ? h("div", { class: "toolbar" }, h("span", { class: "muted", text: "Groups without default ISK offers:" }), excludedChips,
        h("button", { text: "Add selected group", onclick: () => { if (!cfg.excluded_groups.includes(selected)) cfg.excluded_groups.push(selected); renderExcluded(); renderTree(); renderTable(); } })) : null,
      h("p", { class: "muted", text: "The client loads market and store once per login – changes show up after the next login." + (isk ? " Tree checkboxes: show the group in the market navigation." : "") })),
    h("div", { class: "split" },
      h("div", { class: "card" }, tree),
      h("div", { class: "card" },
        h("div", { class: "toolbar" },
          h("input", { type: "text", placeholder: "Search (name, typeName, ID)", oninput: (e) => { filter = e.target.value; page = 0; renderTable(); } }),
          select([["all", "all"], ["on", "offered"], ["off", "not offered"], ["changed", "changed"]], show, (v) => { show = v; page = 0; renderTable(); }),
          h("span", { class: "muted", text: "Filtered:" }),
          h("button", { text: "on", onclick: () => bulk(true) }),
          h("button", { text: "off", onclick: () => bulk(false) }),
          h("button", { text: "default", onclick: () => bulk("reset") })),
        table, pager)),
    h("div", { class: "actions" }, h("button", { class: "primary", text: "Save", onclick: (e) => run(e.target, async () => {
      await api(`/api/content/${name}`, cfg);
      Object.assign(effective, await api("/api/market/effective"));
      renderTree();
      toast(`${isk ? "ISK market" : "AUR store"} saved`);
    }) })));
  renderExcluded();
  renderTree();
  renderTable();
}

// --- storefront -----------------------------------------------------------------------------------

const SF_BLOCKS = {
  topRightData: "Top right (large)", bigSliderData: "Slider", bottomRightData: "Bottom right (list)",
  bottomSmallLeftData: "Bottom left (small)", bottomSmallRightData: "Bottom right (small)",
};
const SF_FLAGS = {
  showPrice: "Show price", currencyIsAUR: "Price in AUR", isPSNStoreItem: "PSN Store item", showPlaystationStoreLogo: "PS Store logo",
  showNewIcon: "\"New\"", showHotIcon: "\"Hot\"", showSpecialItemIcon: "Special icon",
};
const SF_ITEM = () => ({ showHotIcon: null, index: null, showPrice: true, showNewIcon: null, description: null, title: null, image: null, tagImage: null,
  bgImage: null, header: null, currencyIsAUR: true, catmaID: null, isPSNStoreItem: false, showPlaystationStoreLogo: false, price: null, showSpecialItemIcon: false });

async function pageStorefront(el) {
  const [cat, data] = await Promise.all([loadCatalog(), api("/api/content/storefront")]);
  const layout = clone(data.layout || data.ccp_default || {});
  const custom = !!data.layout;
  const itemNames = h("datalist", { id: "sf-items" }, cat.itemsSorted.map((i) => h("option", { value: `${i.id} ${i.name}` })));

  const itemEditor = (item, onRemove) => {
    const resolved = h("span", { class: "muted" });
    const resolve = () => { const i = cat.items.get(Number(item.catmaID)); resolved.textContent = item.catmaID ? (i ? `${i.name} (${fmt(i.basePrice)} ISK / ${fmt(i.baseAurPrice)} AUR)` : "not in the catalog") : "no item (text tile)"; };
    resolve();
    const catma = h("input", { type: "text", list: "sf-items", value: item.catmaID ?? "", placeholder: "Item ID or name", oninput: (e) => {
      const id = parseInt(e.target.value, 10);
      item.catmaID = Number.isFinite(id) ? id : null;
      resolve();
    } });
    return h("div", { class: "sf-item" },
      h("div", { class: "form" },
        field("Item (catmaID)", h("div", {}, catma, resolved)),
        field("Title", textInput(item.title, (v) => { item.title = v || null; })),
        field("Description", textInput(item.description, (v) => { item.description = v || null; })),
        field("Price", numberInput(item.price, (v) => { item.price = v; }), "empty = price from market/store"),
        field("Image URL", textInput(item.image, (v) => { item.image = v || null; })),
        field("Options", h("div", { class: "checks" }, Object.entries(SF_FLAGS).map(([k, label]) => checkbox(item[k], (v) => { item[k] = v; }, label))))),
      onRemove ? h("div", { class: "actions" }, h("button", { class: "danger", text: "Remove tile", onclick: onRemove })) : null);
  };

  const blocks = h("div");
  const render = () => {
    blocks.replaceChildren(...Object.keys(layout).filter((k) => layout[k] && typeof layout[k] === "object").map((key) => {
      const block = layout[key];
      const body = h("div");
      if (block.item) body.append(itemEditor(block.item));
      if (Array.isArray(block.items)) {
        block.items.forEach((item, i) => body.append(itemEditor(item, () => { block.items.splice(i, 1); render(); })));
        body.append(h("div", { class: "actions" }, h("button", { text: "Add tile", onclick: () => { block.items.push(SF_ITEM()); render(); } })));
      }
      return h("div", { class: "card sf-block" }, h("h2", { text: SF_BLOCKS[key] || key }),
        "header" in block || Array.isArray(block.items) ? h("div", { class: "form" }, field("Heading", textInput(block.header, (v) => { block.header = v || null; }))) : null,
        body);
    }));
  };
  render();
  el.replaceChildren(
    head("Marketplace start page", custom ? "Custom start page active." : "Currently CCP's offline start page; saving turns it into a custom one."),
    itemNames, blocks,
    h("div", { class: "actions" },
      h("button", { class: "primary", text: "Save", onclick: (e) => run(e.target, async () => { await api("/api/content/storefront", { layout }); toast("Start page saved"); }) }),
      h("button", { class: "danger", text: "Restore CCP default", onclick: (e) => run(e.target, async () => { await api("/api/content/storefront", { layout: null }); toast("CCP default active"); route(); }) })));
}

// --- loyalty --------------------------------------------------------------------------------------

const LOYALTY_GROUPS = { 1000262: 365996, 1000198: 365997, 1000263: 365998, 1000261: 365999 };

async function pageLoyalty(el) {
  const [cat, data] = await Promise.all([loadCatalog(), api("/api/content/loyalty")]);
  const cfg = clone(data);
  const cards = h("div");
  const render = () => {
    cards.replaceChildren(...Object.entries(LOYALTY_GROUPS).map(([corp, group]) => {
      const store = cfg.stores[corp] || (cfg.stores[corp] = { balance: 0, offers: {} });
      const groupItems = cat.itemsSorted.filter((i) => cat.subtree(group).has(i.categoryID));
      const listId = `lp-${corp}`;
      const add = h("input", { type: "text", list: listId, placeholder: "Add item (ID or name)" });
      const offers = Object.entries(store.offers).sort((a, b) => (cat.items.get(+a[0]) || {}).name?.localeCompare((cat.items.get(+b[0]) || {}).name || "") || 0);
      return h("div", { class: "card" }, h("h2", { text: cat.groupName(group) }),
        h("div", { class: "form" }, field("LP balance", numberInput(store.balance, (v) => { store.balance = v || 0; }))),
        h("h3", { text: `Offers (${offers.length})` }),
        offers.length ? h("div", { class: "table-wrap" }, h("table", {},
          h("tr", {}, h("th", { text: "Item" }), h("th", { text: "LP" }), h("th", { text: "ISK" }), h("th", { text: "" })),
          offers.map(([id, offer]) => h("tr", {},
            h("td", { text: (cat.items.get(+id) || {}).name || id }),
            h("td", {}, numberInput(offer.lp, (v) => { offer.lp = v || 0; })),
            h("td", {}, numberInput(offer.isk, (v) => { offer.isk = v || 0; })),
            h("td", {}, h("button", { class: "danger", text: "×", onclick: () => { delete store.offers[id]; render(); } })))))) : h("p", { class: "muted", text: "No offers." }),
        h("datalist", { id: listId }, groupItems.map((i) => h("option", { value: `${i.id} ${i.name}` }))),
        h("div", { class: "actions" }, add,
          h("button", { text: "Add", onclick: () => {
            const id = parseInt(add.value, 10);
            const item = cat.items.get(id);
            if (!item) return toast("Item not in the catalog", true);
            store.offers[id] = { lp: Math.max(1, Math.round(item.basePrice / 10)), isk: 0 };
            render();
          } }),
          h("button", { text: `All ${groupItems.length} items of the faction`, title: "Suggested: LP = base price / 10, ISK = 0", onclick: () => {
            for (const i of groupItems) if (!store.offers[i.id]) store.offers[i.id] = { lp: Math.max(1, Math.round(i.basePrice / 10)), isk: 0 };
            render();
          } })));
    }));
  };
  render();
  el.replaceChildren(
    head("Loyalty stores", "The four faction stores (LP). Offers show up in the marketplace under the item's group; suggested price LP = base price / 10."),
    cards,
    h("div", { class: "actions" }, h("button", { class: "primary", text: "Save", onclick: (e) => run(e.target, async () => { await api("/api/content/loyalty", cfg); toast("Loyalty stores saved"); }) })));
}

// --- rewards and wallet ---------------------------------------------------------------------------

async function pageRewards(el) {
  const cfg = clone(await api("/api/content/rewards"));
  const body = h("div");
  const render = () => body.replaceChildren(h("table", {},
    h("tr", {}, h("th", { text: "Login day" }), h("th", { text: "Skill points" }), h("th", { text: "Aurum" }), h("th", { text: "" })),
    cfg.daily_login.map((d, i) => h("tr", {}, h("td", { text: `Day ${i + 1}` }),
      h("td", {}, numberInput(d.sp, (v) => { d.sp = v || 0; })),
      h("td", {}, numberInput(d.aur, (v) => { d.aur = v || 0; })),
      h("td", {}, h("button", { class: "danger", text: "×", disabled: cfg.daily_login.length <= 1, onclick: () => { cfg.daily_login.splice(i, 1); render(); } }))))));
  render();
  el.replaceChildren(
    head("Login rewards", "Reward per consecutive login day, shown on the welcome screen."),
    h("div", { class: "card" }, body,
      h("div", { class: "actions" },
        h("button", { text: "Add day", disabled: cfg.daily_login.length >= 31, onclick: () => { cfg.daily_login.push({ sp: 0, aur: 0 }); render(); } }),
        h("button", { class: "primary", text: "Save", onclick: (e) => run(e.target, async () => { await api("/api/content/rewards", cfg); toast("Login rewards saved"); }) }))),
    h("p", { class: "muted", text: "The battle finder text (theatre name and description) is set under Battle host." }));
}

async function pageWallet(el) {
  const cfg = clone(await api("/api/content/wallet"));
  el.replaceChildren(
    head("Wallet", "Balance of the offline character shown by the client (applies to every player using CCP's offline character). With DUST_CHAR_STORE=1, own characters have their own ISK; AUR stays shared here."),
    h("div", { class: "card" },
      h("div", { class: "form" },
        field("ISK", numberInput(cfg.isk, (v) => { cfg.isk = v || 0; })),
        field("Aurum (AUR)", numberInput(cfg.aur, (v) => { cfg.aur = v || 0; }))),
      h("p", { class: "muted", text: "Loyalty points are set per faction under Loyalty stores. Purchases are not stored yet, so buying does not change the balance." }),
      h("div", { class: "actions" }, h("button", { class: "primary", text: "Save", onclick: (e) => run(e.target, async () => { await api("/api/content/wallet", cfg); toast("Wallet saved – applies at the next login"); }) }))));
}

// --- characters (store.py, DUST_CHAR_STORE=1) -----------------------------------------------------

const openSkillEditors = new Set();  // character IDs whose skill list is expanded, kept across reloads

async function pageCharacters(el) {
  const data = await api("/api/characters");
  const intro = head("Characters", "Accounts (RPCN online ID) and their characters. Total SP include passive gain; free SP = total minus the cost of all known skills. Changes reach a logged-in client right away.");
  if (!data.enabled) {
    el.replaceChildren(intro, h("div", { class: "card" }, h("p", { class: "muted", text: "Own characters are off: start the server with DUST_CHAR_STORE=1. Until then every player uses CCP's offline characters." })));
    return;
  }
  let skillData = null;
  try { skillData = await api("/api/skills"); } catch (e) { /* CATMA service without GET /skills: no skill editor */ }
  const skillById = new Map((skillData ? skillData.skills : []).map((s) => [s.id, s]));
  const skillName = (id) => (skillById.get(id) || { name: `Skill ${id}` }).name;
  const levels = (max) => Array.from({ length: max + 1 }, (_, l) => [String(l), l === 0 ? "0 (book)" : String(l)]);
  const save = (button, id, body, message) => run(button, async () => { await api(`/api/characters/${id}`, body); toast(message); await pageCharacters(el); });

  const skillEditor = (c) => {
    const known = [...c.skills].sort((a, b) => skillName(a.id).localeCompare(skillName(b.id)));
    const listId = `skills-${c.id}`;
    const add = { name: "", level: "1" };
    return h("tr", {}, h("td", { colspan: 7 },
      h("table", {},
        h("tr", {}, ["Skill", "Level", "SP spent", ""].map((t) => h("th", { text: t }))),
        known.map((k) => h("tr", {},
          h("td", { text: `${skillName(k.id)} (${k.id})` }),
          h("td", {}, select(levels(skillData.maxLevel), String(k.level), (v) => save(null, c.id, { skill: { typeID: k.id, level: Number(v) } }, `${skillName(k.id)}: level ${v}`))),
          h("td", { text: fmt(skillById.has(k.id) ? skillById.get(k.id).cost[k.level] : null) }),
          h("td", {}, h("button", { class: "danger", text: "×", title: "Remove the skill", onclick: (e) => save(e.target, c.id, { skill: { typeID: k.id, level: null } }, `${skillName(k.id)} removed`) }))))),
      h("div", { class: "toolbar" },
        h("input", { type: "text", placeholder: "Add skill by name …", list: listId, oninput: (e) => { add.name = e.target.value; } }),
        h("datalist", { id: listId }, skillData.skills.filter((s) => !c.skills.some((k) => k.id === s.id)).map((s) => h("option", { value: s.name }))),
        select(levels(skillData.maxLevel), add.level, (v) => { add.level = v; }),
        h("button", { text: "Set", onclick: (e) => {
          const skill = skillData.skills.find((s) => s.name.toLowerCase() === add.name.trim().toLowerCase());
          if (!skill) { toast("Unknown skill name", true); return; }
          save(e.target, c.id, { skill: { typeID: skill.id, level: Number(add.level) } }, `${skill.name}: level ${add.level}`);
        } })),
      h("p", { class: "muted", text: "No prerequisite or SP check here: any state can be set. Level 0 = skill book read, nothing trained." })));
  };

  const rows = (c) => {
    const edit = {};  // only changed fields: the shown total SP may already be behind the passive gain
    const open = openSkillEditors.has(c.id);
    const main = h("tr", {},
      h("td", { text: `${c.name} (${c.id})` }),
      h("td", {}, numberInput(c.sp, (v) => { edit.sp = v || 0; })),
      h("td", { text: fmt(c.free_sp) }),
      h("td", { text: c.passive ? `${fmt(c.sp_per_day)} / day` : "off" }),
      h("td", {}, numberInput(c.isk, (v) => { edit.isk = v || 0; })),
      h("td", {}, skillData
        ? h("button", { text: `${c.skills.length} ${open ? "▲" : "▼"}`, title: "Show and edit the skills", onclick: () => { open ? openSkillEditors.delete(c.id) : openSkillEditors.add(c.id); pageCharacters(el); } })
        : h("span", { text: fmt(c.skills.length) })),
      h("td", {},
        h("button", { class: "primary", text: "Save", onclick: (e) => save(e.target, c.id, edit, `${c.name} saved`) }), " ",
        h("button", { class: "danger", text: "Reset skills", title: "Back to the specialty's starting skills", onclick: (e) => {
          if (confirm(`Reset all skills of ${c.name} to the starting skills?`)) save(e.target, c.id, { reset_skills: true }, `Skills of ${c.name} reset`);
        } })));
    return open && skillData ? [main, skillEditor(c)] : [main];
  };
  el.replaceChildren(intro, ...(data.users.length ? data.users.map((u) => h("div", { class: "card" },
    h("h3", { text: `${u.online_id} (user ${u.id})` }),
    u.characters.length ? h("table", {},
      h("tr", {}, ["Character", "Total SP", "Free SP", "Passive gain", "ISK", "Skills", ""].map((t) => h("th", { text: t }))),
      u.characters.flatMap(rows)) : h("p", { class: "muted", text: "No characters." }))) : [h("div", { class: "card" }, h("p", { class: "muted", text: "No accounts yet – they are created at the first login." }))]));
  if (!skillData) el.append(h("p", { class: "muted", text: "Skill editor unavailable: the CATMA service does not serve /skills yet (restart it)." }));
}

// --- start ----------------------------------------------------------------------------------------

api("/api/status").then(showApp).catch((e) => { if (!(e instanceof ApiError)) toast(e.message, true); });
