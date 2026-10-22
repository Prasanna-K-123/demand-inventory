"""Keep the original research freeze and the exact post-freeze input guards.

Original method bytes and the readable revision patch remain public. Only the
listed revisions are accepted; every other frozen input uses its actual hash.
"""
from pathlib import Path
import hashlib

REVISIONS = {'src/demand_inventory/core.py': {'original_sha256': 'c40e291bbcdc2e7a8f925c855d5813ea8999c615eaa86ce150dfec7fdeb87e3d', 'revised_sha256': '67cc56b345b871c69d5a84ebc3048a712a773dce1b31dc538b8319fe34a7ed77', 'preserved_path': 'reproducibility/original_core.py'}, 'scripts/train_and_freeze.py': {'original_sha256': '587c64dc821b401eb138e5cdad53b08dbb72c30926abb5d7fc32d440e35c2212', 'revised_sha256': '4bf2664669b3e63c4c6a137b9a0fd1356fcfec22f55d9377f0854ae4bbda0f90', 'preserved_path': 'reproducibility/original_train_and_freeze.py'}, 'scripts/evaluate_final.py': {'original_sha256': '3285f1340386c4e2b884d7b5edaece1513788cec096b3e5213b04b662db70771', 'revised_sha256': '61d7716a8e52160bc4568bfc462b6db7816b85bf11312d8dedbc8c068bd21aff', 'preserved_path': 'reproducibility/original_evaluate_final.py'}}
PATCH_SHA256 = 'e49bfe690bbf3f5ebfd45fc924770e411f1d334c4d469bede6168441bacf0aea'
CONTRACTS_SHA256 = '5f7ead2c3eea3bb2ef2daabbac74154219abed90d8cf2ed0dbd1331e0a75ffe6'
ORIGIN_PATCH_SHA256 = '1c6ec23cd538475aab9821a735712f5b4a02cfca351ca3baae37222f11ce80c7'

def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_revision(root):
    root = Path(root)
    if digest(root / 'reproducibility/input_contract_revision_20261022.patch') != PATCH_SHA256:
        raise RuntimeError('Input-contract revision patch changed')
    if digest(root / 'reproducibility/origin_dtype_revision_20261022.patch') != ORIGIN_PATCH_SHA256:
        raise RuntimeError('Origin-dtype revision patch changed')
    if digest(root / 'src/demand_inventory/_contracts.py') != CONTRACTS_SHA256:
        raise RuntimeError('Input-contract implementation changed')
    for path, revision in REVISIONS.items():
        if digest(root / path) != revision['revised_sha256']:
            raise RuntimeError('Unrecorded method revision: ' + path)
        if digest(root / revision['preserved_path']) != revision['original_sha256']:
            raise RuntimeError('Preserved research source changed: ' + path)
    return {'checked_revisions': list(REVISIONS), 'original_sources_preserved': True,
            'exact_revision_and_input_guards_verified': True}


def research_digest(root, path):
    if path in REVISIONS:
        verify_revision(root)
        return REVISIONS[path]['original_sha256']
    return digest(Path(root) / path)
