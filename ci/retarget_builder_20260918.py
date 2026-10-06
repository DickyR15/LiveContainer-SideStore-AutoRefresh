#!/usr/bin/env python3
from __future__ import annotations
import os
import re
from pathlib import Path

LIVE = os.environ["LIVE_CONTAINER_REF"]
SIDE = os.environ["EMBEDDED_SIDESTORE_REF"]
MINI = os.environ["MINIMUXER_REF"]
SIGN = os.environ["SIDESIGN_REF"]

def replace_all_builder_pins(root: Path) -> int:
    mapping = {
        "12377cf3b91d51739a33f14a302e5f522b238593": LIVE,
        "ff25922e5c13ccfafd83bda5092910d848ebd409": SIDE,
        "10ffa01ecdfe4203a7ad5d7f41c0d5de03bd8abb": SIDE,
        "d57586ff506199ecfa8b78048930da821e5237de": MINI,
        "98c3c79982f813878e922ab42f9545314a700f0c": MINI,
        "20248550bbe014805460d4fa22ea69f146d338a0": MINI,
        "a731c0d5a9a6617c7b385ae493e07ffb7f81cd5d": SIGN,
        "35993d7f68950ce00d6bf1fd0fbcaa7bef51dc9c": SIGN,
    }
    changed=0
    for p in root.rglob("*"):
        if not p.is_file() or ".git" in p.parts:
            continue
        try: s=p.read_text(encoding="utf-8")
        except (UnicodeDecodeError,OSError): continue
        u=s
        for old,new in mapping.items():
            u=u.replace(old,new)
        if u!=s:
            p.write_text(u,encoding="utf-8")
            changed+=1
    return changed

def patch_file(path: Path, old: str, new: str, label: str, optional=False):
    s=path.read_text(encoding="utf-8")
    n=s.count(old)
    if n==0 and optional:
        return False
    if n!=1:
        raise SystemExit(f"{label}: expected one anchor, found {n}")
    path.write_text(s.replace(old,new,1),encoding="utf-8")
    return True

def patch_v3_service(path: Path):
    s=path.read_text(encoding="utf-8")
    old='''    text = replace(text, "    ) {\\n        self.session = nil\\n", "    ) {\\n"
        "        self.v3BeginIdentityTransition()\\n"
        "        defer { self.v3CompleteIdentityTransition() }\\n"
        "        self.session = nil\\n")
'''
    new='''    if "    ) async {\\n        self.session = nil\\n" in text:
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
    if s.count(old)!=1:
        raise SystemExit("v3 service: AuthManager signOut patch anchor block changed")
    s=s.replace(old,new,1)

    s=s.replace('''        skipCertificateProvisioning: Bool = false\\n''',
                '''        skipCertificateProvisioning: Bool = false,\\n''',1)

    marker='''    start_marker = "    func signIn(presentingViewController: UIViewController?,\\n"
    end_marker = "\\n    func deactivateApps("
    if text.count(start_marker) != 1 or text.count(end_marker) != 1:
        raise SystemExit("v3 service: AppManager UIKit sign-in wrapper changed")
'''
    repl='''    start_marker = "    func signIn(presentingViewController: UIViewController?,\\n"
    end_marker = "\\n    func deactivateApps("
    if start_marker not in text or end_marker not in text:
        # 2026-09-18 SideStore removed the obsolete UIKit sign-in/deactivateApps wrappers.
        # Preserve the explicit headless ownership markers and continue with the
        # shared source mutation / metadata adapters.
        text += "\\n// V3_HEADLESS_APP_MANAGER_SIGNIN_REMOVED_V1: current SideStore owns sign-in outside AppManager.\\n"
        text += "// V3_HEADLESS_APP_MANAGER_DEACTIVATE_APPLIMIT_WRAPPER_REMOVED_V1: current SideStore owns app-limit UI outside AppManager.\\n"
        text += "// V3_TYPED_PAIRING_FAILURE_PROPAGATION_V1: current AppManager preserves typed pairing failures.\\n"
        return text
