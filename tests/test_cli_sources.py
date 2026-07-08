import json
from pathlib import Path

from typer.testing import CliRunner

from remote_mcp.cli import app

runner = CliRunner()
FIXTURE = Path(__file__).parent / "fixtures" / "petstore.json"


def make_project(tmp_path: Path) -> Path:
    proj = tmp_path / "proj"
    (proj / "src" / "core").mkdir(parents=True)
    (proj / "src" / "server.py").write_text("# server", encoding="utf-8")
    (proj / "src" / "core" / "handlers.py").write_text("# handlers", encoding="utf-8")
    return proj


def test_add_openapi_generates_files_and_manifest(tmp_path):
    proj = make_project(tmp_path)
    result = runner.invoke(
        app,
        ["add", "openapi", str(FIXTURE), "-p", str(proj), "--tag", "pets", "-y"],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 0, result.output
    assert (proj / "src/tools/petstore/pets.py").exists()
    assert (proj / "tests/tools/test_petstore_pets.py").exists()
    manifest = json.loads((proj / "sources.lock.json").read_text())
    entry = manifest["sources"][0]
    assert entry["kind"] == "openapi" and entry["name"] == "petstore"
    assert sorted(entry["selected"]) == ["createPet", "getPetById", "listPets"]
    assert all(len(f["sha256"]) == 64 for f in entry["generated_files"])
    assert "mcp.mount(petstore_pets_router)" in result.output  # mount instructions


def test_add_openapi_yes_without_selectors_fails(tmp_path):
    proj = make_project(tmp_path)
    result = runner.invoke(
        app, ["add", "openapi", str(FIXTURE), "-p", str(proj), "-y"], env={"COLUMNS": "200"}
    )
    assert result.exit_code == 1
    assert "--include or --tag" in result.output


def test_add_openapi_outside_project_fails(tmp_path):
    result = runner.invoke(
        app,
        ["add", "openapi", str(FIXTURE), "-p", str(tmp_path), "--tag", "pets", "-y"],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 1
    assert "remote-mcp new" in result.output


def test_add_openapi_rerun_is_unchanged(tmp_path):
    proj = make_project(tmp_path)
    args = ["add", "openapi", str(FIXTURE), "-p", str(proj), "--tag", "pets", "-y"]
    assert runner.invoke(app, args, env={"COLUMNS": "200"}).exit_code == 0
    second = runner.invoke(app, args, env={"COLUMNS": "200"})
    assert second.exit_code == 0
    assert "unchanged" in second.output and "changed" not in second.output.replace("unchanged", "")


def test_corrupt_manifest_leaves_no_files(tmp_path):
    proj = make_project(tmp_path)
    (proj / "sources.lock.json").write_text("{not json", encoding="utf-8")
    result = runner.invoke(
        app,
        ["add", "openapi", str(FIXTURE), "-p", str(proj), "--tag", "pets", "-y"],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 2, result.output
    assert not (proj / "src/tools/petstore").exists()


def test_unusable_spec_title_exits_1(tmp_path):
    proj = make_project(tmp_path)
    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    spec["info"]["title"] = "!!!"
    bad_spec = tmp_path / "bad.json"
    bad_spec.write_text(json.dumps(spec), encoding="utf-8")
    result = runner.invoke(
        app,
        ["add", "openapi", str(bad_spec), "-p", str(proj), "--tag", "pets", "-y"],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 1, result.output
    assert "pass --name" in result.output


def test_name_flag_overrides_bad_title(tmp_path):
    proj = make_project(tmp_path)
    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    spec["info"]["title"] = "!!!"
    bad_spec = tmp_path / "bad.json"
    bad_spec.write_text(json.dumps(spec), encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "add",
            "openapi",
            str(bad_spec),
            "-p",
            str(proj),
            "--tag",
            "pets",
            "--name",
            "petstore",
            "-y",
        ],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 0, result.output


def test_tag_matches_any_position(tmp_path):
    # listPets carries tags ["store", "pets"] — "pets" is not tags[0], so a
    # selection engine that only ever inspects the first tag would miss it.
    proj = make_project(tmp_path)
    spec = json.loads(FIXTURE.read_text(encoding="utf-8"))
    spec["paths"]["/pets"]["get"]["tags"] = ["store", "pets"]
    edited_spec = tmp_path / "petstore-edited.json"
    edited_spec.write_text(json.dumps(spec), encoding="utf-8")

    result = runner.invoke(
        app,
        ["add", "openapi", str(edited_spec), "-p", str(proj), "--tag", "pets", "-y"],
        env={"COLUMNS": "200"},
    )
    assert result.exit_code == 0, result.output
    manifest = json.loads((proj / "sources.lock.json").read_text())
    entry = manifest["sources"][0]
    assert "listPets" in entry["selected"]
