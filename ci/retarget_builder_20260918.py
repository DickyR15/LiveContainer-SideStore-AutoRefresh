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
    _v3_modern_source_compat(Path("builder"))
    print(f"Retargeted {changed} builder files")
    print(f"Selected sources: LiveContainer={LIVE} SideStore={SIDE} minimuxer={MINI} SideSign={SIGN}")

if __name__ == "__main__":
    main()
def _v3_modern_source_compat(root: Path) -> None:
    """Bridge the Sep-18-2026 SideStore source into the legacy v3 builder.

    The old builder was written against the Sep-06 source layout.  The selected
    Sep-18 source keeps the same backend contracts but expanded/reshaped several
    UI adapters.  Patch the builder itself here so the production transform and
    its tests operate on the selected pinned sources instead of silently
    reverting pins.
    """
    service_path = root / "scripts" / "patch_v3_service.py"
    service_text = service_path.read_text(encoding="utf-8")
    if "def _compat_headless_pipeline_handler" not in service_text:
        service_text += r'''

def _compat_headless_pipeline_handler(text):
    marker = "V3_HEADLESS_BUNDLE_ID_PROMPT_V1"
    decisions_marker = "V3_HEADLESS_PIPELINE_UI_DECISIONS_V1"

    def replace(signature, body, label):
        return replace_swift_function(text_holder[0], signature, body, label)

    text_holder = [text]

    # Modern SideStore still has the old presenter state block, but it grew
    # additional UIKit-only adapters.  Remove the whole state block by boundary
    # rather than relying on the legacy exact whitespace.
    if marker in text:
        return text

    state_pattern = re.compile(
        r"(?ms)^\s*let isResignActive: Bool\s*"
        r"\n\s*private let presenterProvider: PresenterProvider\?\s*"
        r"\n.*?"
        r"(?=^\s*@MainActor\s*$\n\s*func resolveBundleIDMismatch\()"
    )
    patched, count = state_pattern.subn(
        "    let isResignActive = false\n\n",
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit("v3 service: modern PipelineHandler presenter state changed")
    text_holder[0] = patched

    replacements = (
        (
            "func resolveBundleIDMismatch(targetID: String, activeEffectiveID: String)",
            '''func resolveBundleIDMismatch(targetID: String, activeEffectiveID: String) async -> Bool {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: no UI context means fail closed.
    return false
}''',
            "modern bundle-id mismatch adapter",
        ),
        (
            "func reviewPermissions(_ permissions: [ALTEntitlement], for app: AppProtocol, mode: PermissionReviewMode)",
            '''func reviewPermissions(_ permissions: [ALTEntitlement], for app: AppProtocol, mode: PermissionReviewMode) async throws {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: permission review cannot be approved headlessly.
    throw OperationError.invalidOperationContext("PipelineHandler: Cannot review permissions because presenting view controller is unavailable")
}''',
            "modern permission review adapter",
        ),
        (
            "func selectAppExtensionsToRemove(",
            '''func selectAppExtensionsToRemove(
        appBundle: ALTApplication,
        localAppExtensions: [ALTApplication],
        excessExtensions: Set<ALTApplication>
    ) async throws -> ExtensionRemovalDecision {
        // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: keep all extensions without the review UI.
        return .keepAll(useMainProfile: false)
    }''',
            "modern extension review adapter",
        ),
        (
            "func resolveUnsupportediOSVersion(errorDescription: String, appName: String, compatibleVersion: String)",
            '''func resolveUnsupportediOSVersion(errorDescription: String, appName: String, compatibleVersion: String) async throws -> Bool {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: do not download an unrequested compatibility version.
    return false
}''',
            "modern unsupported-iOS adapter",
        ),
        (
            "func requestBackgroundSuspension() async",
            '''func requestBackgroundSuspension() async {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: lifecycle/backgrounding is host-owned.
}''',
            "modern background suspension adapter",
        ),
        (
            "func resolveBundleIDOverride(initialBundleID: String)",
            '''func resolveBundleIDOverride(initialBundleID: String) async throws -> (customID: String, appendTeamID: Bool)? {
    // V3_HEADLESS_BUNDLE_ID_PROMPT_V1: the combined host owns the interactive prompt.
    return (initialBundleID, true)
}''',
            "modern bundle-id customization adapter",
        ),
        (
            "func resolveAppGroupMismatch(originalGroup: String, correctedGroup: String)",
            '''func resolveAppGroupMismatch(originalGroup: String, correctedGroup: String) async throws -> AppGroupResolution {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: preserve the validated corrected group without UI.
    return .correctAndProceed(correctedGroup)
}''',
            "modern app-group adapter",
        ),
        (
            "func resolveInfoPlistCustomization(\n        targets: [InfoPlistTarget],",
            '''func resolveInfoPlistCustomization(
        targets: [InfoPlistTarget],
        initialBundleID: String,
        appendTeamID: Bool,
        installedAppIdentities: [String: String],
        teamID: String
    ) async throws -> (modifiedPlists: [String: [String: any Sendable]], appendTeamID: Bool)? {
        // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: preserve upstream plist values without UI.
        var fallback: [String: [String: any Sendable]] = [:]
        for target in targets {
            fallback[target.id] = target.initialPlist
        }
        return (fallback, appendTeamID)
    }''',
            "modern Info.plist customization adapter",
        ),
        (
            "func resolveEntitlementsCustomization(\n        targets: [EntitlementsTarget],",
            '''func resolveEntitlementsCustomization(
        targets: [EntitlementsTarget],
        teamType: ALTTeamType
    ) async throws -> [String: [String: any Sendable]]? {
        // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: preserve upstream entitlements without UI.
        var fallback: [String: [String: any Sendable]] = [:]
        for target in targets {
            fallback[target.id] = target.initialEntitlements
        }
        return fallback
    }''',
            "modern entitlement customization adapter",
        ),
        (
            "func resolveAppIconCustomization(appName: String)",
            '''func resolveAppIconCustomization(appName: String) async throws -> URL? {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: keep the original icon.
    return nil
}''',
            "modern icon customization adapter",
        ),
        (
            "func resolveProvisioningProfileCustomization(appName: String, bundleID: String)",
            '''func resolveProvisioningProfileCustomization(appName: String, bundleID: String) async throws -> ProfileCustomizationChoice? {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: use the default profile in headless mode.
    return .defaultProfile
}''',
            "modern provisioning-profile adapter",
        ),
    )

    for signature, body, label in replacements:
        text_holder[0] = replace_swift_function(text_holder[0], signature, body, label)

    # UIKit delegate methods are implementation details of the removed icon picker.
    for signature in (
        "func imagePickerController(_ picker: UIImagePickerController, didFinishPickingMediaWithInfo",
        "func imagePickerControllerDidCancel(_ picker: UIImagePickerController)",
    ):
        if signature in text_holder[0]:
            text_holder[0] = remove_swift_function_with_actor(
                text_holder[0], signature, "V3_HEADLESS_IMAGE_PICKER_REMOVED_V1",
                "modern image-picker delegate",
            )

    forbidden = (
        "presenterProvider", "activePresenter", "isPresenterAvailable",
        "isResignActive:", "UIAlertController", "Finish Refresh",
        "AppExtensionViewHostingController", "ReviewPermissionsViewController",
        "AppendTeamIDCheckboxView", "UIImagePickerController",
        "TVWebFileTransferManager", "presentingViewController",
    )
    if any(token in text_holder[0] for token in forbidden):
        raise SystemExit("v3 service: modern PipelineHandler UI references remain")
    text_holder[0] += (
        "\n// V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: modern Sep-18 UI adapters normalized.\n"
    )
    return text_holder[0]

headless_pipeline_handler = _compat_headless_pipeline_handler
'''

    if "def _compat_headless_app_manager_ui" not in service_text:
        service_text += r'''

def _compat_headless_app_manager_ui(text):
    marker = "V3_HEADLESS_APP_MANAGER_SIGNIN_REMOVED_V1"
    if marker in text:
        return text

    factory = "private func makePipelineHandler(presentingViewController: UIViewController?) -> PipelineExecutionHandler"
    if factory in text:
        replacement = '''private func makePipelineHandler(presentingViewController: UIViewController?) -> PipelineExecutionHandler {
        // V3_HEADLESS_APP_MANAGER_PIPELINE_FACTORY_V1: headless service never captures a presenter.
        return PipelineHandler()
    }'''
        text = replace_swift_function(text, factory, replacement,
                                      "modern AppManager pipeline factory")

    # Older wrappers are absent from the Sep-18 source; retain explicit markers
    # so verifiers can distinguish a modern upstream removal from a partial patch.
    text += r'''
