"""Export actual pytest metadata, or explicit unrun artifacts. Never manufacture scores."""
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIMENSIONS = ["factual_accuracy","on_topic","no_pressure","no_data_leaks","correct_escalation"]


def digest(path):
    return hashlib.sha256((ROOT / path).read_bytes()).hexdigest()


def export():
    cases = json.loads((ROOT / "evals/scenarios.json").read_text())
    versions = []
    for version in ("v1","v2"):
        path = ROOT / f"evals/results/{version}.json"
        existing = json.loads(path.read_text()) if path.exists() else {}
        records = []
        infrastructure_errors = [str(c.get("longrepr", "Collection failed")) for c in existing.get("collectors", []) if c.get("outcome") == "failed"]
        for test in existing.get("tests", []):
            record = test.get("metadata", {}).get("conversation")
            if record is not None:
                records.append(record)
                continue
            case_id = test.get("nodeid", "").rsplit("[", 1)[-1].removesuffix("]")
            if case_id not in {c["id"] for c in cases}:
                continue
            outcome = test.get("outcome")
            if outcome in {"failed", "error", "skipped"}:
                records.append({"id":case_id, "status":"skipped" if outcome == "skipped" else "error",
                    "executed":False, "scores":None, "error":str(test.get("setup", {}).get("longrepr", outcome))})
        if not records and existing.get("status") == "not_run":
            records = existing.get("cases",[])
        by_id = {r["id"]:r for r in records}
        missing_reason = "Not executed in this run" if "tests" in existing or infrastructure_errors else "Not run — provider calls disabled / credentials unavailable"
        rows = [by_id.get(c["id"], {"id":c["id"],"status":"not_run","executed":False,"scores":None,"reason":missing_reason}) for c in cases]
        counts = {"executed":sum(r["status"] not in {"not_run","skipped"} and r.get("executed",True) for r in rows),
                  "scored":sum(r.get("scores") is not None for r in rows),
                  "errors":sum(r["status"] == "error" for r in rows) + len(infrastructure_errors),
                  "skipped":sum(r["status"] == "skipped" for r in rows),
                  "unrun":sum(r["status"] == "not_run" for r in rows),
                  "passed":sum(r["status"] == "passed" for r in rows)}
        scores = {d:{"sum":sum(r["scores"][d]["score"] for r in rows if r.get("scores")),"scored_count":counts["scored"]} for d in DIMENSIONS} if counts["scored"] else None
        status = "error" if infrastructure_errors or counts["errors"] and not counts["executed"] else "completed" if counts["executed"] == 30 else "partial" if counts["executed"] or counts["skipped"] else "not_run"
        reason = "Evaluation infrastructure failed; see errors" if infrastructure_errors else missing_reason if not counts["executed"] else None
        result = {"version":version,"status":status,
            "timestamp":existing.get("timestamp") or datetime.now(timezone.utc).isoformat(), "model":"muse-spark-1.3", "provider":"https://api.meta.ai/v1", "counts":counts,
            "hashes":{p:digest(p) for p in [f"prompts/{version}.md","evals/scenarios.json","data/demo.json","evals/judge.md"]},
            "scores":scores,"cases":rows,"reason":reason,"infrastructure_errors":infrastructure_errors}
        if not existing or existing.get("status") == "not_run":
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(result,indent=2)+"\n")
        versions.append(result)
    public = ROOT / "web/public/evals"
    public.mkdir(parents=True,exist_ok=True)
    (public / "results.json").write_text(json.dumps({"dimensions":DIMENSIONS,"method":"30 fixed multi-turn scripts; shared LiveKit agent; deterministic authorization/state/provenance checks override same-model Muse Spark 1.3 high-reasoning judge. A pass requires 4/4 on every criterion.","versions":versions},indent=2)+"\n")
    table = "| Prompt | Executed | Scored | Errors | Skipped | Unrun | Scores |\n|---|---:|---:|---:|---:|---:|---|\n"
    for v in versions:
        c=v["counts"]
        table += f"| {v['version']} | {c['executed']}/30 | {c['scored']} | {c['errors']} | {c['skipped']} | {c['unrun']} | " + (str(v["scores"]) if v["scores"] else "Not run — no numeric scores") + " |\n"
    (ROOT / "evals/results/table.md").write_text(table)
    print(table)


if __name__ == "__main__":
    export()
