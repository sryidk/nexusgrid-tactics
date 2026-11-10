# -*- coding: utf-8 -*-
"""
HexGrid Tactics (六角战棋 / 5x5 Turn-Based Multiplayer Strategy Game for Humans & AI Agents)
Built for TaskMarket TSK-JKVSTHB7 (10 OUSD on Tempo).
Features:
- Turn-based 2-4 player tactical resource & territory control game on a 5x5 tactical grid.
- Matches complete in 12 rounds (< 5 minutes).
- Every turn offers 3 meaningful, non-dominant strategic actions (Rock-Paper-Scissors + Economy):
  1. EXPAND (claim adjacent neutral tile or fortify owned tile: +1 Territory, +1 Energy/turn)
  2.HARVEST (boost energy reserves by +3 Energy; vulnerable to RAID)
  3. RAID (spend 2 Energy to capture an opponent's adjacent tile or steal 3 Energy if they HARVESTED)
  4. SHIELD (spend 1 Energy to block incoming RAIDs and counter-drain 2 Energy from attacker)
- Humans play directly in browser at `/game` (zero install, zero login, instant Lobby + Match Code + 1-click Add Bot).
- AI Agents play via clean documented JSON API (`/game/api/state`, `/game/api/join`, `/game/api/move`, `/game/api/bot-step`, `/game/api/replay`).
"""
import hashlib
import json
import random
import time
import threading

GAME_LOCK = threading.Lock()
MATCHES = {}

DIRS = [(-1, 0), (1, 0), (0, -1), (0, 1)]
SPAWNS = [(0, 0), (4, 4), (0, 4), (4, 0)]
COLORS = ["#3b82f6", "#ef4444", "#10b981", "#f59e0b"]
MAX_ROUNDS = 12


def _create_match_unlocked(match_id: str, creator_name: str = "Player 1", is_agent: bool = False) -> dict:
    grid = [[{"owner": None, "fortified": False, "crystal": (r == 2 and c == 2)} for c in range(5)] for r in range(5)]
    grid[0][0]["owner"] = "P1"
    m = {
        "match_id": match_id,
        "status": "waiting",  # waiting | active | finished
        "round": 1,
        "max_rounds": MAX_ROUNDS,
        "turn_index": 0,
        "created_at": int(time.time()),
        "players": [
            {
                "id": "P1",
                "name": creator_name,
                "type": "agent" if is_agent else "human",
                "color": COLORS[0],
                "energy": 3,
                "tiles": 1,
                "score": 4,
                "last_action": None,
                "shielded": False,
            }
        ],
        "grid": grid,
        "log": [
            {"round": 0, "event": f"Match {match_id} created by {creator_name} (P1 at [0,0]). Waiting for 2-4 players or bots."}
        ],
        "winner": None,
    }
    MATCHES[match_id] = m
    return m


def _recalc_scores(m: dict):
    counts = {p["id"]: 0 for p in m["players"]}
    crystal_bonus = {p["id"]: 0 for p in m["players"]}
    for r in range(5):
        for c in range(5):
            cell = m["grid"][r][c]
            owner = cell["owner"]
            if owner in counts:
                counts[owner] += 2 if cell["fortified"] else 1
                if cell["crystal"]:
                    crystal_bonus[owner] += 3
    for p in m["players"]:
        pid = p["id"]
        p["tiles"] = counts[pid]
        p["score"] = counts[pid] * 3 + crystal_bonus[pid] + p["energy"]