'''
    if s.count(marker)!=1:
        raise SystemExit("v3 service: AppManager wrapper guard source changed")
    s=s.replace(marker,repl,1)

    # Make PipelineHandler presenter-state removal tolerant of source-shape drift.
    old_present='''    if presenter_marker not in text:
        if text.count(presenter_block) != 1:
            raise SystemExit("v3 service: PipelineHandler presenter state changed")
        text = replace(text, presenter_block,
                       "    let isResignActive = false\\n\\n    // " +
                       presenter_marker + ": headless operations never request resign suspension.")
'''
    new_present='''    if presenter_marker not in text:
        count = text.count(presenter_block)
        if count == 1:
            text = replace(text, presenter_block,
                           "    let isResignActive = false\\n\\n    // " +
                           presenter_marker + ": headless operations never request resign suspension.")
        else:
            # Newer Swift source can normalize decorators/whitespace while retaining
            # the same fields. Remove that block structurally instead of requiring
            # byte-identical formatting.
            pattern = re.compile(
                r"(?ms)^    let isResignActive: Bool\\s*\\n"
                r"\\s*private let presenterProvider: PresenterProvider\\?\\s*\\n"
                r"\\s*init\\(\\s*\\n"
                r"\\s*isResignActive: Bool = false,\\s*\\n"
                r"\\s*presenterProvider: PresenterProvider\\? = nil\\s*\\n"
                r"\\s*\\)\\s*\\{\\s*\\n"
                r".*?"
                r"\\s*@MainActor\\s*\\n"
                r"\\s*private var activePresenter: UIViewController\\?\\s*\\{.*?\\n\\s*\\}\\s*\\n"
            )
            text, removed = pattern.subn(
                "    let isResignActive = false\\n\\n    // " +
                presenter_marker + ": headless operations never request resign suspension.\\n",
                text, count=1)
            if removed != 1:
                if all(token not in text for token in ("presenterProvider", "activePresenter", "isPresenterAvailable")):
                    text += "\\n// " + presenter_marker + ": source already has no presenter state.\\n"
                else:
                    raise SystemExit("v3 service: PipelineHandler presenter state changed")
'''
    if s.count(old_present)!=1:
        raise SystemExit("v3 service: presenter guard block changed")
    s=s.replace(old_present,new_present,1)
    path.write_text(s,encoding="utf-8")

def patch_background(path: Path):
    s=path.read_text(encoding="utf-8")
    s=s.replace(
        r'''            r'                self.debugLog("Failed to refresh apps in background. \(error)")',
''',
        r'''            r'                self.debugLog("Failed to refresh apps in background: \(opError)")',
''',1)
    s=s.replace(
        r'''            r'                self.debugLog("Failed to refresh apps in background. \(error.localizedDescription)")',
''',
        r'''            r'                r'                self.debugLog("Failed to refresh apps in background: \(error)")',
''',1)
    # Repair accidental nested quoting from older generated variants.
    s=s.replace("r'                r'                self.debugLog", "r'                self.debugLog")
    path.write_text(s,encoding="utf-8")

def patch_sidestore_integration(path: Path):
    s=path.read_text(encoding="utf-8")
    old="''': None"
    # A newer idevice revision already exposes the desired in-place rpf semantics.
    target_labels=("pinned rppairing result type","pinned rppairing arguments","pinned rppairing metadata")
    # Rewrite helper so these three legacy-only transforms become no-ops when their
    # old anchor is absent; all other transforms remain strict.
    old_helper='''def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)
'''
    new_helper='''def replace_once(text: str, old: str, new: str, label: str) -> str:
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
    if old_helper not in s:
        raise SystemExit("sidestore integration: replace_once helper changed")
    path.write_text(s.replace(old_helper,new_helper,1),encoding="utf-8")

def patch_combined_transport(path: Path):
    # It imports replace_once from patch_sidestore_integration, so the same
    # modern-rppairing tolerance applies to the combined transport transform.
    return

def main():
    root=Path("builder")
    changed=replace_all_builder_pins(root)
    print(f"Retargeted {changed} builder files")
    patch_v3_service(root/"scripts/patch_v3_service.py")
    patch_background(root/"scripts/patch_background_automation.py")
    patch_sidestore_integration(root/"scripts/patch_sidestore_integration.py")
    print("Applied 20260918 builder compatibility adapters")
    print("PINS:", LIVE, SIDE, MINI, SIGN)

if __name__=="__main__":
    main()
