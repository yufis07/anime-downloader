import hashlib
import io
import json
import zipfile

import pytest

from animepahe_dl import config, ffmpeg_install
from animepahe_dl.config import Settings
from animepahe_dl.ffmpeg_install import FfmpegInstallError, install_ffmpeg, parse_sha256


# ---------------------------------------------------------------- portable mode
def test_portable_marker_switches_the_data_folder(tmp_path, monkeypatch):
    monkeypatch.delenv("ANIMEPAHEDL_DATA", raising=False)
    monkeypatch.setattr(config, "app_dir", lambda: tmp_path)
    assert config.portable_root() is None and not config.is_portable()
    (tmp_path / "portable.txt").write_text("", encoding="utf-8")
    assert config.portable_root() == tmp_path and config.is_portable()
    assert config.app_data_dir() == tmp_path / "data" and (tmp_path / "data").is_dir()
    assert config.default_download_dir() == tmp_path / "Anime"
    assert Settings.default_path() == tmp_path / "data" / "settings.json"


def test_environment_variable_overrides_everything(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIMEPAHEDL_DATA", str(tmp_path / "elsewhere"))
    assert config.app_data_dir() == tmp_path / "elsewhere" and config.is_portable()


# ---------------------------------------------------------------- first-run flag
def test_new_install_needs_setup_but_existing_settings_do_not(tmp_path):
    missing = Settings.load(tmp_path / "none.json")
    assert missing.setup_done is False
    old = tmp_path / "old.json"
    old.write_text(json.dumps({"quality": 720}), encoding="utf-8")  # written before the wizard existed
    assert Settings.load(old).setup_done is True and Settings.load(old).quality == 720
    fresh = Settings()
    fresh.setup_done = False
    fresh.save(tmp_path / "new.json")
    assert Settings.load(tmp_path / "new.json").setup_done is False  # explicit False is kept


# ---------------------------------------------------------------- ffmpeg install
def make_zip(with_exe=True):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("ffmpeg-7.1-essentials_build/LICENSE", "x")
        if with_exe:
            zf.writestr("ffmpeg-7.1-essentials_build/bin/ffmpeg.exe", b"MZ-fake-ffmpeg")
    return buf.getvalue()


class FakeHttp:
    def __init__(self, archive, digest=None, checksum_error=None):
        self.archive = archive
        self.digest = digest or hashlib.sha256(archive).hexdigest()
        self.checksum_error = checksum_error
        self.urls = []

    def get_text(self, url, **kwargs):
        self.urls.append(url)
        if self.checksum_error:
            raise self.checksum_error
        return f"{self.digest}  ffmpeg-release-essentials.zip\n"

    def download_file(self, url, dest, progress=None, should_stop=None, **kwargs):
        self.urls.append(url)
        dest.write_bytes(self.archive)
        if progress:
            progress(len(self.archive), len(self.archive), len(self.archive))
        return len(self.archive)


def test_parse_sha256():
    digest = "ab" * 32
    assert parse_sha256(f"{digest.upper()} *file.zip") == digest
    with pytest.raises(FfmpegInstallError):
        parse_sha256("not a checksum")


def test_install_ffmpeg_verifies_and_unpacks(tmp_path):
    seen = []
    target = install_ffmpeg(FakeHttp(make_zip()), tmp_path / "tools", progress=lambda d, t, a: seen.append(d))
    assert target == tmp_path / "tools" / "ffmpeg.exe" and target.read_bytes() == b"MZ-fake-ffmpeg"
    assert not (tmp_path / "tools" / "ffmpeg-download.zip").exists() and seen


def test_install_refuses_a_wrong_checksum(tmp_path):
    with pytest.raises(FfmpegInstallError, match="checksum"):
        install_ffmpeg(FakeHttp(make_zip(), digest="0" * 64), tmp_path / "tools")
    assert not (tmp_path / "tools" / "ffmpeg.exe").exists()
    assert not (tmp_path / "tools" / "ffmpeg-download.zip").exists()


def test_install_reports_missing_exe_missing_checksum_and_bad_zip(tmp_path):
    with pytest.raises(FfmpegInstallError, match="bin/ffmpeg.exe"):
        install_ffmpeg(FakeHttp(make_zip(with_exe=False)), tmp_path / "a")
    from animepahe_dl.http import HttpError

    with pytest.raises(FfmpegInstallError, match="checksum"):
        install_ffmpeg(FakeHttp(make_zip(), checksum_error=HttpError("HTTP 404", 404)), tmp_path / "b")
    junk = b"this is not a zip"
    with pytest.raises(FfmpegInstallError, match="not a valid zip"):
        install_ffmpeg(FakeHttp(junk), tmp_path / "c")
    assert ffmpeg_install.FFMPEG_ZIP_URL.endswith(".zip")


def test_find_ffmpeg_sees_the_installed_copy(tmp_path, monkeypatch):
    from animepahe_dl import utils

    monkeypatch.setenv("ANIMEPAHEDL_DATA", str(tmp_path))
    exe = "ffmpeg.exe" if utils.sys.platform == "win32" else "ffmpeg"
    tools = tmp_path / "tools"
    tools.mkdir()
    (tools / exe).write_bytes(b"x")
    (tools / exe).chmod(0o755)
    monkeypatch.setattr(utils.shutil, "which", lambda _n: None)
    assert utils.find_ffmpeg("") == str(tools / exe)
