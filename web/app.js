// ChitAI — Cosmic Edition browser client. Presentation only: every rule, legality
// check and score comes from the server (the authoritative engine). The client
// never sends a seat, never computes a result and never sees another hand.
"use strict";

const $ = (id) => document.getElementById(id);
let ws = null;
let last = null;          // latest "state" message from the server
let logLines = [];        // public log entries (server already filtered them per seat)
let selected = null;      // index into the displayed hand
let timerInfo = null;     // {seat, deadline, total}
let lastResult = null;    // round-result card data, built only from server events

// ---------------------------------------------------------------- presentation
// Symbols and colours are display-only; matching always uses the chit name.
const CHIT_STYLE = {
  Sun:   { color: "#ffc857", svg: '<circle cx="12" cy="12" r="4.5"/><path d="M12 2.5v3M12 18.5v3M2.5 12h3M18.5 12h3M5.3 5.3l2.1 2.1M16.6 16.6l2.1 2.1M5.3 18.7l2.1-2.1M16.6 7.4l2.1-2.1"/>' },
  Moon:  { color: "#c3d0ff", svg: '<path d="M20 14.5A8.5 8.5 0 1 1 9.5 4a6.7 6.7 0 0 0 10.5 10.5z"/>' },
  Star:  { color: "#b794ff", svg: '<path d="M12 2.8l2.8 5.8 6.4.9-4.6 4.5 1.1 6.3-5.7-3-5.7 3 1.1-6.3L2.8 9.5l6.4-.9z"/>' },
  Cloud: { color: "#a8dcff", svg: '<path d="M17.5 18.5H8a5 5 0 1 1 1.3-9.8 5.6 5.6 0 0 1 10.6 2.3 3.8 3.8 0 0 1-2.4 7.5z"/>' },
  Flame: { color: "#ff9a62", svg: '<path d="M12 2.5c.8 3.6 5.2 5.6 5.2 10.6a5.2 5.2 0 0 1-10.4 0c0-2 .9-3.4 2.1-4.4.1 1.8.9 2.7 1.9 2.9-.6-3.4-.2-6.2 1.2-9.1z"/>' },
  Wave:  { color: "#58d6c9", open: true, svg: '<path d="M2.5 9c3-3 5-3 7.5 0s4.5 3 7.5 0 3-2 4-1.5M2.5 15c3-3 5-3 7.5 0s4.5 3 7.5 0 3-2 4-1.5"/>' },
  Leaf:  { color: "#7be08f", svg: '<path d="M5 19C4.5 10 10 4.5 20 4c0 9.5-5 15-15 15zM5 19l9-9"/>' },
  Stone: { color: "#c2b8ac", svg: '<path d="M4 15l2.5-7.5 6-3.5 6.5 4 1.5 7-6 4z"/>' },
};
const SEAT_SYMBOLS = ["Sun", "Moon", "Star", "Cloud", "Flame", "Wave", "Leaf", "Stone"];
const FALLBACK_STYLE = CHIT_STYLE.Star;

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined) n.textContent = text;   // names are always inserted as text
  return n;
}
function symbol(name) {                           // static, trusted SVG markup only
  const st = CHIT_STYLE[name] || FALLBACK_STYLE;
  const s = el("span", "sym" + (st.open ? " open" : ""));
  s.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">${st.svg}</svg>`;
  return s;
}
function isAi(seat) {
  const p = last && last.room.players.find((x) => x.seat === seat);
  return !!(p && p.ai);
}
function avatar(seat, ai) {
  const name = SEAT_SYMBOLS[seat % SEAT_SYMBOLS.length];
  const a = el("span", "avatar" + (ai ? " ai" : ""));
  a.style.color = (CHIT_STYLE[name] || FALLBACK_STYLE).color;
  a.appendChild(symbol(name));
  return a;
}
function toast(text, kind, ms) {
  const t = el("div", "toast " + (kind || "info"), text);
  $("toasts").appendChild(t);
  setTimeout(() => t.remove(), ms || 4500);
}