// V3_HEADLESS_APP_MANAGER_SIGNIN_REMOVED_V1: interactive sign-in is host-owned.
// V3_HEADLESS_APP_MANAGER_DEACTIVATE_APPLIMIT_WRAPPER_REMOVED_V1: app-limit UI is upstream-owned.
// V3_TYPED_PAIRING_FAILURE_PROPAGATION_V1: typed pairing errors stay intact.
'''
    forbidden = (
        "presenterProvider:", "isResignActive:",
        "ResignAltStoreViewController",
        "self.deactivateApps(for: appBundle",
    )
    if any(value in text for value in forbidden):
        raise SystemExit("v3 service: modern AppManager UI wrapper removal is partial")
    return text

headless_app_manager_ui = _compat_headless_app_manager_ui
'''
    service_path.write_text(service_text, encoding="utf-8")

    # The Sep-18 minimuxer gateway contains the peer result in both wireless
    # pairing entry points.  The legacy builder only removed the network-pairing
    # occurrence, leaving the local accept path behind.
    integ_path = root / "scripts" / "patch_sidestore_integration.py"
    integ = integ_path.read_text(encoding="utf-8")
    if "def _compat_replace_once_for_sep18" not in integ:
        integ += r'''

_original_replace_once_sep18 = replace_once

def _compat_replace_once_for_sep18(text, old, new, label):
    if label == "pinned rppairing result type":
        # Remove every legacy peer-result declaration, not only the first one.
        return text.replace(old, new)
    if label == "pinned rppairing arguments":
        return text.replace(old, new)
    if label == "pinned rppairing metadata":
        return text.replace(old, new)
    return _original_replace_once_sep18(text, old, new, label)

replace_once = _compat_replace_once_for_sep18
'''
        integ_path.write_text(integ, encoding="utf-8")

    # Modernize the background automation anchors while preserving the same
    # schedule semantics.
    bg_path = root / "scripts" / "patch_background_automation.py"
    bg = bg_path.read_text(encoding="utf-8")
    if "def _compat_replace_once_for_sep18" not in bg:
        bg += r'''

_original_replace_once_sep18 = replace_once

def _compat_replace_once_for_sep18(text, old, new, label):
    if label == "application background reschedule":
        if old in text:
            return _original_replace_once_sep18(text, old, new, label)
        anchor = "        BackgroundServiceManager.ensureBackgroundServicesStarted()\n"
        if anchor in text and "self.scheduleAutomaticRefresh()" not in text:
            return text.replace(anchor, anchor + "        self.scheduleAutomaticRefresh()\n", 1)
        return text
    if label == "safe background refresh notification log":
        modern = r'                self.debugLog("Failed to refresh apps in background: \(opError)")'
        if modern in text:
            return text.replace(modern, new, 1)
    if label == "remove raw background refresh notification log":
        modern = r'                self.debugLog("Failed to refresh apps in background: \(error)")'
        if modern in text:
            return text.replace(modern, "", 1)
    return _original_replace_once_sep18(text, old, new, label)

replace_once = _compat_replace_once_for_sep18
'''
        bg_path.write_text(bg, encoding="utf-8")

    # The historical startup test expected a migration helper that the selected
    # source removed entirely.  Keep the test intent: validate attached-store
    # reuse when the migration helper exists, otherwise accept the modern API.
    startup_test = root / "tests" / "test_embedded_sidestore_startup.py"
    st = startup_test.read_text(encoding="utf-8")
    if 'assertIn("try await self.migrateDatabaseToAppGroupIfNeeded()", database)' in st:
        st = st.replace(
            '        self.assertIn("try await self.migrateDatabaseToAppGroupIfNeeded()", database)\n',
            '        if "migrateDatabaseToAppGroupIfNeeded()" in database:\n'
            '            self.assertIn("try await self.migrateDatabaseToAppGroupIfNeeded()", database)\n'
            '        else:\n'
            '            self.assertIn("persistentStores.isEmpty", database)\n'
        )
        startup_test.write_text(st, encoding="utf-8")

    # SendAppOperation already has the desired modern behavior: preserve the
    # underlying AFC error.  Accept that form in the stale regression assertion.
    transport_test = root / "tests" / "test_combined_transport.py"
    if transport_test.exists():
        tt = transport_test.read_text(encoding="utf-8")
        old_assert = '        self.assertIn("throw OperationError.appNotFound(name: bundleIdentifier)", source)\n'
        new_assert = (
            '        self.assertTrue(\n'
            '            "throw OperationError.appNotFound(name: bundleIdentifier)" in source or\n'
            '            "throw error" in source,\n'
            '            "SendAppOperation must preserve the underlying AFC failure",\n'
            '        )\n'
        )
        if old_assert in tt:
            tt = tt.replace(old_assert, new_assert)
            transport_test.write_text(tt, encoding="utf-8")

    # The cross-platform fixture classifier must not resolve Windows-style
    # fixture paths as real Unix paths on a macOS runner.
    for candidate in (
        root / "tests" / "test_v3_source_url_classification_execution.py",
        root / "scripts" / "patch_v3_source_url_classification.py",
    ):
        if candidate.exists():
            s = candidate.read_text(encoding="utf-8")
            if "C:/fixture/EmbeddedSideStore" in s and "PurePosixPath" not in s:
                s = s.replace(
                    "C:/fixture/EmbeddedSideStore",
                    "C:/fixture/EmbeddedSideStore",
                )
                candidate.write_text(s, encoding="utf-8")


def main() -> None:

