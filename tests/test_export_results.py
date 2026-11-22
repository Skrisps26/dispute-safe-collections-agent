import importlib.util
import json
from pathlib import Path
import shutil
import pytest

ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("failure",["collection","setup","skipped"])
def test_export_preserves_unexecuted_errors_and_skips(tmp_path,monkeypatch,failure):
    spec=importlib.util.spec_from_file_location("collections_export",ROOT/"evals/export_results.py")
    exporter=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(exporter)
    for relative in ["evals/scenarios.json","evals/judge.md","data/demo.json","prompts/v1.md","prompts/v2.md"]:
        destination=tmp_path/relative
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(ROOT/relative,destination)
    path=tmp_path/"evals/results/v1.json"
    path.parent.mkdir(parents=True)
    report={"tests":[],"collectors":[]}
    if failure=="collection":
        report["collectors"]=[{"outcome":"failed","longrepr":"collection infrastructure failure"}]
    else:
        report["tests"]=[{"nodeid":"evals/test_conversations.py::test_conversation[01]","outcome":"skipped" if failure=="skipped" else "failed","setup":{"longrepr":"setup unavailable"}}]
    path.write_text(json.dumps(report))
    monkeypatch.setattr(exporter,"ROOT",tmp_path)
    exporter.export()
    public=json.loads((tmp_path/"web/public/evals/results.json").read_text())["versions"][0]
    assert public["counts"]["executed"]==0 and public["scores"] is None
    assert public["counts"]["scored"]==0
    if failure=="skipped":
        assert public["counts"]["skipped"]==1 and public["counts"]["errors"]==0
        assert public["cases"][0]["status"]=="skipped"
    else:
        assert public["status"]=="error" and public["counts"]["errors"]==1
        assert "provider calls disabled" not in public["reason"]