// ---------------------------------------------------------------- connection
function connect() {
  const scheme = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${scheme}://${location.host}/ws`);
  ws.onopen = () => { setConn("connected", "ok"); show("home"); };
  ws.onclose = () => {
    setConn("disconnected", "bad");
    const o = $("offline");
    o.textContent = "Connection lost. Reload the page to start again.";
    o.classList.remove("hidden");
  };
  ws.onmessage = (e) => {
    let msg;
    try { msg = JSON.parse(e.data); } catch { return; }
    if (msg.type === "error") toast(msg.message, "error", 6000);
    else if (msg.type === "state") onState(msg);
  };
}
function send(obj) { if (ws && ws.readyState === 1) ws.send(JSON.stringify(obj)); }
function setConn(text, cls) { const c = $("conn"); c.textContent = text; c.className = "pill " + cls; }
function show(view) {
  for (const v of ["home", "lobby", "game", "over"]) $("view-" + v).classList.toggle("hidden", v !== view);
}

// ---------------------------------------------------------------- home
function fillSettings() {
  const players = $("num-players");
  for (let n = 4; n <= 8; n++) players.add(new Option(`${n} players`, String(n)));
  players.value = "4";
  const refresh = () => {
    const n = Number(players.value), rounds = $("num-rounds");
    rounds.innerHTML = "";
    for (let k = 1; k <= 5; k++) rounds.add(new Option(`${k * n} rounds`, String(k * n)));
    rounds.value = String(n);
  };
  players.onchange = () => { refresh(); refreshAi(); };
  refresh();
  document.querySelectorAll('input[name="mode"]').forEach((r) => { r.onchange = refreshAi; });
  $("num-humans").onchange = renderAiSeats;
  refreshAi();
}
function mode() { return document.querySelector('input[name="mode"]:checked').value; }
const AGENT_CHOICES = [["rulebot", "RuleBot (rule-based baseline)"], ["mindbot", "MindBot (behavioural inference)"]];
const DEFAULT_AGENTS = ["rulebot", "mindbot", "rulebot"];
let agentPicks = [];     // chosen strategy per AI seat, kept while the form is adjusted
function refreshAi() {
  const on = mode() === "ai";
  $("ai-config").classList.toggle("hidden", !on);
  if (!on) return;
  const n = Number($("num-players").value), humans = $("num-humans");
  const keep = Math.min(Number(humans.value) || 1, n - 1);
  humans.innerHTML = "";
  for (let h = 1; h <= n - 1; h++) humans.add(new Option(`${h} human${h > 1 ? "s" : ""}`, String(h)));
  humans.value = String(Math.max(1, keep));
  renderAiSeats();
}
function renderAiSeats() {
  const n = Number($("num-players").value), h = Number($("num-humans").value) || 1, ai = n - h;
  $("ai-summary").textContent = `${h} human + ${ai} AI = ${n} players. Humans take the first ${h} seat${h > 1 ? "s" : ""}.`;
  const box = $("ai-seats");
  box.innerHTML = "";
  for (let i = 0; i < ai; i++) {
    if (!agentPicks[i]) agentPicks[i] = DEFAULT_AGENTS[i % DEFAULT_AGENTS.length];
    const row = el("div", "aiseat");
    const lab = el("label", "", `Seat ${h + i + 1}`);
    lab.htmlFor = `ai-seat-${i}`;
    const sel = el("select");
    sel.id = `ai-seat-${i}`;
    AGENT_CHOICES.forEach(([v, t]) => sel.add(new Option(t, v)));
    sel.value = agentPicks[i];
    sel.onchange = () => { agentPicks[i] = sel.value; };
    row.appendChild(lab); row.appendChild(sel); box.appendChild(row);
  }
}
function needName() {
  if ($("name").value.trim()) return false;
  toast("Please enter a display name first.", "error");
  $("name").focus();
  return true;
}
$("btn-create").onclick = () => {
  if (needName()) return;
  const msg = { type: "create_room", name: $("name").value,
    num_players: Number($("num-players").value), num_rounds: Number($("num-rounds").value),
    timeout_seconds: Number($("timeout").value) };
  if (mode() === "ai") {
    // The server validates this lineup; it is the only place a client names agent types.
    const n = msg.num_players, h = Number($("num-humans").value);
    msg.mode = "ai";
    msg.seats = [...Array(h).fill("human"), ...agentPicks.slice(0, n - h)];
  }
  send(msg);
};
$("btn-join").onclick = () => {
  if (needName()) return;
  if (!$("code").value.trim()) { toast("Enter the room code from your host.", "error"); $("code").focus(); return; }
  send({ type: "join_room", name: $("name").value, code: $("code").value });
};
$("code").addEventListener("keydown", (e) => { if (e.key === "Enter") $("btn-join").click(); });
$("name").addEventListener("keydown", (e) => { if (e.key === "Enter" && $("code").value.trim()) $("btn-join").click(); });
$("btn-start").onclick = () => send({ type: "start_game" });
$("btn-new").onclick = () => location.reload();
$("btn-copy").onclick = async () => {
  try { await navigator.clipboard.writeText(last.room.code); toast("Room code copied.", "success", 2000); }
  catch { toast("Copy is not available here. Select the code and copy it by hand.", "info"); }
};

