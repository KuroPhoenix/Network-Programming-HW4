import json
import shutil
from pathlib import Path
from typing import List, Dict, Any


class LocalGameManager:
    """
    Manage locally downloaded games for a user.
    Downloads live at user/downloads/<username>/<game_name>/<version>/manifest.json.
    """

    def __init__(self, username: str, base_dir: Path | None = None):
        self.base_dir = (base_dir or Path(__file__).resolve().parent.parent / "downloads") / str(username)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _game_dir(self, game_name: str) -> Path:
        return self.base_dir / game_name

    def _manifest_path(self, game_name: str, version: str) -> Path:
        return self._game_dir(game_name) / str(version) / "manifest.json"

    def list_games(self) -> List[Path]:
        """
        Return game directories that contain at least one version with a manifest.
        """
        if not self.base_dir.exists():
            return []
        games: List[Path] = []
        for game_dir in self.base_dir.iterdir():
            if not game_dir.is_dir():
                continue
            has_manifest = any((vdir / "manifest.json").exists() for vdir in game_dir.iterdir() if vdir.is_dir())
            if has_manifest:
                games.append(game_dir)
        return games

    def list_versions(self, game_name: str) -> List[str]:
        """
        List version folder names for a given game that contain manifest.json.
        """
        gdir = self._game_dir(game_name)
        if not gdir.exists():
            return []
        versions: List[str] = []
        for vdir in gdir.iterdir():
            if vdir.is_dir() and (vdir / "manifest.json").exists():
                versions.append(vdir.name)
        return sorted(versions)

    def load_manifest(self, game_name: str, version: str | None = None) -> Dict[str, Any]:
        """
        Read manifest.json for a specific game/version. If version is None, uses the highest available version.
        """
        versions = self.list_versions(game_name)
        if not versions:
            raise FileNotFoundError(f"No installed versions for {game_name}")
        target_version = version or versions[-1]
        manifest_path = self._manifest_path(game_name, target_version)
        return json.loads(manifest_path.read_text(encoding="utf-8"))

    def list_manifests(self) -> List[Dict[str, Any]]:
        """
        Return minimal manifest info for all local game versions.
        """
        manifests: List[Dict[str, Any]] = []
        for game_dir in self.list_games():
            game_name = game_dir.name
            for version in self.list_versions(game_name):
                try:
                    manifest = self.load_manifest(game_name, version)
                    manifests.append(
                        {
                            "game_name": manifest.get("game_name"),
                            "version": manifest.get("version"),
                            "type": manifest.get("type"),
                            "description": manifest.get("description"),
                            "_path": str(self._manifest_path(game_name, version).parent),
                        }
                    )
                except Exception:
                    continue
        return manifests

    def delete_version(self, game_name: str, version: str) -> bool:
        """
        Remove a specific version folder for a game.
        """
        vdir = self._manifest_path(game_name, version).parent
        base_resolved = self.base_dir.resolve()
        try:
            resolved = vdir.resolve()
            if not resolved.is_relative_to(base_resolved):
                raise ValueError("unsafe path")
        except FileNotFoundError:
            return False
        if vdir.exists():
            shutil.rmtree(vdir, ignore_errors=True)
            return True
        return False

    def delete_game(self, game_name: str) -> bool:
        """
        Remove all local versions of a game.
        """
        gdir = self._game_dir(game_name)
        base_resolved = self.base_dir.resolve()
        try:
            resolved = gdir.resolve()
            if not resolved.is_relative_to(base_resolved):
                raise ValueError("unsafe path")
        except FileNotFoundError:
            return False
        if gdir.exists():
            shutil.rmtree(gdir, ignore_errors=True)
            return True
        return False