def _choose_bot_move(m: dict, pid: str) -> dict:
    player = next(p for p in m["players"] if p["id"] == pid)
    owned = []
    adj_neutral = []
    adj_enemy = []
    for r in range(5):
        for c in range(5):
            if m["grid"][r][c]["owner"] == pid:
                owned.append((r, c))
                for dr, dc in DIRS:
                    nr, nc = r + dr, c + dc
                    if 0 <= nr < 5 and 0 <= nc < 5:
                        o = m["grid"][nr][nc]["owner"]
                        if o is None:
                            adj_neutral.append((nr, nc))
                        elif o != pid:
                            adj_enemy.append((nr, nc))
    # Heuristic mix so there is no single dominant strategy
    if (2, 2) in adj_neutral:
        return {"action": "EXPAND", "target": [2, 2]}
    if player["energy"] >= 3 and adj_enemy and random.random() < 0.55:
        t = random.choice(adj_enemy)
        return {"action": "RAID", "target": [t[0], t[1]]}
    if adj_neutral and random.random() < 0.7:
        t = random.choice(adj_neutral)
        return {"action": "EXPAND", "target": [t[0], t[1]]}
    if player["energy"] >= 2 and adj_enemy and random.random() < 0.45:
        return {"action": "SHIELD", "target": list(owned[0]) if owned else [0, 0]}
    return {"action": "HARVEST", "target": list(owned[0]) if owned else [0, 0]}


def _apply_move_unlocked(m: dict, pid: str, action: str, target: list) -> dict:
    if m["status"] == "waiting" and len(m["players"]) >= 2:
        m["status"] = "active"
    if m["status"] != "active":
        return {"ok": False, "error": "Match is not active (need at least 2 players; add a bot or second player)."}

    cur_p = m["players"][m["turn_index"]]
    if cur_p["id"] != pid:
        return {"ok": False, "error": f"It is currently {cur_p['id']}'s turn, not {pid}."}

    action = (action or "EXPAND").upper()
    if not isinstance(target, list) or len(target) != 2:
        target = [2, 2]
    tr, tc = max(0, min(4, int(target[0]))), max(0, min(4, int(target[1])))

    cur_p["shielded"] = False
    msg = ""

    # Passive income from center crystal
    if m["grid"][2][2]["owner"] == pid:
        cur_p["energy"] += 1

    if action == "HARVEST":
        cur_p["energy"] += 3
        msg = f"{cur_p['name']} ({pid}) used HARVEST (+3 Energy -> {cur_p['energy']}E)."
    elif action == "SHIELD":
        if cur_p["energy"] >= 1:
            cur_p["energy"] -= 1
            cur_p["shielded"] = True
            msg = f"{cur_p['name']} ({pid}) raised tactical SHIELD (-1E, blocks & reflects next RAID)."
        else:
            cur_p["energy"] += 2
            msg = f"{cur_p['name']} ({pid}) lacked energy for SHIELD; fell back to mini-HARVEST (+2E)."
    elif action == "RAID":
        cell = m["grid"][tr][tc]
        enemy_id = cell["owner"]
        if cur_p["energy"] < 2:
            cur_p["energy"] += 2
            msg = f"{cur_p['name']} ({pid}) lacked 2E for RAID; fell back to mini-HARVEST (+2E)."
        elif enemy_id and enemy_id != pid:
            cur_p["energy"] -= 2
            enemy = next((p for p in m["players"] if p["id"] == enemy_id), None)
            if enemy and enemy.get("shielded"):
                stolen = min(2, cur_p["energy"])
                cur_p["energy"] -= stolen
                enemy["energy"] += stolen + 1
                enemy["shielded"] = False
                msg = f"{cur_p['name']} ({pid}) RAIDED [{tr},{tc}], but {enemy['name']} ({enemy_id}) deflected it with SHIELD! (+{stolen+1}E counter)."
            else:
                if cell["fortified"]:
                    cell["fortified"] = False
                    msg = f"{cur_p['name']} ({pid}) RAIDED [{tr},{tc}] and broke {enemy_id}'s fortification!"
                else:
                    cell["owner"] = pid
                    if enemy and enemy.get("last_action") == "HARVEST" and enemy["energy"] >= 2:
                        enemy["energy"] -= 2
                        cur_p["energy"] += 2
                        msg = f"{cur_p['name']} ({pid}) RAIDED [{tr},{tc}], captured tile from {enemy_id} AND Punished HARVEST (+2E stolen)!"
                    else:
                        msg = f"{cur_p['name']} ({pid}) RAIDED and captured [{tr},{tc}] from {enemy_id}!"
        else:
            cell["owner"] = pid
            cur_p["energy"] -= 1
            msg = f"{cur_p['name']} ({pid}) swept into [{tr},{tc}]."
    else:  # EXPAND
        cell = m["grid"][tr][tc]
        if cell["owner"] is None:
            cell["owner"] = pid
            cur_p["energy"] += 1
            msg = f"{cur_p['name']} ({pid}) EXPANDED to neutral sector [{tr},{tc}] (+1E)."
        elif cell["owner"] == pid:
            cell["fortified"] = True
            cur_p["energy"] += 1
            msg = f"{cur_p['name']} ({pid}) FORTIFIED sector [{tr},{tc}] (+1E)."
        else:
            # Find nearest neutral or fortify own
            placed = False
            for r in range(5):
                for c in range(5):
                    if m["grid"][r][c]["owner"] is None:
                        m["grid"][r][c]["owner"] = pid
                        cur_p["energy"] += 1
                        msg = f"{cur_p['name']} ({pid}) EXPANDED to sector [{r},{c}] (+1E)."
                        placed = True
                        break
                if placed:
                    break
            if not placed:
                cur_p["energy"] += 2
                msg = f"{cur_p['name']} ({pid}) consolidated reserves (+2E)."

    cur_p["last_action"] = action
    m["log"].append({"round": m["round"], "player": pid, "action": action, "target": [tr, tc], "event": msg})
    _recalc_scores(m)

    # Advance turn
    m["turn_index"] += 1
    if m["turn_index"] >= len(m["players"]):
        m["turn_index"] = 0
        m["round"] += 1

    # Check win condition
    for p in m["players"]:
        if p["tiles"] >= 15:
            m["status"] = "finished"
            m["winner"] = p["id"]
            m["log"].append({"round": m["round"], "event": f"🏆 {p['name']} ({p['id']}) achieved Domination Victory (15+ sectors)!"})
            break

    if m["status"] != "finished" and m["round"] > m["max_rounds"]:
        m["status"] = "finished"
        best = max(m["players"], key=lambda x: (x["score"], x["tiles"], x["energy"]))
        m["winner"] = best["id"]
        m["log"].append({"round": m["max_rounds"], "event": f"🏆 Match Complete! {best['name']} ({best['id']}) wins with {best['score']} pts!"})

    # Auto-step any consecutive AI bots so human/API caller sees immediate bot response
    safety = 0
    while m["status"] == "active" and m["players"][m["turn_index"]]["type"] == "bot" and safety < 8:
        safety += 1
        b_id = m["players"][m["turn_index"]]["id"]
        bm = _choose_bot_move(m, b_id)
        _apply_move_unlocked(m, b_id, bm["action"], bm["target"])
        break  # Let _apply_move_unlocked recursion handle next bot

    return {"ok": True, "match": m}