// ---------------------------------------------------------------- state
function onState(msg) {
  const prev = last;
  last = msg;
  for (const ev of msg.events || []) { logLines.push(describe(ev)); collectResult(ev); }
  notify(prev, msg);
  const status = msg.room.status;
  document.title = `ChitAI — ${msg.room.code}`;
  if (status === "lobby") renderLobby();
  else if (status === "playing") renderGame();
  else renderOver();
}

function notify(prev, cur) {
  const names = (m) => m.room.players.map((p) => p.name);
  if (!prev) { toast(`You are in room ${cur.room.code}.`, "success"); return; }
  if (prev.room.status === "lobby" && cur.room.status === "lobby") {
    const before = names(prev), now = names(cur);
    now.filter((n) => !before.includes(n)).forEach((n) => toast(`${n} joined the room.`, "info"));
    before.filter((n) => !now.includes(n)).forEach((n) => toast(`${n} left the room.`, "info"));
  }
  if (prev.room.status === "lobby" && cur.room.status === "playing") toast("The game has started. Good luck!", "success");
  if (cur.room.status !== "lobby") {
    cur.room.players.forEach((p, i) => {
      const was = prev.room.players[i];
      if (was && was.connected && !p.connected) toast(`${p.name} disconnected. The game goes on and timers keep running.`, "info", 6000);
    });
  }
}

function nm(seat) {
  const p = last && last.room.players[seat];
  return p ? p.name : `Seat ${seat + 1}`;
}
function scoreText(scores) { return scores.map((s, i) => `${nm(i)} ${s}`).join(", "); }

// Log wording only. No rule is evaluated here: the server says what happened.
function describe(ev) {
  const t = ev.type;
  if (t === "deal") {
    const mine = ev.my_hand ? ` Your hand: ${ev.my_hand.join(", ")}.` : "";
    return { kind: "", text: `New deal: round ${ev.completed_round + 1}, attempt ${ev.attempt}. ${nm(ev.initiator)} starts.${mine}` };
  }
  if (t === "initial_claim_declined") return { kind: "", text: `${nm(ev.seat)} declined the opening claim.` };
  if (t === "initial_claim_made") return { kind: ev.valid ? "claim" : "bad", text: `${nm(ev.seat)} claimed at the deal: ${ev.valid ? "valid" : "FALSE"}.` };
  if (t === "initial_claims_resolved") return { kind: "", text: "Opening claims finished. Passing begins." };
  if (t === "chit_passed") {
    const what = ev.chit_name ? `the ${ev.chit_name} chit` : "a chit";
    return { kind: "", text: `${nm(ev.from_seat)} passed ${what} to ${nm(ev.to_seat)}.` };
  }
  if (t === "claim_made") return { kind: ev.valid ? "claim" : "bad", text: `${nm(ev.seat)} claimed: ${ev.valid ? "valid" : "FALSE"}.` };
  if (t === "false_claim_penalized") return { kind: "bad", text: `${nm(ev.seat)} made a false claim and loses ${ev.penalty} points. Scores: ${scoreText(ev.scores)}.` };
  if (t === "player_reacted") return { kind: "claim", text: `${nm(ev.seat)} reacted (place ${ev.position}).` };
  if (t === "valid_win_scored") return { kind: "win", text: `${nm(ev.winner)} won the round. Reaction order: ${ev.reaction_order.map(nm).join(", ")}. Scores: ${scoreText(ev.scores)}.` };
  if (t === "round_completed") return { kind: "round", text: `Round ${ev.rounds_completed} complete.` };
  if (t === "decision_timed_out") return { kind: "time", text: `${nm(ev.seat)} ran out of time.` };
  if (t === "attempt_drawn") return { kind: "bad", text: `${nm(ev.seat)} passed the same chit ${ev.consecutive_passes} times in a row: draw, new deal (no points).` };
  if (t === "game_completed") return { kind: "round", text: "All rounds are complete." };
  return { kind: "", text: t };
}

