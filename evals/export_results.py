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
        records = [t["metadata"]["conversation"] for t in existing.get("tests",[]) if "conversation" in t.get("metadata",{})]
        if not records and existing.get("status") == "not_run":
            records = existing.get("cases",[])
        by_id = {r["id"]:r for r in records}
        rows = [by_id.get(c["id"], {"id":c["id"],"status":"not_run","scores":None,"reason":"Not run — provider calls disabled / credentials unavailable"}) for c in cases]
        counts = {"executed":sum(r["status"] != "not_run" for r in rows),
                  "scored":sum(r.get("scores") is not None for r in rows),
                  "errors":sum(r["status"] == "error" for r in rows),
                  "unrun":sum(r["status"] == "not_run" for r in rows),
                  "passed":sum(r["status"] == "passed" for r in rows)}
        scores = {d:{"sum":sum(r["scores"][d]["score"] for r in rows if r.get("scores")),"scored_count":counts["scored"]} for d in DIMENSIONS} if counts["scored"] else None
        result = {"version":version,"status":"not_run" if not counts["executed"] else "completed" if counts["executed"] == 30 else "partial",
            "timestamp":existing.get("timestamp") or datetime.now(timezone.utc).isoformat(), "model":"muse-spark-1.3", "provider":"https://api.meta.ai/v1", "counts":counts,
            "hashes":{p:digest(p) for p in [f"prompts/{version}.md","evals/scenarios.json","data/demo.json","evals/judge.md"]},
            "scores":scores,"cases":rows,"reason":"Not run — provider calls disabled / credentials unavailable" if not counts["executed"] else None}
        if not existing or existing.get("status") == "not_run":
            path.parent.mkdir(parents=True,exist_ok=True)
            path.write_text(json.dumps(result,indent=2)+"\n")
        versions.append(result)
    public = ROOT / "web/public/evals"
    public.mkdir(parents=True,exist_ok=True)
    (public / "results.json").write_text(json.dumps({"dimensions":DIMENSIONS,"method":"30 fixed multi-turn scripts; shared LiveKit agent; deterministic authorization/state/provenance checks override same-model Muse Spark 1.3 high-reasoning judge. A pass requires 4/4 on every criterion.","versions":versions},indent=2)+"\n")
    table = "| Prompt | Executed | Scored | Errors | Unrun | Scores |\n|---|---:|---:|---:|---:|---|\n"
    for v in versions:
        c=v["counts"]
        table += f"| {v['version']} | {c['executed']}/30 | {c['scored']} | {c['errors']} | {c['unrun']} | " + (str(v["scores"]) if v["scores"] else "Not run — no numeric scores") + " |\n"
    (ROOT / "evals/results/table.md").write_text(table)
    print(table)


if __name__ == "__main__":
    export()
