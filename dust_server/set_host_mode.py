"""Switches the listen-server host to another game mode: rewrites the map start in dev_commands.json, bumps the
revision (a running host restarts the map on its next poll) and sets the fake battle's mode for the battle finder.

    python set_host_mode.py skirmish
    python set_host_mode.py ambush     # same mode again: restarts the map, e.g. after the match timer ran out

A running host crashes when it switches to a different mode in place (null object in the function at 0x8cb534,
some seconds after the new map loaded), so for another mode restart the host (tools/restart_all.ps1).

Modes come from CATMA (GalaxyLevel gameModes lists, e.g. 365271 = level_craters_bg_1; DustGameType ids).
"""
import argparse
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
MODES = {
    # name: (DustGameType id, gametype, gameModeLevel, map, bfid, terraform, mode name in the battle finder)
    "ambush": (353889, "gamemode_ambush_32p", "MN_Craters01_BG01_AmbA", "MN_Craters01", 365271, "Desert01", "Ambush"),
    "ambush_oms": (364136, "gamemode_ambush_oms_32p", "MN_Craters01_BG01_OmsA", "MN_Craters01", 365271, "Desert01",
                   "Ambush OMS"),
    "domination": (365195, "gamemode_domination_32p", "MN_Craters01_BG01_DomB", "MN_Craters01", 365271, "Desert01",
                   "Domination"),
    "skirmish": (365340, "gamemode_skirmish_4obj_32p", "MN_Craters01_BG01_SkB", "MN_Craters01", 365271, "Desert01",
                 "Skirmish"),
    # Acquisition: DustDominationGame, sites expire after 300 s (mSiteExpiration); only on Highland and Mountains.
    "acquisition": (366776, "gamemode_domination_2", "MN_Highland01_BG01_Dom20A", "MN_Highland01", 365818, "Desert01",
                    "Acquisition"),
}


def start_command(mode, credential):
    mode_id, gametype, level, map_name, bfid, terraform, _ = MODES[mode]
    return (f"Start {map_name}?gametype={gametype}?gameModeLevel={level}?bfid={bfid}?loadDefaultOutpost"
            f"?Terraform={terraform}?LightingMode=MOOD_DAY?listen?MaxPlayers=32?battleID=514001?credential={credential}"
            f"?Team=0?Name=DustPlayer?PlayerControllerClass=DustGame.DustDevPlayerController")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=sorted(MODES))
    args = parser.parse_args()

    path = HERE / "dev_commands.json"
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    host = next(c["arg"] for c in data["commands"] if c["action"] == "battle_member")
    for command in data["commands"]:
        if command["action"] == "ue3" and command["arg"].startswith("Start "):
            command["arg"] = start_command(args.mode, host["credential"])
    data["revision"] += 1
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    battle_path = HERE / "fake_battle.json"
    battle = json.loads(battle_path.read_text(encoding="utf-8"))
    battle["mode_id"], battle["mode_name"] = MODES[args.mode][0], MODES[args.mode][6]
    battle_path.write_text(json.dumps(battle, indent=2) + "\n", encoding="utf-8")
    print(f"revision {data['revision']}: {args.mode}")


if __name__ == "__main__":
    main()