// Round-result card: built only from the server's public score events.
function collectResult(ev) {
  if (ev.type === "valid_win_scored") {
    lastResult = { cls: "win", title: `${nm(ev.winner)} wins the round`,
      rows: ev.score_changes.map((d, i) => ({ seat: i, d })).sort((a, b) => b.d - a.d),
      note: `Reaction order: ${ev.reaction_order.map(nm).join(" → ")}` };
  } else if (ev.type === "false_claim_penalized") {
    lastResult = { cls: "false", title: `${nm(ev.seat)}'s claim was false`,
      rows: ev.score_changes.map((d, i) => ({ seat: i, d })).filter((r) => r.d !== 0).sort((a, b) => b.d - a.d), note: "" };
  } else if (ev.type === "attempt_drawn") {
    lastResult = { cls: "draw", title: "Draw: new deal", rows: [],
      note: `${nm(ev.seat)} passed the same chit ${ev.consecutive_passes} times in a row. No points change.` };
  }
}
function renderResult() {
  const box = $("g-result");
  box.innerHTML = "";
  if (!lastResult) { box.classList.add("hidden"); return; }
  box.className = "result " + lastResult.cls;
  const close = el("button", "btn ghost small close", "Dismiss");
  close.onclick = () => { lastResult = null; renderResult(); };
  box.appendChild(close);
  box.appendChild(el("h3", "", lastResult.title));
  if (lastResult.rows.length) {
    const ul = el("ul");
    lastResult.rows.forEach((r) => {
      const li = el("li", r.d >= 0 ? "pos" : "neg", `${nm(r.seat)} ${r.d}`);
      ul.appendChild(li);
    });
    box.appendChild(ul);
  }
  if (lastResult.note) box.appendChild(el("p", "muted", lastResult.note));
}

// ---------------------------------------------------------------- waiting room
function renderLobby() {
  show("lobby");
  const r = last.room;
  $("lobby-code").textContent = r.code;
  const humanSeats = r.seat_kinds.filter((k) => k === "human").length;
  const humansIn = r.players.filter((p) => !p.ai).length;
  const aiCount = r.num_players - humanSeats;
  const chips = $("lobby-chips");
  chips.innerHTML = "";
  [aiCount ? `${humansIn} of ${humanSeats} humans` : `${humansIn} of ${r.num_players} players`,
   ...(aiCount ? [`${aiCount} AI`] : []), `${r.num_rounds} rounds`, `${r.timeout_seconds}s decision timer`]
    .forEach((t) => chips.appendChild(el("li", "", t)));
  const grid = $("lobby-players");
  grid.innerHTML = "";
  for (let i = 0; i < r.num_players; i++) {
    const p = r.players.find((x) => x.seat === i);
    const li = el("li", "seat" + (p ? "" : " empty") + (p && p.ai ? " ai" : "") + (p && i === last.me.seat ? " me" : ""));
    if (p) {
      li.appendChild(avatar(i, p.ai));
      const box = el("div");
      const line = el("div", "nm", p.name);
      if (p.ai) line.appendChild(el("span", "tag ai", "AI"));
      if (p.is_host) line.appendChild(el("span", "tag host", "Host"));
      if (i === last.me.seat) line.appendChild(el("span", "tag", "You"));
      box.appendChild(line);
      box.appendChild(el("div", "sub", p.ai ? `Seat ${i + 1} · ${p.agent}` : `Seat ${i + 1}`));
      li.appendChild(box);
    } else {
      li.appendChild(el("span", "avatar", "?"));
      const box = el("div");
      box.appendChild(el("div", "nm", "Empty seat"));
      box.appendChild(el("div", "sub", `Seat ${i + 1}: waiting for a human`));
      li.appendChild(box);
    }
    grid.appendChild(li);
  }
  const missing = humanSeats - humansIn;
  const full = missing === 0;
  $("lobby-wait").textContent = full
    ? (last.me.is_host ? "Everyone is here. Start when you are ready." : "Everyone is here. Waiting for the host to start the game…")
    : `Waiting for ${missing} more ${missing === 1 ? "human" : "humans"}. Share the room code.`;
  const start = $("btn-start");
  start.classList.toggle("hidden", !last.me.is_host);   // the server also enforces host-only start
  start.disabled = !full;
}

// ---------------------------------------------------------------- game
function legal(kind) { return last.legal_actions.some((a) => a.type === kind); }
function legalPassNames() { return last.legal_actions.filter((a) => a.type === "pass").map((a) => a.chit_name); }