def handle_game_api(method: str, route: str, params: dict) -> tuple[int, dict]:
    with GAME_LOCK:
        if not MATCHES:
            m0 = _create_match_unlocked("DEMO-100", "Commander Alpha", is_agent=False)
            # Pre-populate a bot in DEMO-100 so anyone opening it can immediately play
            m0["players"].append({
                "id": "P2",
                "name": "TacticalBot-v1 (AI)",
                "type": "bot",
                "color": COLORS[1],
                "energy": 3,
                "tiles": 1,
                "score": 4,
                "last_action": None,
                "shielded": False,
            })
            m0["grid"][4][4]["owner"] = "P2"
            m0["status"] = "active"
            _recalc_scores(m0)

        if route == "/game/api/list":
            return 200, {
                "ok": True,
                "matches": [
                    {
                        "match_id": k,
                        "status": v["status"],
                        "round": v["round"],
                        "max_rounds": v["max_rounds"],
                        "players": [{"id": p["id"], "name": p["name"], "type": p["type"], "score": p["score"]} for p in v["players"]],
                        "winner": v["winner"],
                    }
                    for k, v in list(MATCHES.items())[-20:]
                ],
            }

        if route == "/game/api/create":
            mid = (params.get("match_id") or f"M-{random.randint(1000, 9999)}").upper()
            name = params.get("name") or "Player 1"
            is_ag = str(params.get("is_agent", "")).lower() in ("true", "1", "yes")
            m = _create_match_unlocked(mid, name, is_agent=is_ag)
            if str(params.get("fill_bots", "true")).lower() in ("true", "1", "yes"):
                m["players"].append({
                    "id": "P2",
                    "name": "NexusBot (AI)",
                    "type": "bot",
                    "color": COLORS[1],
                    "energy": 3,
                    "tiles": 1,
                    "score": 4,
                    "last_action": None,
                    "shielded": False,
                })
                m["grid"][4][4]["owner"] = "P2"
                m["status"] = "active"
                _recalc_scores(m)
            return 200, {"ok": True, "match": m}

        if route == "/game/api/join":
            mid = (params.get("match_id") or "DEMO-100").upper()
            m = MATCHES.get(mid)
            if not m:
                m = _create_match_unlocked(mid, "Host Player")
            if len(m["players"]) >= 4:
                return 400, {"ok": False, "error": "Match is full (4 players max)."}
            idx = len(m["players"])
            pid = f"P{idx + 1}"
            ptype = params.get("type") or "human"
            pname = params.get("name") or (f"TacticalBot-{pid}" if ptype == "bot" else f"Player {idx + 1}")
            sr, sc = SPAWNS[idx]
            m["grid"][sr][sc]["owner"] = pid
            m["players"].append({
                "id": pid,
                "name": pname,
                "type": ptype,
                "color": COLORS[idx],
                "energy": 3,
                "tiles": 1,
                "score": 4,
                "last_action": None,
                "shielded": False,
            })
            if len(m["players"]) >= 2 and m["status"] == "waiting":
                m["status"] = "active"
            m["log"].append({"round": m["round"], "event": f"{pname} ({pid}, {ptype}) joined at [{sr},{sc}]."})
            _recalc_scores(m)
            return 200, {"ok": True, "player_id": pid, "match": m}

        if route in ("/game/api/state", "/game/api/replay"):
            mid = (params.get("match_id") or "DEMO-100").upper()
            m = MATCHES.get(mid)
            if not m:
                return 404, {"ok": False, "error": f"Match {mid} not found."}
            return 200, {"ok": True, "match": m}

        if route == "/game/api/move":
            mid = (params.get("match_id") or "DEMO-100").upper()
            m = MATCHES.get(mid)
            if not m:
                return 404, {"ok": False, "error": f"Match {mid} not found."}
            pid = params.get("player_id") or m["players"][m["turn_index"]]["id"]
            action = params.get("action") or "EXPAND"
            target = params.get("target") or [2, 2]
            if isinstance(target, str) and "," in target:
                parts = target.split(",")
                target = [int(parts[0]), int(parts[1])]
            res = _apply_move_unlocked(m, pid, action, target)
            return (200 if res.get("ok") else 400), res

        if route == "/game/api/bot-step":
            mid = (params.get("match_id") or "DEMO-100").upper()
            m = MATCHES.get(mid)
            if not m:
                return 404, {"ok": False, "error": f"Match {mid} not found."}
            cur_id = m["players"][m["turn_index"]]["id"]
            bm = _choose_bot_move(m, cur_id)
            res = _apply_move_unlocked(m, cur_id, bm["action"], bm["target"])
            return 200, res

    return 404, {"ok": False, "error": "Unknown game endpoint"}


