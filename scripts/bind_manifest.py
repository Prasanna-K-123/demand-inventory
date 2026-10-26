"""Bind the existing fitted artifact to the complete served inference contract; no refit."""
from pathlib import Path
import json,shutil
from stockout.common import atomic_json,file_hash
from stockout.model import bind_manifest,ModelBundle
BASE=Path(__file__).resolve().parents[1]
f=BASE/"artifacts/model_manifest.json"
manifest=json.loads(f.read_text())
assert file_hash(BASE/"artifacts/models.pkl")==manifest["artifact_sha256"]
archive=BASE/"artifacts/audit"/("model_manifest_"+manifest["model_version"]+".json")
archive.parent.mkdir(exist_ok=True)
if not archive.exists():shutil.copyfile(f,archive)
updated=bind_manifest(manifest);atomic_json(f,updated)
ModelBundle(BASE/"artifacts")
print(json.dumps({"old_version":manifest["model_version"],"new_version":updated["model_version"],"served_configuration_sha256":updated["served_configuration_sha256"],"pickle_unchanged":True}))
