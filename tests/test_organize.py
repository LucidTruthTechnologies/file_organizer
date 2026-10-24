from __future__ import annotations

import csv
import hashlib
import os

import pytest
import pytsk3
from fixture_lib import FILES, IMAGES, VIDEOS, write_tree

from file_organizer import cli, pipeline
from file_organizer.ewf_reader import open_e01
from file_organizer.extensions import (BUNDLED_LIST, IMAGE_EXTENSIONS, VIDEO_EXTENSIONS, load_extension_list,
                                       select_extensions)
from file_organizer.pipeline import Options, run, safe_name


def _manifest(summary) -> list[dict[str, str]]:
    with open(summary.manifest, encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _sha(path: str) -> str:
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read()).hexdigest()


def _copied(out: str) -> dict[str, list[str]]:
    """{extension folder: sorted file names}, manifest and log excluded."""
    return {d: sorted(os.listdir(os.path.join(out, d))) for d in sorted(os.listdir(out))
            if os.path.isdir(os.path.join(out, d))}


# -- extension selection -------------------------------------------------------

def test_bundled_list_parses_to_real_extensions():
    exts = load_extension_list(BUNDLED_LIST)
    assert {".jpg", ".mp4", ".docx", ".one", ".pdf"} <= exts
    assert all(e.startswith(".") and ":" not in e and " " not in e for e in exts)


def test_images_and_videos_switches_alone_and_together():
    imgs, _ = select_extensions(images=True, videos=False)
    vids, _ = select_extensions(images=False, videos=True)
    both, origin = select_extensions(images=True, videos=True)
    assert imgs == IMAGE_EXTENSIONS and vids == VIDEO_EXTENSIONS
    assert both == IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
    assert not (IMAGE_EXTENSIONS & VIDEO_EXTENSIONS)
    assert "images and videos" in origin


def test_safe_name_handles_windows_hazards():
    assert safe_name('a:b?.jpg') == "a_b_.jpg"
    assert safe_name("CON.jpg") == "_CON.jpg"
    assert safe_name("trail. .jpg") == "trail.jpg"
    assert pipeline._units(safe_name("x" * 400 + ".jpg")) <= pipeline.MAX_NAME_UNITS
    # emoji are two UTF-16 units each; the cap counts units, not code points
    assert pipeline._units(safe_name("\U0001F600" * 150 + ".jpg")) <= pipeline.MAX_NAME_UNITS
    # a device name before the FIRST dot, and the newer reserved names
    for bad in ("con.foo.jpg", "CONIN$.jpg", "COM¹.jpg", "nul .jpg"):
        assert safe_name(bad).startswith("_"), bad


def test_namer_folds_case_like_ntfs(tmp_path):
    n = pipeline._Namer()
    assert n.claim(str(tmp_path), "xσ.jpg") == "xσ.jpg"
    assert n.claim(str(tmp_path), "xς.jpg") == "xς (2).jpg"  # final sigma upper-cases the same


# -- folder sources ------------------------------------------------------------

def test_folder_source_sorts_and_never_overwrites(tmp_path):
    write_tree(str(tmp_path / "src"))
    out = tmp_path / "out"
    s = run(Options(sources=[str(tmp_path / "src")], output_dir=str(out), images=True))
    assert s.files_copied == IMAGES and s.files_failed == 0
    got = _copied(str(out))
    assert got == {"Extension-.jpg": ["beach (2).jpg", "beach.jpg"], "Extension-.png": ["diagram.png"]}
    rows = _manifest(s)
    assert len(rows) == IMAGES
    for r in rows:
        dest = os.path.join(str(out), *r["output_path"].split("/"))
        assert _sha(dest) == r["sha256"] == _sha(r["path_in_source"])
        assert int(os.path.getmtime(dest)) == 1_600_000_000
        assert r["modified_utc"] == "2020-09-13T12:26:40Z"


def test_two_folder_sources_in_one_run(tmp_path):
    write_tree(str(tmp_path / "a"))
    write_tree(str(tmp_path / "b"))
    s = run(Options(sources=[str(tmp_path / "a"), str(tmp_path / "b")], output_dir=str(tmp_path / "out"),
                    videos=True))
    assert s.files_copied == 2 * VIDEOS
    assert len(os.listdir(tmp_path / "out" / "Extension-.mp4")) == 2


def test_output_inside_source_is_not_rescanned(tmp_path):
    src = tmp_path / "src"
    write_tree(str(src))
    s = run(Options(sources=[str(src)], output_dir=str(src / "sorted"), images=True))
    assert s.files_copied == IMAGES
    again = run(Options(sources=[str(src)], output_dir=str(src / "sorted"), images=True))
    assert again.files_copied == IMAGES  # the first run's copies were not picked up
    assert os.path.basename(again.manifest).startswith("manifest-")  # first manifest kept


def test_manifests_from_quick_reruns_never_collide(tmp_path):
    write_tree(str(tmp_path / "src"))
    names = {os.path.basename(run(Options(sources=[str(tmp_path / "src")], output_dir=str(tmp_path / "out"),
                                          images=True)).manifest) for _ in range(3)}
    assert len(names) == 3


def test_error_mid_run_still_writes_manifest(tmp_path, monkeypatch):
    write_tree(str(tmp_path / "src"))
    calls = {"n": 0}
    real = pipeline._take

    def flaky(*a, **k):
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("boom")
        return real(*a, **k)

    monkeypatch.setattr(pipeline, "_take", flaky)
    with pytest.raises(RuntimeError):
        run(Options(sources=[str(tmp_path / "src")], output_dir=str(tmp_path / "out")))
    with open(tmp_path / "out" / "manifest.csv", encoding="utf-8") as fh:
        assert len(list(csv.DictReader(fh))) == 2


