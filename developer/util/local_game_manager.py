import json
import shutil
from pathlib import Path
from typing import List, Dict, Any


class LocalGameManager:
    """
    Utility to scan local developer games and read their manifests.
    Looks for manifest.json under developer/games/<game_name>/.
    """

    def __init__(self, base_dir: Path | None = None):
        self.base_dir = base_dir or Path(__file__).resolve().parent.parent / "games"

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
        Only includes fields aligned with games.db: author, game_name, version, type.
        """
        manifests = []
        for game_dir in self.list_games():
            try:
                manifest = self.load_manifest(game_dir)
                author = manifest.get("author") or "Unknown"
                entry = {
                    "game_name": manifest.get("game_name"),
                    "version": manifest.get("version"),
                    "type": manifest.get("type"),
                    "description": manifest.get("description"),
                    "uploaded": manifest.get("uploaded"),
                    "_path": str(game_dir),
                    "author": author,
                }
                manifests.append(entry)
            except Exception:
                continue
        manifests.sort(key=lambda m: ((m.get("author") or "").lower(), (m.get("game_name") or "").lower()))
        return manifests

    def create_manifest(
        self,
        game_name: str,
        version: str,
        game_type: str,
        description: str = "",
        max_players: int = 2,
        author: str = "Unknown",
    ) -> Path:
        """
        Backwards-compatible wrapper around create_or_update_manifest.
        """
        path, _ = self.create_or_update_manifest(
            game_name=game_name,
            version=version,
            game_type=game_type,
            description=description,
            max_players=max_players,
            author=author,
        )
        return path

    def create_or_update_manifest(
        self,
        game_name: str,
        version: str,
        game_type: str,
        description: str = "",
        max_players: int = 2,
        author: str = "Unknown",
    ) -> tuple[Path, bool]:
        """
        Create or update a game manifest. If the game already exists, the manifest
        is updated in-place (keeping server/client commands and assets). Returns
        (manifest_path, created_flag).
        """
        game_dir = self.base_dir / game_name
        manifest_path = game_dir / "manifest.json"
        created = not manifest_path.exists()
        if created:
            game_dir.mkdir(parents=True, exist_ok=True)
            manifest: Dict[str, Any] = self._default_manifest(
                game_name=game_name,
                version=version,
                game_type=game_type,
                description=description,
                max_players=max_players,
                author=author,
            )
        else:
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                manifest = {}
            # Preserve existing server/client/assets if present; otherwise seed defaults.
            if "server" not in manifest or "client" not in manifest:
                defaults = self._default_manifest(
                    game_name=game_name,
                    version=version,
                    game_type=game_type,
                    description=description,
                    max_players=max_players,
                    author=author,
                )
                manifest.setdefault("server", defaults["server"])
                manifest.setdefault("client", defaults["client"])
                manifest.setdefault("assets", defaults["assets"])
                manifest.setdefault("healthcheck", defaults["healthcheck"])

        manifest["game_name"] = game_name
        manifest["author"] = author
        manifest["version"] = version
        manifest["description"] = description
        manifest["type"] = game_type
        manifest["max_players"] = max_players
        manifest["lobby_requires_download"] = manifest.get("lobby_requires_download", True)
        manifest["uploaded"] = False  # local edit implies needs upload

        manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
        return manifest_path, created

    def _default_manifest(
        self,
        game_name: str,
        version: str,
        game_type: str,
        description: str,
        max_players: int,
        author: str,
    ) -> Dict[str, Any]:
        return {
            "game_name": game_name,
            "author": author,
            "version": version,
            "description": description,
            "type": game_type,
            "max_players": max_players,
            "lobby_requires_download": True,
            "uploaded": False,
            "server": {
                "command": "python server/main.py --port {port} --room {room_id}",
                "working_dir": "server",
                "env": {"ROOM_ID": "{room_id}", "PORT": "{port}"},
            },
            "client": {
                "command": "python client/main.py --host {host} --port {port} --player {player_name}",
                "working_dir": "client",
                "env": {"PLAYER_NAME": "{player_name}"},
            },
            "assets": ["assets/*"],
            "healthcheck": {"tcp_port": "{port}", "timeout_sec": 5},
        }

    def upload_game(self, game_name: str) -> bool:
        path = self.base_dir / game_name / "manifest.json"
        if not path.exists():
            return False
        data = json.loads(path.read_text(encoding="utf-8"))
        data["uploaded"] = True
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True

    def delete_game(self, game_name: str) -> bool:
        """
        Delete a local game folder. Returns True if removed, False if not found.
        """
        if not game_name:
            raise ValueError("Game name required to delete local game.")
        target = self.base_dir / game_name
        if not target.exists():
            return False
        if not target.is_dir():
            raise ValueError(f"Refusing to delete non-directory path: {target}")
        shutil.rmtree(target)
        return True
