from taps_utils.migrate_metadata import migrate_file, scan_taskbeacon_files


def test_scan_finds_t_and_h_taskbeacon_files(tmp_path):
    (tmp_path / "T000001-demo").mkdir()
    (tmp_path / "H000001-demo").mkdir()
    (tmp_path / "community").mkdir()
    (tmp_path / "T000001-demo" / "taskbeacon.yaml").write_text("contracts:\n  psyflow_taps: v0.1.0\n", encoding="utf-8")
    (tmp_path / "H000001-demo" / "taskbeacon.yaml").write_text("contracts:\n  psyflow_web_taps: v0.1.0\n", encoding="utf-8")
    (tmp_path / "community" / "taskbeacon.yaml").write_text("contracts:\n  taps: v0.1.0\n", encoding="utf-8")

    found = [p.parent.name for p in scan_taskbeacon_files(tmp_path)]

    assert found == ["H000001-demo", "T000001-demo"]


def test_migrate_python_key_to_taps(tmp_path):
    path = tmp_path / "taskbeacon.yaml"
    path.write_text("contracts:\n  psyflow_taps: v0.1.0\n", encoding="utf-8")

    result = migrate_file(path, write=True)

    assert result.changed is True
    text = path.read_text(encoding="utf-8")
    assert "taps: v0.1.0" in text
    assert "psyflow_taps" not in text


def test_migrate_web_key_to_taps(tmp_path):
    path = tmp_path / "taskbeacon.yaml"
    path.write_text('title: "AX-CPT Task"\nversion:\n  release_tag: "0.1.0"\ncontracts:\n  psyflow_web_taps: v0.1.0\n', encoding="utf-8")

    result = migrate_file(path, write=True)

    assert result.changed is True
    text = path.read_text(encoding="utf-8")
    assert 'title: "AX-CPT Task"' in text
    assert 'release_tag: "0.1.0"' in text
    assert "taps: v0.1.0" in text
    assert "psyflow_web_taps" not in text


def test_dry_run_does_not_write(tmp_path):
    path = tmp_path / "taskbeacon.yaml"
    original = "contracts:\n  psyflow_taps: v0.1.0\n"
    path.write_text(original, encoding="utf-8")

    result = migrate_file(path, write=False)

    assert result.changed is True
    assert path.read_text(encoding="utf-8") == original


def test_migrate_to_v020_adds_runtime_profile(tmp_path):
    path = tmp_path / "taskbeacon.yaml"
    path.write_text("contracts:\n  taps: v0.1.0\n", encoding="utf-8")

    result = migrate_file(path, write=True, version="v0.2.0", profile="web")

    assert result.changed is True
    text = path.read_text(encoding="utf-8")
    assert "taps: v0.2.0" in text
    assert "runtime:" in text
    assert "profile: web" in text
