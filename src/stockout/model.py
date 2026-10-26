"""Only load the hash-verified local artifact built by this repository.
Python pickle is executable: never load an artifact supplied by a request/client.
"""
from __future__ import annotations
import json,pickle,math,hashlib
from pathlib import Path
import numpy as np
from .common import file_hash,digest
from .features import FEATURE_VERSION,FEATURE_NAMES

IMPLEMENTATION_FILES=("features.py","model.py","worker.py","decisions.py","contracts.py","ledger.py","api.py")
IDENTITY_KEYS=("artifact_sha256","feature_version","feature_names","selected_point_model","calibration_margin", "implementation_sha256","decision_policy_id","monitoring_policy_version","source_hashes","protocol_sha256","cohort_sha256","training_end","calibration_start","calibration_end")

def implementation_hashes():
    base=Path(__file__).resolve().parent
    return {name:hashlib.sha256((base/name).read_text(encoding="utf-8").replace("\r\n","\n").encode("utf-8")).hexdigest() for name in IMPLEMENTATION_FILES}

def configuration_digest(manifest):
    return digest({key:manifest[key] for key in IDENTITY_KEYS})

def bind_manifest(manifest):
    manifest=dict(manifest)
    manifest["implementation_sha256"]=implementation_hashes()
    manifest["decision_policy_id"]="raw-quantile-point-grid-v1"
    manifest["monitoring_policy_version"]="unique-label-coverage-v2"
    identity=configuration_digest(manifest)
    manifest["served_configuration_sha256"]=identity
    manifest["model_version"]=identity[:16]
    manifest["version_scope"]="pickle + inference configuration + feature/policy/ledger/API UTF-8 LF-text implementation digests"
    return manifest

class ModelBundle:
    def __init__(self, artifact_dir):
        d=Path(artifact_dir);self.manifest=json.loads((d/"model_manifest.json").read_text())
        try:identity=configuration_digest(self.manifest)
        except KeyError as e:raise ValueError("legacy manifest lacks bound served configuration") from e
        if identity!=self.manifest.get("served_configuration_sha256") or identity[:16]!=self.manifest.get("model_version"):
            raise ValueError("served configuration identity mismatch")
        if self.manifest["implementation_sha256"]!=implementation_hashes():raise ValueError("runtime implementation compatibility mismatch")
        if self.manifest["selected_point_model"] not in ["pooled_poisson","seasonal_4week_fallback_mean_28"]:raise ValueError("unknown selected model")
        if not math.isfinite(self.manifest["calibration_margin"]) or self.manifest["calibration_margin"]<0:raise ValueError("invalid calibration margin")
        if file_hash(d/"models.pkl")!=self.manifest["artifact_sha256"]:raise ValueError("model artifact hash mismatch")
        if self.manifest["feature_version"]!=FEATURE_VERSION or self.manifest["feature_names"]!=FEATURE_NAMES:
            raise ValueError("feature version mismatch")
        with (d/"models.pkl").open("rb") as f:self.models=pickle.load(f)
        self.version=self.manifest["model_version"]
    def predict(self, features):
        if not features:return []
        x=np.asarray([f["x"] for f in features],float);sc=np.array([f["scale"] for f in features])
        mean=np.maximum(0,self.models["poisson"].predict(x)*sc)
        rawlo=np.maximum(0,self.models["q10"].predict(x)*sc)
        rawhi=np.maximum(0,self.models["q90"].predict(x)*sc)
        lo=np.minimum(rawlo,rawhi);hi=np.maximum(rawlo,rawhi)
        margin=self.manifest["calibration_margin"]
        lo=np.maximum(0,lo-margin);hi=np.maximum(lo,hi+margin)
        out=[]
        for i,f in enumerate(features):
            selected=float(mean[i]) if self.manifest["selected_point_model"]=="pooled_poisson" else float(f["seasonal_4week_fallback_mean_28"])
            out.append({"point":selected,"pooled_point":float(mean[i]),"lower":float(lo[i]),"upper":float(hi[i]),
                        "interval_model":"pooled_quantile_cqr_80pct","seasonal_point":float(f["seasonal_4week_fallback_mean_28"]),"scenario_low":float(min(rawlo[i],rawhi[i])),"scenario_high":float(max(rawlo[i],rawhi[i]))})
        return out