function renderGame() {
  // keep keyboard focus on the same control across re-renders
  const fid = document.activeElement && document.activeElement.dataset ? document.activeElement.dataset.fid : null;
  show("game");
  const o = last.observation, r = last.room;

  $("g-round").textContent = `${Math.min(o.completed_rounds + 1, o.num_rounds)} of ${o.num_rounds}`;
  $("g-round-bar").style.width = `${(o.completed_rounds / o.num_rounds) * 100}%`;
  $("g-attempt").textContent = o.attempt > 1 ? `Redeal ${o.attempt - 1} this round` : "";
  const phases = { initial_claims: "Opening claims", passing: "Passing", win_declared: "Reaction race" };
  $("g-phase").textContent = phases[o.phase] || o.phase;
  $("g-active").textContent = o.phase === "win_declared"
    ? (o.pending_reactors.length === 1 ? `${nm(o.pending_reactors[0])} (last to react)` : `${o.pending_reactors.length} players reacting`)
    : (o.decision_seat === last.me.seat ? "You" : nm(o.decision_seat));

  renderPlayers(o, r);
  renderHand(o);
  $("g-prompt").replaceWith(buildPrompt(o));
  renderResult();

  const log = $("g-log");
  log.innerHTML = "";
  logLines.slice(-80).forEach((l) => log.appendChild(el("li", l.kind ? "k-" + l.kind : "", l.text)));
  log.scrollTop = log.scrollHeight;

  timerInfo = last.timer ? { seat: last.timer.seat, deadline: performance.now() + last.timer.seconds_left * 1000, total: r.timeout_seconds } : null;
  tickTimer();
  if (fid) { const again = document.querySelector(`[data-fid="${fid}"]`); if (again && !again.disabled) again.focus(); }
}

function renderPlayers(o, r) {
  const ul = $("g-players");
  ul.innerHTML = "";
  r.players.forEach((p) => {
    const reacting = o.phase === "win_declared";
    const active = reacting ? o.pending_reactors.includes(p.seat) : o.decision_seat === p.seat;
    const li = el("li", "pcard" + (active ? " active" : "") + (p.seat === last.me.seat ? " me" : "") + (p.connected ? "" : " offline"));
    if (active) li.setAttribute("aria-current", "true");
    li.appendChild(avatar(p.seat, p.ai));
    const mid = el("div");
    const name = el("div", "nm", p.name);
    if (p.ai) name.appendChild(el("span", "tag ai", "AI"));
    if (p.seat === last.me.seat) name.appendChild(el("span", "tag", "You"));
    mid.appendChild(name);
    mid.appendChild(el("div", "meta", `Seat ${p.seat + 1} · ${o.hand_sizes[p.seat]} chits${p.connected ? "" : " · offline"}`));
    let state = "";
    if (reacting && o.winner === p.seat) state = "Claimed a win";
    else if (reacting && o.reaction_order.includes(p.seat)) state = `Reacted: place ${o.reaction_order.indexOf(p.seat) + 1}`;
    else if (active) state = p.ai ? "Thinking…" : (reacting ? "Needs to react" : "Deciding");
    mid.appendChild(el("div", "state", state));
    li.appendChild(mid);
    const sc = el("div", "score", String(o.scores[p.seat]));
    sc.appendChild(el("small", "", "points"));
    li.appendChild(sc);
    ul.appendChild(li);
  });
}

function renderHand(o) {
  const passable = legalPassNames();
  if (selected !== null && !(o.my_hand[selected] && passable.includes(o.my_hand[selected]))) selected = null;
  const hand = $("g-hand");
  hand.innerHTML = "";
  o.my_hand.forEach((name, idx) => {
    const st = CHIT_STYLE[name] || FALLBACK_STYLE;
    const b = el("button", "chit" + (idx === selected ? " selected" : ""));
    b.type = "button";
    b.style.setProperty("--c", st.color);
    b.dataset.fid = "chit-" + idx;
    b.disabled = !passable.includes(name);
    b.setAttribute("aria-pressed", idx === selected ? "true" : "false");
    b.setAttribute("aria-label", `${name} chit${idx === selected ? ", selected" : ""}${b.disabled ? ", not available now" : ""}`);
    b.appendChild(symbol(name));
    b.appendChild(el("span", "nm", name));
    b.onclick = () => { selected = selected === idx ? null : idx; renderGame(); };
    hand.appendChild(b);
  });

  const actions = $("g-actions");
  actions.innerHTML = "";
  const add = (label, cls, fid, fn, disabled) => {
    const b = el("button", "btn " + cls, label);
    b.type = "button"; b.dataset.fid = fid; b.disabled = !!disabled; b.onclick = fn; actions.appendChild(b);
  };
  if (legal("claim")) add("Claim", "gold big claim", "act-claim", () => send({ type: "action", action: "claim" }));
  if (legal("react")) add("React!", "gold big react", "act-react", () => send({ type: "action", action: "react" }));
  if (legal("decline")) add("Decline", "outline decline", "act-decline", () => send({ type: "action", action: "decline" }));
  if (passable.length) {
    const name = selected !== null ? o.my_hand[selected] : null;
    const next = nm((o.my_seat + 1) % o.num_players);
    add(name ? `Pass ${name} to ${next}` : "Pass (choose a chit first)", "violet pass", "act-pass", () => {
      if (name === null) return;
      send({ type: "action", action: "pass", chit_name: name }); selected = null;
    }, name === null);
  }
}

