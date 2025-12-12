import tarfile
import json
from loguru import logger
from pathlib import Path
from dataclasses import dataclass, field
import shutil
from shared.logger import ensure_global_logger, log_dir
@dataclass
class DownloadSession:
    file_obj: any
    tmp_dir: Path = field(default_factory=Path)
    archive_path: Path = field(default_factory=Path)
    manifest_path: Path = field(default_factory=Path)
    received: int = 0
    seq: int = 0

class DownloadWizard:
    def __init__(self, username: str):
        ensure_global_logger()
        logger.add(log_dir() / "download_wizard.log", rotation="1 MB", level="INFO", mode="w")
        self.base = Path(__file__).resolve().parent.parent / "downloads" / username
        self.base.mkdir(parents=True, exist_ok=True)
        self.tmpdir = self.base / "tmp"
        self.tmpdir.mkdir(parents=True, exist_ok=True)
        self.downloadID_to_info: dict[str, DownloadSession] = dict()
        self.downloadID_to_metadata: dict[str, dict] = dict()

    def init_download_verification(self, resp_metadata: dict, download_id: str):
        """
        The First step of game downloading
        internally allocates a temp file path.
        :param download_id:
        :param resp_metadata: request/DB data to validate manifest against
        :return:
        """
        if not resp_metadata or "game_name" not in resp_metadata:
            raise ValueError("resp_metadata missing game_name")
        game_path_tmp = self.tmpdir / download_id
        game_path_tmp.mkdir(parents=True, exist_ok=True)
        game_path = game_path_tmp / "download.tar.gz"
        file = game_path.open("wb")
        self.downloadID_to_info[download_id] = DownloadSession(file, game_path_tmp, game_path)
        version_val = resp_metadata.get("version")
        if version_val is None:
            version_val = ""
        self.downloadID_to_metadata[download_id] = {
            "game_name": resp_metadata.get("game_name"),
            "version": str(version_val),
        }

    def append_chunk(self, download_id, chunk: bytes, seq: int):
        """
        Second step of game uploading: Accept sequential chunk stream and writing into file.
        :param download_id:
        :param chunk:
        :param seq:
        :return:
        """
        sess = self.downloadID_to_info.get(download_id)
        if not sess:
            raise ValueError("unknown download_id")
        if seq != sess.seq:
            raise ValueError("out-of-order chunk")
        sess.file_obj.write(chunk)
        sess.received += len(chunk)
        if seq is not None:
            sess.seq += 1

    def finalise_download(self, download_id: str):
        """
        Third step of game downloading.\n
        Close, stage, validate, and move the download into its final location.\n
        Returns a dictionary containing game archive folder path and manifest file path.
        """
        sess = self.downloadID_to_info.get(download_id)
        if not sess:
            raise ValueError("unknown download_id")
        sess.file_obj.close()
        try:
            manifest, stage_dir = self._verify_download(download_id)

            game_name = manifest["game_name"]
            version = str(manifest["version"])
            if Path(game_name).is_absolute() or ".." in Path(game_name).parts:
                raise ValueError("game_name unsafe")
            if Path(version).is_absolute() or ".." in Path(version).parts:
                raise ValueError("version unsafe")

            final_dir = self.base / game_name / version
            if final_dir.exists():
                shutil.rmtree(final_dir, ignore_errors=True)
            final_dir.parent.mkdir(parents=True, exist_ok=True)
            stage_dir.rename(final_dir)
            return {"path": str(final_dir), "manifest": manifest}
        except Exception as e:
            shutil.rmtree(sess.tmp_dir, ignore_errors=True)
            self.downloadID_to_info.pop(download_id, None)
            logger.warning(f"finalise_download failed for {download_id}: {e}")
            raise
        finally:
            shutil.rmtree(sess.tmp_dir, ignore_errors=True)
            self.downloadID_to_info.pop(download_id, None)

    def _verify_download(self, download_id: str):
        sess = self.downloadID_to_info.get(download_id)
        if not sess:
            raise ValueError("unknown download_id")
        expected = self.downloadID_to_metadata.get(download_id) or {}
        if not expected:
            raise ValueError("missing expected metadata")
        try:
            stage_dir = self._stage_verification(download_id)
            sess.manifest_path = self._find_manifest(stage_dir)
            manifest = self._align_manifest(download_id)
            return manifest, stage_dir
        except ValueError as e:
            logger.info(f"Download {download_id} failed validation: {e}")
            raise e

    def _find_manifest(self, base):
        """
        Returns the path to the manifest.json file
        :param base:
        :return:
        """
        file = list(base.rglob("manifest.json"))
        if len(file) == 1:
          return file[0]
        raise ValueError("manifest.json not found or ambiguous")

    def _stage_verification(self, download_id: str):
        sess = self.downloadID_to_info.get(download_id)
        if sess is None:
            raise ValueError(f"Cannot find DownloadSession for download ID {download_id}")
        stage_dir = sess.tmp_dir / "staged"
        if stage_dir.exists():
            shutil.rmtree(stage_dir, ignore_errors=True)
        stage_dir.mkdir(parents=True, exist_ok=True)
        with tarfile.open(sess.archive_path, "r:gz") as tar:
            for m in tar.getmembers():
                p = stage_dir / m.name
                if not p.resolve().is_relative_to(stage_dir.resolve()):
                    raise ValueError("unsafe path in archive")
            tar.extractall(stage_dir)
        return stage_dir

    def _align_manifest(self, download_id: str):
        sess = self.downloadID_to_info.get(download_id)
        if not sess or not sess.manifest_path:
            raise ValueError("manifest not staged")
        expected = self.downloadID_to_metadata.get(download_id) or {}
        manifest = json.loads(Path(sess.manifest_path).read_text(encoding="utf-8"))
        for key in ["game_name", "version"]:
            expected_val = expected.get(key, "")
            if expected_val in (None, ""):
                continue
            if str(manifest.get(key, "")) != str(expected_val):
                raise ValueError(f"{key} mismatch")
        return manifest


