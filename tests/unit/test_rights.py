"""
Unit tests for rights verification and authorization enforcement.
"""

from pathlib import Path
import pytest
from manhwa_studio.rights import RightsManager
from manhwa_studio.schemas import AssetMetadata, RightsStatus
from manhwa_studio.utils.hashing import compute_file_sha256


def test_rights_authorization_lifecycle(tmp_path: Path):
    manifest_file = tmp_path / "rights.json"
    rm = RightsManager(manifest_file)

    test_img = tmp_path / "panel_01.jpg"
    test_img.write_bytes(b"dummy image content 12345")
    h = compute_file_sha256(test_img)

    # 1. Unknown asset initially
    ok, msg = rm.verify_asset("panel_01.jpg", test_img)
    assert not ok
    assert "not registered" in msg

    # 2. Register with prohibited status
    meta_prohibited = AssetMetadata(
        asset_id="panel_01.jpg",
        file_path=str(test_img),
        sha256=h,
        width=800,
        height=1200,
        format="JPEG",
        rights_status=RightsStatus.PROHIBITED,
    )
    rm.register_asset(meta_prohibited)
    ok, msg = rm.verify_asset("panel_01.jpg", test_img)
    assert not ok
    assert "unauthorized status" in msg

    # 3. Register with authorized status (permission_granted)
    meta_authorized = meta_prohibited.model_copy(update={"rights_status": RightsStatus.PERMISSION_GRANTED})
    rm.register_asset(meta_authorized)
    ok, msg = rm.verify_asset("panel_01.jpg", test_img)
    assert ok
    assert msg == "Authorized"

    # 4. Modify file -> hash mismatch
    test_img.write_bytes(b"tampered content")
    ok, msg = rm.verify_asset("panel_01.jpg", test_img)
    assert not ok
    assert "hash mismatch" in msg