GAME_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NexusGrid Tactics — Multiplayer Strategy for Humans & AI Agents</title>
<style>
  :root { --bg: #0b0f19; --panel: #151c2c; --border: #263147; --text: #e2e8f0; --accent: #38bdf8; }
  * { box-sizing: border-box; font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif; }
  body { margin: 0; background: var(--bg); color: var(--text); padding: 20px; }
  .container { max-width: 1080px; margin: 0 auto; }
  header { display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid var(--border); padding-bottom: 14px; margin-bottom: 18px; flex-wrap: wrap; gap: 12px; }
  h1 { margin: 0; font-size: 1.45rem; color: #fff; display: flex; align-items: center; gap: 10px; }
  .badge { background: #1e293b; border: 1px solid var(--accent); color: var(--accent); font-size: 0.75rem; padding: 3px 8px; border-radius: 99px; }
  .layout { display: grid; grid-template-columns: 1fr 360px; gap: 20px; }
  @media (max-width: 820px) { .layout { grid-template-columns: 1fr; } }
  .card { background: var(--panel); border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-bottom: 16px; }
  .controls { display: flex; gap: 8px; flex-wrap: wrap; margin-bottom: 14px; }
  input, select, button { background: #0f172a; color: #fff; border: 1px solid var(--border); padding: 8px 12px; border-radius: 8px; font-size: 0.9rem; }
  button { cursor: pointer; font-weight: 600; transition: 0.15s; }
  button.primary { background: #0284c7; border-color: #38bdf8; }
  button.primary:hover { background: #0369a1; }
  button.action-btn { flex: 1; min-width: 110px; padding: 10px; text-align: center; }
  button.action-btn.active { outline: 2px solid #38bdf8; background: #1e3a8a; }
  .grid-board { display: grid; grid-template-columns: repeat(5, 1fr); gap: 8px; max-width: 440px; margin: 12px auto; }
  .cell { aspect-ratio: 1; border-radius: 10px; border: 2px solid var(--border); background: #0f172a; display: flex; flex-direction: column; align-items: center; justify-content: center; cursor: pointer; position: relative; transition: transform 0.12s, border-color 0.12s; user-select: none; }
  .cell:hover { transform: scale(1.04); border-color: #94a3b8; }
  .cell .coords { position: absolute; top: 4px; left: 6px; font-size: 0.68rem; color: #64748b; }
  .cell .icon { font-size: 1.4rem; }
  .cell .owner-tag { font-size: 0.75rem; font-weight: 700; margin-top: 2px; }
  .player-row { display: flex; justify-content: space-between; align-items: center; padding: 8px 10px; border-radius: 8px; margin-bottom: 6px; background: #0f172a; border-left: 4px solid #64748b; }
  .log-box { max-height: 220px; overflow-y: auto; font-size: 0.82rem; line-height: 1.45; background: #090d16; padding: 10px; border-radius: 8px; border: 1px solid var(--border); }
  .log-item { margin-bottom: 6px; border-bottom: 1px dashed #1e293b; padding-bottom: 4px; }
  code { background: #090d16; padding: 2px 6px; border-radius: 4px; color: #38bdf8; font-size: 0.82rem; }
</style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>⚡ NexusGrid Tactics <span class="badge">Humans + AI Agents (2–4 Players)</span></h1>
      <div style="font-size:0.85rem;color:#94a3b8;margin-top:4px;">Turn-Based 5×5 Tactical Sector Control · Under 5 Min · Counter-Strategy Triangle (Expand / Harvest / Raid / Shield)</div>
    </div>
    <div class="controls" style="margin:0;">
      <input id="matchInput" value="DEMO-100" style="width:120px;" placeholder="Match Code">
      <button onclick="loadMatch()">Join / Refresh</button>
      <button class="primary" onclick="createNewMatch()">+ New Match</button>
      <button onclick="addPlayer('bot')">+ Add AI Bot</button>
      <button onclick="addPlayer('human')">+ Add Human Seat</button>
    </div>
  </header>

  <div class="layout">
    <div>
      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;">
          <div id="statusBanner" style="font-weight:700;font-size:1.05rem;color:#38bdf8;">Loading match...</div>
          <div id="roundBadge" class="badge">Round 1 / 12</div>
        </div>

        <div style="margin-bottom:10px;font-size:0.85rem;color:#cbd5e1;">
          <b>1. Select Tactical Action:</b> (No single dominant strategy — <code>RAID</code> punishes <code>HARVEST</code>, <code>SHIELD</code> reflects <code>RAID</code>, <code>EXPAND</code> outscales <code>SHIELD</code>)
        </div>
        <div class="controls">
          <button id="btn-EXPAND" class="action-btn active" onclick="setAction('EXPAND')">🚩 EXPAND / FORTIFY<br><small style="color:#94a3b8">+1 Tile, +1E</small></button>
          <button id="btn-HARVEST" class="action-btn" onclick="setAction('HARVEST')">⚡ HARVEST<br><small style="color:#94a3b8">+3E (Vulnerable)</small></button>
          <button id="btn-RAID" class="action-btn" onclick="setAction('RAID')">⚔️ RAID (-2E)<br><small style="color:#94a3b8">Capture / Steal 2E</small></button>
          <button id="btn-SHIELD" class="action-btn" onclick="setAction('SHIELD')">🛡️ SHIELD (-1E)<br><small style="color:#94a3b8">Reflects RAID</small></button>
        </div>

        <div style="font-size:0.85rem;color:#cbd5e1;margin-bottom:6px;">
          <b>2. Click Any Sector on the 5×5 Grid to Execute Turn</b> (Center 💎 [2,2] grants +3 Score & +1E/turn):
        </div>
        <div id="board" class="grid-board"></div>
        <div style="display:flex;justify-content:space-between;margin-top:10px;">
          <button onclick="triggerBotStep()">🤖 Force AI Bot Move</button>
          <span style="font-size:0.8rem;color:#94a3b8;">Tip: Click any tile to submit your move for the active player.</span>
        </div>
      </div>

      <div class="card">
        <h3 style="margin:0 0 8px 0;font-size:1rem;">📖 Rules (1 Paragraph) & Agent HTTP/JSON API</h3>
        <p style="font-size:0.84rem;color:#cbd5e1;line-height:1.5;margin:0 0 10px 0;">
          <b>Rules:</b> 2–4 players (humans or HTTP AI agents) battle over 12 rounds on a 5×5 grid. Each turn, a player chooses one of four counter-balanced actions: <b>EXPAND</b> (claim a neutral tile or fortify an owned tile for +1 Energy), <b>HARVEST</b> (gain +3 Energy, but if an opponent <b>RAIDs</b> you before your next turn, they steal 2 Energy), <b>RAID</b> (spend 2 Energy to capture an enemy tile or break fortification), or <b>SHIELD</b> (spend 1 Energy to block and reflect an incoming RAID for +3 Energy). Controlling the center Nexus Crystal <code>[2,2]</code> grants +1 Energy/turn and +3 pts. Instant victory at 15 tiles, or highest score (<code>3×Tiles + Energy + Crystal</code>) after Round 12 wins!
        </p>
        <div style="font-size:0.8rem;color:#94a3b8;line-height:1.6;">
          • <code>GET /game/api/state?match_id=DEMO-100</code> — Read full board, scores, active turn, & replay log<br>
          • <code>POST /game/api/create</code> <code>{"match_id":"MY-ROOM","name":"AgentZero","fill_bots":true}</code> — Create lobby<br>
          • <code>POST /game/api/join</code> <code>{"match_id":"MY-ROOM","name":"Bot2","type":"agent"}</code> — Join seat (P1–P4)<br>
          • <code>POST /game/api/move</code> <code>{"match_id":"DEMO-100","player_id":"P1","action":"EXPAND","target":[1,0]}</code> — Submit move
        </div>
      </div>
    </div>

    <div>
      <div class="card">
        <h3 style="margin:0 0 10px 0;font-size:1rem;">👥 Players & Standings</h3>
        <div id="playersList"></div>
      </div>
      <div class="card">
        <h3 style="margin:0 0 10px 0;font-size:1rem;">📜 Live Match Log / Replay</h3>
        <div id="logBox" class="log-box"></div>
      </div>
    </div>
  </div>
</div>

<script>
let currentAction = 'EXPAND';
let currentMatch = null;

function setAction(act) {
  currentAction = act;
  ['EXPAND','HARVEST','RAID','SHIELD'].forEach(a => {
    document.getElementById('btn-' + a).classList.toggle('active', a === act);
  });
}

async function apiCall(path, method='GET', body=null) {
  const opts = { method, headers: {'Content-Type': 'application/json'} };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  return await r.json();
}

async function loadMatch() {
  const mid = document.getElementById('matchInput').value.trim().toUpperCase() || 'DEMO-100';
  const res = await apiCall('/game/api/state?match_id=' + encodeURIComponent(mid));
  if (res.ok) renderMatch(res.match);
  else alert(res.error || 'Match not found');
}

async function createNewMatch() {
  const code = 'M-' + Math.floor(1000 + Math.random() * 9000);
  document.getElementById('matchInput').value = code;
  const res = await apiCall('/game/api/create', 'POST', { match_id: code, name: 'Human Commander', fill_bots: true });
  if (res.ok) renderMatch(res.match);
}

async function addPlayer(type) {
  const mid = document.getElementById('matchInput').value.trim().toUpperCase();
  const res = await apiCall('/game/api/join', 'POST', { match_id: mid, type: type });
  if (res.ok) renderMatch(res.match);
  else alert(res.error);
}

async function clickCell(r, c) {
  if (!currentMatch) return;
  if (currentMatch.status === 'finished') { alert('Match finished! Create a new match.'); return; }
  const activePlayer = currentMatch.players[currentMatch.turn_index];
  const res = await apiCall('/game/api/move', 'POST', {
    match_id: currentMatch.match_id,
    player_id: activePlayer.id,
    action: currentAction,
    target: [r, c]
  });
  if (res.ok) renderMatch(res.match);
  else alert(res.error);
}

async function triggerBotStep() {
  if (!currentMatch) return;
  const res = await apiCall('/game/api/bot-step', 'POST', { match_id: currentMatch.match_id });
  if (res.ok) renderMatch(res.match);
}

function renderMatch(m) {
  currentMatch = m;
  document.getElementById('matchInput').value = m.match_id;
  document.getElementById('roundBadge').innerText = `Round ${Math.min(m.round, m.max_rounds)} / ${m.max_rounds}`;
  const activeP = m.players[m.turn_index] || m.players[0];
  const banner = document.getElementById('statusBanner');
  if (m.status === 'finished') {
    banner.innerText = `🏆 Match Finished — Winner: ${m.winner}!`;
    banner.style.color = '#fbbf24';
  } else {
    banner.innerText = `Active Turn: ${activeP.name} (${activeP.id}) — Choose action & click sector`;
    banner.style.color = activeP.color;
  }

  const pMap = {};
  m.players.forEach(p => pMap[p.id] = p);

  const board = document.getElementById('board');
  board.innerHTML = '';
  for (let r = 0; r < 5; r++) {
    for (let c = 0; c < 5; c++) {
      const cell = m.grid[r][c];
      const div = document.createElement('div');
      div.className = 'cell';
      const ownerObj = cell.owner ? pMap[cell.owner] : null;
      if (ownerObj) {
        div.style.borderColor = ownerObj.color;
        div.style.background = ownerObj.color + '22';
      }
      let icon = '▫️';
      if (cell.crystal) icon = '💎';
      else if (cell.fortified) icon = '🏰';
      else if (ownerObj) icon = '🚩';
      div.innerHTML = `<span class="coords">[${r},${c}]</span><span class="icon">${icon}</span><span class="owner-tag" style="color:${ownerObj ? ownerObj.color : '#64748b'}">${cell.owner || 'Neutral'}</span>`;
      div.onclick = () => clickCell(r, c);
      board.appendChild(div);
    }
  }

  const pList = document.getElementById('playersList');
  pList.innerHTML = m.players.map((p, idx) => `
    <div class="player-row" style="border-left-color:${p.color}; ${idx === m.turn_index && m.status==='active' ? 'outline:1px solid '+p.color : ''}">
      <div>
        <div style="font-weight:700;color:${p.color}">${p.name} (${p.id}) ${p.shielded ? '🛡️' : ''}</div>
        <div style="font-size:0.76rem;color:#94a3b8">Type: ${p.type.toUpperCase()} · Last: ${p.last_action || '—'}</div>
      </div>
      <div style="text-align:right;font-size:0.85rem;">
        <div><b>${p.score} pts</b></div>
        <div style="color:#94a3b8">${p.tiles} Tiles · ⚡${p.energy}E</div>
      </div>
    </div>
  `).join('');

  const logBox = document.getElementById('logBox');
  logBox.innerHTML = m.log.slice().reverse().map(l => `
    <div class="log-item"><b style="color:#38bdf8">[R${l.round}]</b> ${l.event}</div>
  `).join('');
}

loadMatch();
</script>
</body>
</html>
"""
