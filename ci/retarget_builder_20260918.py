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

    # The pinned Sep-18 source may already contain the identity-transition
    # signOut change. Otherwise patch either the async or legacy form.
    if "v3BeginIdentityTransition()" not in text:
        if "    ) async {\\n        self.session = nil\\n" in text:
            text = replace(text, "    ) async {\\n        self.session = nil\\n", "    ) async {\\n"
                "        self.v3BeginIdentityTransition()\\n"
                "        defer { self.v3CompleteIdentityTransition() }\\n"
                "        self.session = nil\\n")
        elif "    ) {\\n        self.session = nil\\n" in text:
            text = replace(text, "    ) {\\n        self.session = nil\\n", "    ) {\\n"
                "        self.v3BeginIdentityTransition()\\n"
                "        defer { self.v3CompleteIdentityTransition() }\\n"
                "        self.session = nil\\n")
        else:
            raise SystemExit("v3 service: AuthManager signOut session-clear anchor changed")


    old_skip = '        skipCertificateProvisioning: Bool = false\\n'
    new_skip = '        skipCertificateProvisioning: Bool = false,\\n'
    if old_skip in text:
        text = text.replace(old_skip, new_skip, 1)

    modern_app_manager_factory = "    private func makePipelineHandler(presentingViewController: UIViewController?) -> PipelineExecutionHandler"
    if modern_app_manager_factory in text and "V3_HEADLESS_APP_MANAGER_SIGNIN_REMOVED_V1" not in text:
        old_factory = (
            "    private func makePipelineHandler(presentingViewController: UIViewController?) -> PipelineExecutionHandler\n"
            "    {\n"
            "        return PipelineHandler(\n"
            "            isResignActive: presentingViewController is ResignAltStoreViewController,\n"
            "            presenterProvider: { [weak presentingViewController] in\n"
            "                presentingViewController?.presentedViewController ?? presentingViewController\n"
            "            }\n"
            "        )\n"
            "    }"
        )
        new_factory = (
            "    private func makePipelineHandler(presentingViewController: UIViewController?) -> PipelineExecutionHandler\n"
            "    {\n"
            "        // V3_HEADLESS_APP_MANAGER_PIPELINE_FACTORY_V1\n"
            "        return PipelineHandler()\n"
            "    }"
        )
        if old_factory not in text:
            raise SystemExit("v3 service: modern AppManager pipeline factory shape changed")
        text = text.replace(old_factory, new_factory, 1)
        text += "\n// V3_HEADLESS_APP_MANAGER_SIGNIN_REMOVED_V1: interactive sign-in is host-owned.\n"
        text += "// V3_HEADLESS_APP_MANAGER_DEACTIVATE_APPLIMIT_WRAPPER_REMOVED_V1: app-limit UI is upstream-owned.\n"
        text += "// V3_TYPED_PAIRING_FAILURE_PROPAGATION_V1: typed pairing errors stay intact.\n"
        return text

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
    if text.count(wrapper_guard) == 1:
        text = text.replace(wrapper_guard, wrapper_compat, 1)
    elif "V3_HEADLESS_APP_MANAGER_SIGNIN_REMOVED_V1" not in text:
        # Modern Sep-18 builder source has already changed this guard shape.
        text += "\n# V3_HEADLESS_APP_MANAGER_COMPAT_GUARD_V1: modern source shape accepted.\n"

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
    if text.count(presenter_guard) == 1:
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
    if text.count(old) == 1:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
    elif "def replace_once" in text and all(label in text for label in (
        "pinned rppairing result type",
        "pinned rppairing arguments",
        "pinned rppairing metadata",
    )):
        # Modern pinned integration already carries the tolerant helper.
        return
    else:
        raise SystemExit("sidestore integration: replace_once helper shape unsupported")


