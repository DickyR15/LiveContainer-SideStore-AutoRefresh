#!/usr/bin/env python3
"""Adapt the NRG builder to the verified 20260918 source pair."""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path("builder/scripts")
LIVE = os.environ["LIVE_CONTAINER_REF"]
SIDESTORE = os.environ["EMBEDDED_SIDESTORE_REF"]
SIDESIGN = os.environ["SIDESIGN_REF"]

PIN_REPLACEMENTS = {
    "12377cf3b91d51739a33f14a302e5f522b238593": LIVE,
    "ff25922e5c13ccfafd83bda5092910d848ebd409": SIDESTORE,
    "a731c0d5a9a6617c7b385ae493e07ffb7f81cd5d": SIDESIGN,
}

PIN_FILES = [
    "patch_app_layout.py",
    "patch_lc_certificate_observation.py",
    "patch_multitask_dock.py",
    "patch_v3_service.py",
    "patch_combined_service_startup.py",
    "patch_combined_refresh_contract.py",
    "patch_sidesign_privacy.py",
]

def main() -> None:
    for name in PIN_FILES:
        path = ROOT / name
        text = path.read_text(encoding="utf-8")
        updated = text
        for old, new in PIN_REPLACEMENTS.items():
            updated = updated.replace(old, new)
        if updated == text:
            raise SystemExit(f"no source pin found in {name}")
        path.write_text(updated, encoding="utf-8")

    service = ROOT / "patch_v3_service.py"
    text = service.read_text(encoding="utf-8")
    old = '    ) {\\n        self.session = nil\\n'
    new = '    ) async {\\n        self.session = nil\\n'
    if old in text:
        text = text.replace(old, new, 1)
    elif new not in text:
        raise SystemExit("v3 service AuthManager session-clear anchor missing")

    marker = "def headless_app_manager_ui(text):"
    legacy = "def _legacy_headless_app_manager_ui(text):"
    if marker in text and legacy not in text:
        text = text.replace(marker, legacy, 1)
        compat = '''def headless_app_manager_ui(text):
    text = headless_app_manager_persisted_error_privacy(text)
    marker = "V3_HEADLESS_APP_MANAGER_SIGNIN_REMOVED_V1"
    pairing_marker = "V3_TYPED_PAIRING_FAILURE_PROPAGATION_V1"
    if (
        "func signIn(presentingViewController: UIViewController?," not in text
        and "func deactivateApps(for appBundle: ALTApplication" not in text
    ):
        if marker not in text:
            text += "\\n// " + marker + ": current SideStore AppManager no longer owns sign-in UI.\\n"
            text += "// " + pairing_marker + ": current AppManager has no legacy sign-in UI wrapper.\\n"
        return text
    return _legacy_headless_app_manager_ui(text)


'''
        text = text.replace(legacy, compat + legacy, 1)

    service.write_text(text, encoding="utf-8")
    print(f"Builder adapted: LiveContainer={LIVE} SideStore={SIDESTORE} SideSign={SIDESIGN}")

if __name__ == "__main__":
    main()
