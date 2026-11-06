"""Published archive selection and downloader failures are checked without network."""
import hashlib
import io
import json
import tarfile
from unittest.mock import Mock
import urllib.error
import urllib.request

import pytest

from scripts import download_data as downloader


class Response(io.BytesIO):
    def geturl(self):
        return "https://huggingface.co/verified-archive"


def archive_bytes(unsafe=False):
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode="w:gz") as archive:
        for name, content in [("skills_200/example/SKILL.md", b"# Example skill\n"),
                              ("../escape" if unsafe else "skills_200/NOTICE", b"Fixture\n")]:
            member = tarfile.TarInfo(name)
            member.size = len(content)
            archive.addfile(member, io.BytesIO(content))
    return output.getvalue()


def mock_download(monkeypatch, payload=None):
    payload = archive_bytes() if payload is None else payload
    monkeypatch.setitem(downloader.ARCHIVES, "skills_200.tar.gz",
                        (len(payload), hashlib.sha256(payload).hexdigest()))
    opener = Mock(side_effect=lambda url: Response(payload))
    monkeypatch.setattr(downloader, "_open_url", opener)
    return payload, opener


def test_all_eight_pinned_mappings_and_dry_run(tmp_path, monkeypatch, capsys):
    expected = [
        "skills_200.tar.gz", "goskills_workspace_skills_200_v1.tar.gz",
        "skills_500.tar.gz", "goskills_workspace_skills_500_v1.tar.gz",
        "skills_1000.tar.gz", "goskills_workspace_skills_1000_v1.tar.gz",
        "skills_2000.tar.gz", "goskills_workspace_skills_2000_v1.tar.gz",
    ]
    assert downloader.selected_archives() == expected
    assert set(downloader.ARCHIVES) == set(expected)
    assert downloader.selected_archives([1000, 200, 200], "skills") == [expected[0], expected[4]]
    assert downloader.selected_archives([500], "workspaces") == [expected[3]]
    opener = Mock(side_effect=AssertionError("dry-run must not download"))
    monkeypatch.setattr(downloader, "_open_url", opener)
    output = tmp_path / "assets"
    assert downloader.main(["--dry-run", "--output", str(output)]) == 0
    rows = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(rows) == 8
    prefix = "https://huggingface.co/datasets/yuhuo03/group-of-skills-data/resolve/80773c48bed0471fc15dd680467b9fcd8becaed3/"
    for name, row in zip(expected, rows):
        size, digest = downloader.ARCHIVES[name]
        assert row == {"url": prefix + name, "bytes": size, "sha256": digest,
                       "output": str(output / name.removesuffix(".tar.gz"))}
        assert size > 0 and len(bytes.fromhex(digest)) == 32
    assert not output.exists()
    opener.assert_not_called()


def test_verified_download_strips_root_and_writes_receipt_last(tmp_path, monkeypatch):
    payload, opener = mock_download(monkeypatch)
    original_move = downloader.shutil.move
    target = tmp_path / "skills_200"

    def observe_move(source, destination):
        assert not (target / "DOWNLOAD_RECEIPT.json").exists()
        return original_move(source, destination)

    monkeypatch.setattr(downloader.shutil, "move", observe_move)
    assert downloader.main(["--sizes", "200", "--assets", "skills", "--output", str(tmp_path)]) == 0
    assert (target / "example/SKILL.md").read_text() == "# Example skill\n"
    assert not (target / "skills_200").exists()
    receipt = json.loads((target / "DOWNLOAD_RECEIPT.json").read_text())
    assert receipt["archive_bytes"] == len(payload)
    assert receipt["archive_sha256"] == hashlib.sha256(payload).hexdigest()
    assert receipt["files"] == 2 and receipt["hash_pinned"] is True
    opener.assert_called_once_with(downloader.asset_url("skills_200.tar.gz"))
    assert sorted(path.name for path in tmp_path.iterdir()) == ["skills_200"]


@pytest.mark.parametrize("failure", ["hash", "short", "long", "unsafe", "network", "publish"])
def test_failed_download_leaves_no_partial_asset(tmp_path, monkeypatch, failure, capsys):
    payload, opener = mock_download(monkeypatch, archive_bytes(unsafe=failure == "unsafe"))
    size, digest = downloader.ARCHIVES["skills_200.tar.gz"]
    if failure == "hash":
        monkeypatch.setitem(downloader.ARCHIVES, "skills_200.tar.gz", (size, "0" * 64))
    elif failure in {"short", "long"}:
        monkeypatch.setitem(downloader.ARCHIVES, "skills_200.tar.gz",
                            (size + (1 if failure == "short" else -1), digest))
    elif failure == "network":
        class BrokenResponse(Response):
            def read(self, count=-1):
                if self.tell():
                    raise OSError("connection lost")
                return super().read(10)
        opener.side_effect = lambda url: BrokenResponse(payload)
    elif failure == "publish":
        original_move = downloader.shutil.move
        calls = []

        def failed_move(source, destination):
            if calls:
                raise OSError("publication interrupted")
            calls.append(source)
            return original_move(source, destination)

        monkeypatch.setattr(downloader.shutil, "move", failed_move)
    assert downloader.main(["--sizes", "200", "--assets", "skills", "--output", str(tmp_path)]) == 1
    assert list(tmp_path.iterdir()) == []
    assert capsys.readouterr().err.startswith("error: ")


@pytest.mark.parametrize("kind", ["directory", "file", "symlink", "broken_symlink"])
def test_every_existing_target_is_refused_before_network(tmp_path, monkeypatch, kind):
    # This is later in the default eight-archive selection: preflight checks all.
    target = tmp_path / "goskills_workspace_skills_500_v1"
    if kind == "directory":
        target.mkdir()
    elif kind == "file":
        target.write_text("keep")
    else:
        other = tmp_path / "other"
        if kind == "symlink":
            other.write_text("keep")
        target.symlink_to(other)
    opener = Mock(side_effect=AssertionError("existing targets must prevent network"))
    monkeypatch.setattr(downloader, "_open_url", opener)
    assert downloader.main(["--output", str(tmp_path)]) == 1
    opener.assert_not_called()
    assert target.is_symlink() if "symlink" in kind else target.exists()
    if kind == "file":
        assert target.read_text() == "keep"


def test_destination_created_during_download_is_preserved(tmp_path, monkeypatch):
    payload, opener = mock_download(monkeypatch)
    target = tmp_path / "skills_200"

    def raced_open(url):
        target.mkdir()
        (target / "keep").write_text("existing data")
        return Response(payload)

    opener.side_effect = raced_open
    with pytest.raises(FileExistsError):
        downloader.download_asset("skills_200.tar.gz", tmp_path)
    assert (target / "keep").read_text() == "existing data"
    assert list(target.iterdir()) == [target / "keep"]
    assert not list(tmp_path.glob(".goskills-download-*"))


def test_invalid_size_is_rejected_before_network(tmp_path, monkeypatch):
    opener = Mock(side_effect=AssertionError("invalid sizes must prevent network"))
    monkeypatch.setattr(downloader, "_open_url", opener)
    with pytest.raises(SystemExit) as error:
        downloader.main(["--sizes", "100", "--output", str(tmp_path / "assets")])
    assert error.value.code == 2
    opener.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_https_redirects_cannot_downgrade_transport():
    handler = downloader._HTTPSRedirectHandler()
    request = urllib.request.Request("https://huggingface.co/archive")
    with pytest.raises(urllib.error.URLError, match="non-HTTPS"):
        handler.redirect_request(request, None, 302, "Found", {}, "http://example.com/archive")