def test_non_e01_file_source_refused_before_copying(tmp_path):
    write_tree(str(tmp_path / "src"))
    bogus = tmp_path / "notes.dd"
    bogus.write_bytes(b"\x00" * 4096)
    with pytest.raises(ValueError):
        run(Options(sources=[str(tmp_path / "src"), str(bogus)], output_dir=str(tmp_path / "out")))
    assert not (tmp_path / "out").exists()


def test_export_inside_a_source_or_output_is_refused(tmp_path):
    write_tree(str(tmp_path / "src"))
    for bad in (tmp_path / "src" / "e.E01", tmp_path / "out" / "e.E01"):
        os.makedirs(tmp_path / "out", exist_ok=True)
        with pytest.raises(ValueError):
            run(Options(sources=[str(tmp_path / "src")], output_dir=str(tmp_path / "out"), export_e01=str(bad)))


def test_formula_names_are_neutralised_in_manifest(tmp_path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "=HYPERLINK(1).jpg").write_bytes(b"x")
    s = run(Options(sources=[str(tmp_path / "src")], output_dir=str(tmp_path / "out"), images=True))
    row = _manifest(s)[0]
    assert row["output_path"] == "'Extension-.jpg/=HYPERLINK(1).jpg" or row["output_path"].startswith("Extension-")
    assert not any(v.startswith("=") for v in row.values())


def test_source_inside_output_is_refused(tmp_path):
    write_tree(str(tmp_path / "out" / "src"))
    with pytest.raises(ValueError):
        run(Options(sources=[str(tmp_path / "out" / "src")], output_dir=str(tmp_path / "out")))


def test_default_list_takes_documents_but_not_unlisted(tmp_path):
    write_tree(str(tmp_path / "src"))
    s = run(Options(sources=[str(tmp_path / "src")], output_dir=str(tmp_path / "out")))
    got = _copied(str(tmp_path / "out"))
    assert "Extension-.docx" in got and "Extension-.txt" in got
    assert "Extension-.zzq" not in got
    assert s.files_copied == len(FILES) - 1


# -- E01 sources ---------------------------------------------------------------

def test_e01_source_with_forward_slashes_images_and_videos(source_e01, tmp_path):
    before = _sha(source_e01)
    s = run(Options(sources=[source_e01.replace("\\", "/")], output_dir=str(tmp_path / "out"),
                    images=True, videos=True))
    assert s.files_copied == IMAGES + VIDEOS and s.files_failed == 0
    got = _copied(str(tmp_path / "out"))
    assert sorted(got) == ["Extension-.jpg", "Extension-.mov", "Extension-.mp4", "Extension-.png"]
    by_src = {r["path_in_source"].split("/", 1)[1]: r for r in _manifest(s)}
    for rel, row in by_src.items():
        assert row["sha256"] == hashlib.sha256(FILES[rel]).hexdigest()
        assert row["source_kind"] == "e01"
    assert _sha(source_e01) == before  # the source image is untouched


def test_export_e01_reads_back_identical(source_e01, tmp_path):
    out = tmp_path / "out"
    export = tmp_path / "sorted.E01"
    s = run(Options(sources=[source_e01], output_dir=str(out), images=True, videos=True,
                    export_e01=str(export), examiner="pytest", case_number="T2"))
    assert s.e01_segments == [str(export)] and s.e01_excluded == 0
    img, info = open_e01(str(export))
    try:
        fs = pytsk3.FS_Info(img, offset=2048 * 512)
        expected = {r["output_path"]: r["sha256"] for r in _manifest(s)}
        for rel, sha in expected.items():
            f = fs.open("/" + rel)
            assert hashlib.sha256(f.read_random(0, f.info.meta.size)).hexdigest() == sha
        names = {e.info.name.name.decode() for e in fs.open_dir("/")}
        assert {"manifest.csv", pipeline.LOG_NAME} <= names
        assert info.header_values.get("examiner_name") == "pytest"
    finally:
        img.close()


def test_export_leaves_out_files_fat32_cannot_hold(source_e01, tmp_path, monkeypatch):
    monkeypatch.setattr(pipeline, "FAT32_MAX_FILE", 1000)  # stands in for 4 GiB
    s = run(Options(sources=[source_e01], output_dir=str(tmp_path / "out"), images=True,
                    export_e01=str(tmp_path / "x.E01")))
    rows = _manifest(s)
    small = [r for r in rows if int(r["bytes_copied"]) <= 1000]
    big = [r for r in rows if int(r["bytes_copied"]) > 1000]
    assert big and all(r["in_e01"] == "no" and "FAT32" in r["note"] for r in big)
    assert all(r["in_e01"] == "yes" for r in small)
    assert s.e01_excluded == len(big)


def test_export_refuses_to_replace_source(source_e01, tmp_path):
    with pytest.raises(ValueError):
        run(Options(sources=[source_e01], output_dir=str(tmp_path / "out"), export_e01=source_e01,
                    overwrite=True))


# -- command line --------------------------------------------------------------

def test_cli_missing_source_exits_4(tmp_path, capsys):
    assert cli.main(["--source", str(tmp_path / "nope"), "--output", str(tmp_path / "o")]) == 4


def test_cli_needs_output(tmp_path):
    with pytest.raises(SystemExit) as exc:
        cli.main(["--source", str(tmp_path)])
    assert exc.value.code == 2


def test_cli_images_and_videos_together(source_e01, tmp_path, capsys):
    rc = cli.main(["--source", source_e01, "--output", str(tmp_path / "o"), "--images", "--videos"])
    assert rc == 0
    assert f"files_copied={IMAGES + VIDEOS}" in capsys.readouterr().out