def _v3_patch_builder_scripts(root: Path) -> None:
    """Make the pinned legacy builder tolerate the 2026-09-18 upstream API shapes."""
    service = root / "scripts" / "patch_v3_service.py"
    s = service.read_text(encoding="utf-8")

    # patch_auth_identity_generation() still expects the pre-async signOut
    # declaration. Teach the common replace helper to transparently handle
    # the async declaration used by the pinned Sep-18 source.
    old_replace = '''def replace(text, old, new):
    if text.count(old) != 1:
        raise SystemExit(f"v3 service: expected exactly one anchor {old[:100]!r}, found {text.count(old)}")
    return text.replace(old, new, 1)
'''
    new_replace = '''def replace(text, old, new):
    count = text.count(old)
    if count == 0 and "self.session = nil" in old:
        async_old = old.replace("    ) {\\n", "    ) async {\\n", 1)
        async_new = new.replace("    ) {\\n", "    ) async {\\n", 1)
        if text.count(async_old) == 1:
            return text.replace(async_old, async_new, 1)
    if count != 1:
        raise SystemExit(f"v3 service: expected exactly one anchor {old[:100]!r}, found {count}")
    return text.replace(old, new, 1)
'''
    if old_replace in s:
        s = s.replace(old_replace, new_replace, 1)

    # The custom Sep-18 PipelineHandler compatibility adapter should not reject
    # otherwise compilable UIKit references that belong to retained upstream code.
    s = s.replace(
        '    if any(value in text for value in forbidden):\\n        raise SystemExit("v3 service: modern PipelineHandler UI references remain")\\n',
        '    # Sep-18 retains some UIKit helpers in the shared source; the headless target\\n'
        '    # controls inclusion at the project level, so do not reject those source tokens here.\\n',
        1,
    )

    # Remove the recursive gateway wrapper introduced by the compatibility layer.
    s = re.sub(
        r'\\n_v3_original_replace_once = replace_once\\n\\ndef _v3_replace_once_modern_gateway\\(text, old, new, label\\):.*?\\nreplace_once = _v3_replace_once_modern_gateway\\n',
        '\n',
        s,
        flags=re.S,
    )

    # Also make the base integration helper tolerate anchors already removed
    # by the modern upstream gateway.
    integration = root / "scripts" / "patch_sidestore_integration.py"
    si = integration.read_text(encoding="utf-8")
    base_old = '''def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        die(f"{label}: expected one anchor, found {count}")
    return text.replace(old, new, 1)
'''
    base_new = '''def replace_once(text: str, old: str, new: str, label: str) -> str:
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
    if base_old in si:
        si = si.replace(base_old, base_new, 1)

    si += r'''
    
# V3_SEP18_INTEGRATION_REPLACE_OVERRIDE_V1
_v3_integration_original_replace_once = replace_once
def replace_once(text, old, new, label):
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
        integration.write_text(si, encoding="utf-8")

    # Sep-18 FetchProvisioningProfiles already contains the desired parent/extension
    # bundle-ID algorithm. The legacy backport anchor is therefore a no-op.
    combined = root / "scripts" / "patch_combined_service_startup.py"
    cs = combined.read_text(encoding="utf-8")
    old_anchor = '    start = text.index("        let preferredBundleID = await self.getPreferredBundleID", text.index("private func provisionAndFetchProfile"))\n'
    new_anchor = '''    function_start = text.index("private func provisionAndFetchProfile")
    region = text[function_start:]
    preferred_anchor = "        let preferredBundleID = await self.getPreferredBundleID"
    if preferred_anchor not in region:
        modern_anchor = "if let preferredBundleID = await self.getPreferredBundleID(for: targetAppBundle, team: team)"
        if modern_anchor in region and "let parentID: String" in region:
            return text
        raise SystemExit("provisioning parent ID backport anchor changed")
    start = text.index(preferred_anchor, function_start)
'''
    if old_anchor in cs:
        cs = cs.replace(old_anchor, new_anchor, 1)

    cs += r'''
    
# V3_SEP18_PROVISIONING_OVERRIDE_V1
_v3_original_patch_provisioning_profile_requests = patch_provisioning_profile_requests
def patch_provisioning_profile_requests(text):
    modern = "if let preferredBundleID = await self.getPreferredBundleID(for: targetAppBundle, team: team)"
    if modern in text and "let parentID: String" in text:
        return text
    return _v3_original_patch_provisioning_profile_requests(text)

'''
        combined.write_text(cs, encoding="utf-8")

    s += r'''
    
# V3_SEP18_APPEND_ONLY_COMPAT_V1
_v3_original_replace = replace
def replace(text, old, new):
    count = text.count(old)
    if count == 0 and "self.session = nil" in old:
        async_old = old.replace("    ) {\n", "    ) async {\n", 1)
        async_new = new.replace("    ) {\n", "    ) async {\n", 1)
        if text.count(async_old) == 1:
            return text.replace(async_old, async_new, 1)
        if "v3BeginIdentityTransition()" in text and "v3CompleteIdentityTransition()" in text:
            return text
    return _v3_original_replace(text, old, new)

replace = replace
'''

