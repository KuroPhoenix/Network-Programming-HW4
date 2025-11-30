import json
from pathlib import Path
from typing import List, Dict, Any


class LocalGameManager:
    """
    Utility to scan local developer games and read their manifests.
    Looks for manifest.json under developer/games/<game_name>/.
    """

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path(__file__).resolve().parent / "games"

    def list_games(self) -> List[Path]:
        """
        Return a list of game directories under base_dir that contain manifest.json.
        """
        if not self.base_dir.exists():
            return []
        return [p for p in self.base_dir.iterdir() if p.is_dir() and (p / "manifest.json").exists()]

    def load_manifest(self, game_dir: Path) -> Dict[str, Any]:
        """
        Read manifest.json from the given game directory.
        """
        manifest_path = game_dir / "manifest.json"
        with manifest_path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def list_manifests(self) -> List[Dict[str, Any]]:
        """
        Return a list of minimal manifest info for all local games.
        Only includes fields aligned with games.db: author (unknown locally), game_name, version, type.
        """
        manifests = []
        for game_dir in self.list_games():
            try:
                manifest = self.load_manifest(game_dir)
                entry = {
                    "game_name": manifest.get("game_name"),
                    "version": manifest.get("version"),
                    "type": manifest.get("type"),
                    "description": manifest.get("description"),
                    "uploaded": manifest.get("uploaded"),
                    "_path": str(game_dir),
                }
                manifests.append(entry)
            except Exception:
                continue
        return manifests

    def create_manifest(
        self,
        game_name: str,
        version: str,
        game_type: str,
        description: str = "",
        max_players: int = 2,
    ) -> Path:
        """
        Create a new game folder with a manifest.json populated from inputs.
        Uses a simple default template; callers can adjust commands afterward.
        """
        game_dir = self.base_dir / game_name
        game_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "game_name": game_name,
            "version": version,
            "description": description,
            "type": game_type,
            "max_players": max_players,
            "lobby_requires_download": True,
            "uploaded": False,
            "server": {
                "command": "python server/main.py --port {port} --room {room_id}",
                "working_dir": "server",
                "env": {
                    "ROOM_ID": "{room_id}",
                    "PORT": "{port}"
                }
            },
            "client": {
                "command": "python client/main.py --host {host} --port {port} --player {player_name}",
                "working_dir": "client",
                "env": {
                    "PLAYER_NAME": "{player_name}"
                }
            },
            "assets": [
                "assets/*"
            ],
            "healthcheck": {
                "tcp_port": "{port}",
                "timeout_sec": 5
            }
        }
        manifest_path = game_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest_path

    def upload_game(self, game_name: str) -> bool:
        path = self.base_dir / game_name / "manifest.json"
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        data["uploaded"] = True
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True
