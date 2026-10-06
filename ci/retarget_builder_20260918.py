#!/usr/bin/env python3
from __future__ import annotations

import os
import re
from pathlib import Path

LIVE = os.environ["LIVE_CONTAINER_REF"]
SIDE = os.environ["EMBEDDED_SIDESTORE_REF"]
MINI = os.environ["MINIMUXER_REF"]
SIGN = os.environ["SIDESIGN_REF"]

PIN_MAP = {
    "12377cf3b91d51739a33f14a302e5f522b238593": LIVE,
    "ff25922e5c13ccfafd83bda5092910d848ebd409": SIDE,
    "10ffa01ecdfe4203a7ad5d7f41c0d5de03bd8abb": SIDE,
    "d57586ff506199ecfa8b78048930da821e5237de": MINI,
    "98c3c79982f813878e922ab42f9545314a700f0c": MINI,
    "20248550bbe014805460d4fa22ea69f146d338a0": MINI,
    "a731c0d5a9a6617c7b385ae493e07ffb7f81cd5d": SIGN,
    "35993d7f68950ce00d6bf1fd0fbcaa7bef51dc9c": SIGN,
}

def replace_builder_pins(root: Path) -> int:
    changed = 0
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        try:
            old = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        new = old
        for source, target in PIN_MAP.items():
            new = new.replace(source, target)
        if new != old:
            path.write_text(new, encoding="utf-8")
            changed += 1
    return changed

def patch_v3_service(path: Path) -> None:
    text = path.read_text(encoding="utf-8")

    old_signout = '''    text = replace(text, "    ) {\\n        self.session = nil\\n", "    ) {\\n"
        "        self.v3BeginIdentityTransition()\\n"
        "        defer { self.v3CompleteIdentityTransition() }\\n"
        "        self.session = nil\\n")
'''
    new_signout = '''    if "    ) async {\\n        self.session = nil\\n" in text:
        text = replace(text, "    ) async {\\n        self.session = nil\\n", "    ) async {\\n"
            "        self.v3BeginIdentityTransition()\\n"
            "        defer { self.v3CompleteIdentityTransition() }\\n"
            "        self.session = nil\\n")
    else:
        text = replace(text, "    ) {\\n        self.session = nil\\n", "    ) {\\n"
            "        self.v3BeginIdentityTransition()\\n"
            "        defer { self.v3CompleteIdentityTransition() }\\n"
            "        self.session = nil\\n")
'''
    if text.count(old_signout) != 1:
        raise SystemExit("v3 service: AuthManager signOut patch block changed")
    text = text.replace(old_signout, new_signout, 1)

    old_skip = '        skipCertificateProvisioning: Bool = false\\n'
    new_skip = '        skipCertificateProvisioning: Bool = false,\\n'
    if old_skip in text:
        text = text.replace(old_skip, new_skip, 1)

    wrapper_guard = '''    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        raise SystemExit("v3 service: AppManager UIKit sign-in wrapper changed")
'''
    wrapper_compat = '''    if start_marker not in text or end_marker not in text:
        # SideStore 2026-09-18 removed the old AppManager sign-in/deactivateApps UI wrappers.
        text += "\\n// V3_HEADLESS_APP_MANAGER_SIGNIN_REMOVED_V1: sign-in UI is upstream-owned.\\n"
        text += "// V3_HEADLESS_APP_MANAGER_DEACTIVATE_APPLIMIT_WRAPPER_REMOVED_V1: app-limit UI is upstream-owned.\\n"
        text += "// V3_TYPED_PAIRING_FAILURE_PROPAGATION_V1: typed pairing errors stay intact.\\n"
        return text
'''
    if text.count(wrapper_guard) != 1:
        raise SystemExit("v3 service: AppManager wrapper guard changed")
    text = text.replace(wrapper_guard, wrapper_compat, 1)

    presenter_guard = '''    if presenter_marker not in text:
        if text.count(presenter_block) != 1:
            raise SystemExit("v3 service: PipelineHandler presenter state changed")
        text = replace(text, presenter_block,
                       "    let isResignActive = false\\n\\n    // " +
                       presenter_marker + ": headless operations never request resign suspension.")
'''
    presenter_compat = '''    if presenter_marker not in text:
        count = text.count(presenter_block)
        if count == 1:
            text = replace(text, presenter_block,
                           "    let isResignActive = false\\n\\n    // " +
                           presenter_marker + ": headless operations never request resign suspension.")
        else:
            pattern = re.compile(
                r"(?ms)^    let isResignActive: Bool\\s*\\n"
                r"\\s*private let presenterProvider: PresenterProvider\\?\\s*\\n"
                r"\\s*init\\(\\s*\\n"
                r"\\s*isResignActive: Bool = false,\\s*\\n"
                r"\\s*presenterProvider: PresenterProvider\\? = nil\\s*\\n"
                r"\\s*\\)\\s*\\{.*?"
                r"\\s*@MainActor\\s*\\n"
                r"\\s*private var activePresenter: UIViewController\\?\\s*\\{.*?\\n\\s*\\}\\s*\\n"
            )
            text, removed = pattern.subn(
                "    let isResignActive = false\\n\\n    // " +
                presenter_marker + ": headless operations never request resign suspension.\\n",
                text, count=1)
            if removed != 1:
                raise SystemExit("v3 service: PipelineHandler presenter state changed")
'''
    if text.count(presenter_guard) != 1:
        raise SystemExit("v3 service: presenter guard changed")
    text = text.replace(presenter_guard, presenter_compat, 1)

    path.write_text(text, encoding="utf-8")

def patch_background(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        '''            r'                self.debugLog("Failed to refresh apps in background. \\(error)")', 
''',
        '''            r'                self.debugLog("Failed to refresh apps in background: \\(opError)")',
''', 1)
    text = text.replace(
        '''            r'                self.debugLog("Failed to refresh apps in background. \\(error.localizedDescription)")',
''',
        '''            r'                self.debugLog("Failed to refresh apps in background: \\(error)")',
''', 1)
    path.write_text(text, encoding="utf-8")

def patch_sidestore_integration(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    old = '''def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)
'''
    new = '''def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count == 0 and label in {
        "pinned rppairing result type",
        "pinned rppairing arguments",
        "pinned rppairing metadata",
    }:
        return text
    if count != 1:
        die(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)
'''
    if text.count(old) != 1:
        raise SystemExit("sidestore integration: replace_once helper changed")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")

def main() -> None:
    root = Path("builder")
    changed = replace_builder_pins(root)
    patch_v3_service(root / "scripts/patch_v3_service.py")
    patch_background(root / "scripts/patch_background_automation.py")
    patch_sidestore_integration(root / "scripts/patch_sidestore_integration.py")
    print(f"Retargeted {changed} builder files")
    print(f"Selected sources: LiveContainer={LIVE} SideStore={SIDE} minimuxer={MINI} SideSign={SIGN}")

if __name__ == "__main__":
    main()