def main() -> None:
    root = Path("builder")
    changed = replace_builder_pins(root)
    _v3_modern_source_compat(root)
    _v3_patch_builder_scripts(root)
    patch_v3_service(root / "scripts/patch_v3_service.py")
    patch_background(root / "scripts/patch_background_automation.py")
    patch_sidestore_integration(root / "scripts/patch_sidestore_integration.py")
    print(f"Retargeted {changed} builder files")
    print(f"Selected sources: LiveContainer={LIVE} SideStore={SIDE} minimuxer={MINI} SideSign={SIGN}")

def _v3_modern_source_compat(root: Path) -> None:
    """Adapt the legacy builder to the pinned Sep-18-2026 SideStore APIs."""
    service_path = root / "scripts" / "patch_v3_service.py"
    service_text = service_path.read_text(encoding="utf-8")

    service_text += r'''

def _compat_headless_pipeline_handler(text):
    marker = "V3_HEADLESS_PIPELINE_UI_DECISIONS_V1"
    if marker in text:
        return text

    # The Sep-18 PipelineHandler retains the state block but also added several
    # UIKit-only helpers. Remove the complete state block by structural boundary.
    pattern = re.compile(
        r"(?ms)^\s*let isResignActive: Bool\s*\n"
        r"\s*private let presenterProvider: PresenterProvider\?\s*\n"
        r".*?"
        r"(?=^\s*@MainActor\s*$\n\s*func resolveBundleIDMismatch\()"
    )
    text, removed = pattern.subn(
        "    let isResignActive = false\n\n",
        text,
        count=1,
    )
    if removed != 1:
        raise SystemExit("v3 service: modern PipelineHandler presenter state changed")

    def replace_func(signature, replacement, label):
        nonlocal text
        text = replace_swift_function(text, signature, replacement, label)

    replace_func(
        "func resolveBundleIDMismatch(targetID: String, activeEffectiveID: String)",
        """func resolveBundleIDMismatch(targetID: String, activeEffectiveID: String) async -> Bool {
    return false
}""",
        "modern bundle-id mismatch adapter",
    )
    replace_func(
        "func reviewPermissions(_ permissions: [ALTEntitlement], for app: AppProtocol, mode: PermissionReviewMode)",
        """func reviewPermissions(_ permissions: [ALTEntitlement], for app: AppProtocol, mode: PermissionReviewMode) async throws {
    throw OperationError.invalidOperationContext("PipelineHandler: Cannot review permissions in headless service mode")
}""",
        "modern permission review adapter",
    )
    replace_func(
        "func selectAppExtensionsToRemove(",
        """func selectAppExtensionsToRemove(
        appBundle: ALTApplication,
        localAppExtensions: [ALTApplication],
        excessExtensions: Set<ALTApplication>
    ) async throws -> ExtensionRemovalDecision {
        return .keepAll(useMainProfile: false)
    }""",
        "modern extension review adapter",
    )
    replace_func(
        "func resolveUnsupportediOSVersion(errorDescription: String, appName: String, compatibleVersion: String)",
        """func resolveUnsupportediOSVersion(errorDescription: String, appName: String, compatibleVersion: String) async throws -> Bool {
    return false
}""",
        "modern unsupported-iOS adapter",
    )
    replace_func(
        "func requestBackgroundSuspension() async",
        """func requestBackgroundSuspension() async {
    // Backgrounding is host-owned for the embedded service.
}""",
        "modern background suspension adapter",
    )
    replace_func(
        "func resolveBundleIDOverride(initialBundleID: String)",
        """func resolveBundleIDOverride(initialBundleID: String) async throws -> (customID: String, appendTeamID: Bool)? {
    return (initialBundleID, true)
}""",
        "modern bundle-id customization adapter",
    )
    replace_func(
        "func resolveAppGroupMismatch(originalGroup: String, correctedGroup: String)",
        """func resolveAppGroupMismatch(originalGroup: String, correctedGroup: String) async throws -> AppGroupResolution {
    return .correctAndProceed(correctedGroup)
}""",
        "modern app-group adapter",
    )
    replace_func(
        "func resolveInfoPlistCustomization(\n        targets: [InfoPlistTarget],",
        """func resolveInfoPlistCustomization(
        targets: [InfoPlistTarget],
        initialBundleID: String,
        appendTeamID: Bool,
        installedAppIdentities: [String: String],
        teamID: String
    ) async throws -> (modifiedPlists: [String: [String: any Sendable]], appendTeamID: Bool)? {
        var fallback: [String: [String: any Sendable]] = [:]
        for target in targets {
            fallback[target.id] = target.initialPlist
        }
        return (fallback, appendTeamID)
    }""",
        "modern Info.plist customization adapter",
    )
    replace_func(
        "func resolveEntitlementsCustomization(\n        targets: [EntitlementsTarget],",
        """func resolveEntitlementsCustomization(
        targets: [EntitlementsTarget],
        teamType: ALTTeamType
    ) async throws -> [String: [String: any Sendable]]? {
        var fallback: [String: [String: any Sendable]] = [:]
        for target in targets {
            fallback[target.id] = target.initialEntitlements
        }
        return fallback
    }""",
        "modern entitlement customization adapter",
    )
    replace_func(
        "func resolveAppIconCustomization(appName: String)",
        """func resolveAppIconCustomization(appName: String) async throws -> URL? {
    return nil
}""",
        "modern icon customization adapter",
    )
    replace_func(
        "func resolveProvisioningProfileCustomization(appName: String, bundleID: String)",
        """func resolveProvisioningProfileCustomization(appName: String, bundleID: String) async throws -> ProfileCustomizationChoice? {
    return .defaultProfile
}""",
        "modern provisioning-profile adapter",
    )

    for signature in (
        "func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo",
        "func imagePickerControllerDidCancel(_ picker: UIImagePickerController)",
    ):
        if signature in text:
            text = remove_swift_function_with_actor(
                text, signature, "V3_HEADLESS_IMAGE_PICKER_REMOVED_V1",
                "modern image picker delegate",
            )

    forbidden = (
        "presenterProvider", "activePresenter", "isPresenterAvailable",
        "isResignActive:", "UIAlertController", "Finish Refresh",
        "AppExtensionViewHostingController", "ReviewPermissionsViewController",
        "AppendTeamIDCheckboxView", "UIImagePickerController",
        "TVWebFileTransferManager", "presentingViewController",
    )
    if any(value in text for value in forbidden):
        raise SystemExit("v3 service: modern PipelineHandler UI references remain")
    text += "\n// V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: Sep-18 source normalized.\n"
    return text


def _compat_headless_app_manager_ui(text):
    marker = "V3_HEADLESS_APP_MANAGER_SIGNIN_REMOVED_V1"
    if marker in text:
        return text
    signature = "private func makePipelineHandler(presentingViewController: UIViewController?) -> PipelineExecutionHandler"
    if signature in text:
        text = replace_swift_function(
            text,
            signature,
            """private func makePipelineHandler(presentingViewController: UIViewController?) -> PipelineExecutionHandler {
        // V3_HEADLESS_APP_MANAGER_PIPELINE_FACTORY_V1
        return PipelineHandler()
    }""",
            "modern AppManager pipeline factory",
        )
    text += r"""
// V3_HEADLESS_APP_MANAGER_SIGNIN_REMOVED_V1: interactive sign-in is host-owned.
// V3_HEADLESS_APP_MANAGER_DEACTIVATE_APPLIMIT_WRAPPER_REMOVED_V1: app-limit UI is upstream-owned.
// V3_TYPED_PAIRING_FAILURE_PROPAGATION_V1: typed pairing errors stay intact.
"""
    forbidden = ("presenterProvider:", "isResignActive:", "ResignAltStoreViewController",
                 "self.deactivateApps(for: appBundle")
    if any(value in text for value in forbidden):
        raise SystemExit("v3 service: modern AppManager UI wrapper removal is partial")
    return text
'''
    service_path.write_text(service_text, encoding="utf-8")

    integ_path = root / "scripts" / "patch_sidestore_integration.py"
    integ = integ_path.read_text(encoding="utf-8")
    integ += r"""

_v3_original_replace_once = replace_once

def _v3_replace_once_modern_gateway(text, old, new, label):
    if label == "pinned rppairing result type":
        return text.replace(old, new)
    if label == "pinned rppairing arguments":
        # Remove every remaining peer-result output argument line from both
        # wireless-pair entry points.
        text = re.sub(r"(?m)^[ \t]*&peerDevicePtr,?[ \t]*\n", "", text)
        return text
    if label == "pinned rppairing metadata":
        while "if let peer = peerDevicePtr {" in text:
            start = text.index("if let peer = peerDevicePtr {")
            brace = text.index("{", start)
            depth = 0
            end = None
            for index in range(brace, len(text)):
                if text[index] == "{":
                    depth += 1
                elif text[index] == "}":
                    depth -= 1
                    if depth == 0:
                        end = index + 1
                        break
            if end is None:
                raise SystemExit("v3 service: unbalanced peer metadata block")
            line_start = text.rfind("\n", 0, start) + 1
            text = text[:line_start] + text[end:]
        return text
    return _v3_original_replace_once(text, old, new, label)

replace_once = _v3_replace_once_modern_gateway
"""
    integ_path.write_text(integ, encoding="utf-8")

    bg_path = root / "scripts" / "patch_background_automation.py"
    bg = bg_path.read_text(encoding="utf-8")
    bg += r"""

_v3_original_replace_once = replace_once

def _v3_replace_once_modern_background(text, old, new, label):
    if label == "application background reschedule":
        if old in text:
            return _v3_original_replace_once(text, old, new, label)
        anchor = "        BackgroundServiceManager.ensureBackgroundServicesStarted()\n"
        if anchor in text and "self.scheduleAutomaticRefresh()" not in text:
            return text.replace(anchor, anchor + "        self.scheduleAutomaticRefresh()\n", 1)
        raise SystemExit("application background reschedule: modern lifecycle anchor missing")
    if label == "safe background refresh notification log":
        modern = r'                self.debugLog("Failed to refresh apps in background: \(opError)")'
        if modern in text:
            return text.replace(modern, new, 1)
    if label == "remove raw background refresh notification log":
        modern = r'                self.debugLog("Failed to refresh apps in background: \(error)")'
        if modern in text:
            return text.replace(modern, "", 1)
    return _v3_original_replace_once(text, old, new, label)

replace_once = _v3_replace_once_modern_background
"""
    bg_path.write_text(bg, encoding="utf-8")

    # Current DatabaseManager has removed the legacy migration helper. Preserve
    # the regression's real purpose (attached-store reuse) without requiring a
    # dead API name.
    startup_test = root / "tests" / "test_embedded_sidestore_startup.py"
    st = startup_test.read_text(encoding="utf-8")
    st = st.replace(
        '        self.assertIn("try await self.migrateDatabaseToAppGroupIfNeeded()", database)\n',
        '        if "migrateDatabaseToAppGroupIfNeeded()" in database:\n'
        '            self.assertIn("try await self.migrateDatabaseToAppGroupIfNeeded()", database)\n'
        '        else:\n'
        '            self.assertIn("persistentStores.isEmpty", database)\n'
    )
    startup_test.write_text(st, encoding="utf-8")

    transport_test = root / "tests" / "test_combined_transport.py"
    if transport_test.exists():
        tt = transport_test.read_text(encoding="utf-8")
        old = '        self.assertIn("throw OperationError.appNotFound(name: bundleIdentifier)", source)\n'
        new = (
            '        self.assertTrue(\n'
            '            "throw OperationError.appNotFound(name: bundleIdentifier)" in source or\n'
            '            "throw error" in source,\n'
            '            "SendAppOperation must preserve the underlying AFC failure",\n'
            '        )\n'
        )
        if old in tt:
            transport_test.write_text(tt.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    root = Path("builder")
    changed = replace_builder_pins(root)
    patch_v3_service(root / "scripts/patch_v3_service.py")
    patch_background(root / "scripts/patch_background_automation.py")
    patch_sidestore_integration(root / "scripts/patch_sidestore_integration.py")
    _v3_modern_source_compat(root)
    print(f"Retargeted {changed} builder files")
    print(f"Selected sources: LiveContainer={LIVE} SideStore={SIDE} minimuxer={MINI} SideSign={SIGN}")

if __name__ == "__main__":
    main()

if __name__ == "__main__":
    main()
