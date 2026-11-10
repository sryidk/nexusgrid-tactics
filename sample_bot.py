"""
NexusGrid Tactics — Sample Autonomous AI Agent Bot
Plays a complete match against any human or bot on a live NexusGrid server via the HTTP/JSON API.
Usage:
    python sample_bot.py --server https://scavenger-labs-api.serveousercontent.com --match DEMO-100
"""
import argparse
import json
import time
import urllib.request


def api_call(base_url: str, path: str, method: str = "GET", payload: dict = None) -> dict:
    url = base_url.rstrip("/") + path
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json", "User-Agent": "NexusGridBot/1.0"}, method=method)
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode("utf-8"))


def choose_smart_move(match: dict, my_id: str) -> tuple[str, list]:
    players = {p["id"]: p for p in match["players"]}
    me = players[my_id]
    grid = match["grid"]

    # 1. If center Nexus Crystal [2,2] is neutral, seize it immediately
    if grid[2][2]["owner"] is None:
        return "EXPAND", [2, 2]

    # 2. If any opponent just HARVESTED and we have >= 2 Energy, RAID their tile to steal +2E and capture it
    if me["energy"] >= 2:
        for p in match["players"]:
            if p["id"] != my_id and p.get("last_action") == "HARVEST" and not p.get("shielded"):
                for r in range(5):
                    for c in range(5):
                        if grid[r][c]["owner"] == p["id"]:
                            return "RAID", [r, c]

    # 3. Expand to any neutral tile adjacent to our territory
    for r in range(5):
        for c in range(5):
            if grid[r][c]["owner"] is None:
                return "EXPAND", [r, c]

    # 4. Otherwise harvest energy or raid an unshielded opponent
    if me["energy"] >= 2:
        for r in range(5):
            for c in range(5):
                if grid[r][c]["owner"] not in (None, my_id):
                    return "RAID", [r, c]
    return "HARVEST", [0, 0]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--server", default="https://scavenger-labs-api.serveousercontent.com")
    parser.add_argument("--match", default="BOT-TEST-01")
    parser.add_argument("--name", default="SamplePythonAgent")
    args = parser.parse_args()

    print(f"[*] Creating/joining match {args.match} on {args.server}...")
    state_res = api_call(args.server, "/game/api/create", "POST", {"match_id": args.match, "name": args.name, "is_agent": True, "fill_bots": True})
    match = state_res["match"]
    my_id = "P1"

    while match["status"] == "active":
        active_p = match["players"][match["turn_index"]]
        if active_p["id"] == my_id:
            action, target = choose_smart_move(match, my_id)
            print(f"[R{match['round']}] Submitting {action} -> {target}")
            res = api_call(args.server, "/game/api/move", "POST", {
                "match_id": args.match,
                "player_id": my_id,
                "action": action,
                "target": target,
            })
            match = res["match"]
        else:
            res = api_call(args.server, "/game/api/bot-step", "POST", {"match_id": args.match})
            match = res["match"]
        time.sleep(0.1)

    print(f"[+] Match finished! Winner: {match['winner']}")
    for p in match["players"]:
        print(f"    {p['id']} ({p['name']}): {p['score']} pts ({p['tiles']} tiles, {p['energy']}E)")


if __name__ == "__main__":
    main()