function buildPrompt(o) {
  const box = el("div", "prompt");
  box.id = "g-prompt";
  box.setAttribute("role", "status");
  box.setAttribute("aria-live", "polite");
  const ico = el("span", "ico", "✦");
  const body = el("div");
  const big = el("div", "big"), sub = el("div", "sub");
  const next = nm((o.my_seat + 1) % o.num_players);
  if (o.phase === "win_declared") {
    if (legal("react")) { box.classList.add("mine"); big.textContent = `${nm(o.winner)} made a valid claim: react now!`; sub.textContent = "Earlier reactions score more."; }
    else { big.textContent = `${nm(o.winner)} made a valid claim.`; sub.textContent = "Waiting for the other players to react."; }
  } else if (!o.my_turn) {
    big.textContent = isAi(o.decision_seat) ? `${nm(o.decision_seat)} (AI) is thinking…` : `Waiting for ${nm(o.decision_seat)}…`;
    sub.textContent = "You will be notified when it is your turn.";
  } else {
    box.classList.add("mine");
    if (o.decision_kind === "initial_claim") { big.textContent = "Your turn: opening claim"; sub.textContent = "Claim if all four of your chits match, otherwise decline."; }
    else if (o.decision_kind === "initiator_first_pass") { big.textContent = "Your turn: pass a chit"; sub.textContent = `Select a chit, then pass it to ${next}.`; }
    else if (o.decision_kind === "non_initiator_receive") { big.textContent = "Your turn"; sub.textContent = `You now hold five chits. Claim if four match, or pass one chit to ${next}.`; }
    else if (o.decision_kind === "initiator_return") { big.textContent = "Your chit came back"; sub.textContent = `Claim if all four match, or pass one chit to ${next}.`; }
    else big.textContent = "Your turn";
  }
  body.appendChild(big); body.appendChild(sub);
  box.appendChild(ico); box.appendChild(body);
  return box;
}

function tickTimer() {
  const t = $("g-timer"), bar = $("g-timer-bar");
  const tb = bar.parentElement;
  if (!timerInfo) {
    const reacting = last && last.observation && last.observation.phase === "win_declared";
    const aiTurn = last && last.observation && !reacting && isAi(last.observation.decision_seat);
    t.textContent = reacting ? "No time limit until one player is left" : (aiTurn ? `${nm(last.observation.decision_seat)} is thinking…` : "");
    t.classList.remove("low"); tb.classList.remove("low"); bar.style.width = "0";
    return;
  }
  const left = Math.max(0, (timerInfo.deadline - performance.now()) / 1000);
  const who = timerInfo.seat === last.me.seat ? "Your decision" : `${nm(timerInfo.seat)}'s decision`;
  t.textContent = `${who}: ${Math.ceil(left)}s`;
  const low = left <= 5;
  t.classList.toggle("low", low); tb.classList.toggle("low", low);
  bar.style.width = `${Math.min(100, (left / timerInfo.total) * 100)}%`;
}
setInterval(() => { if (last) tickTimer(); }, 250);

// ---------------------------------------------------------------- game over
function renderOver() {
  show("over");
  const tbody = $("o-table").tBodies[0];
  tbody.innerHTML = "";
  last.standings.forEach((row) => {
    const tr = el("tr", row.rank === 1 ? "first" : "");
    [String(row.rank), row.name + (row.ai ? " (AI)" : "") + (row.seat === last.me.seat ? " (you)" : ""), String(row.score)].forEach((c) => tr.appendChild(el("td", "", c)));
    tbody.appendChild(tr);
  });
  const top = last.standings.filter((r) => r.rank === 1).map((r) => r.name);
  $("o-winner").textContent = top.length === 1 ? `${top[0]} wins!` : `Tied for first: ${top.join(", ")}`;
}

fillSettings();
connect();
