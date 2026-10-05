#!/usr/bin/env python3
"""Adapt the NRG builder to the verified 20260918 source pair."""
from __future__ import annotations

import os
import re
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



def rewrite_pipeline_handler_builder(text: str) -> str:
    """Make the v3 PipelineHandler transform resilient to newer SideStore source shape."""
    start_marker = "def headless_pipeline_handler(text):"
    end_marker = "\ndef headless_pipeline_persistence_contract(text):"
    start = text.find(start_marker)
    end = text.find(end_marker, start)
    if start < 0 or end < 0:
        raise SystemExit("v3 service: headless_pipeline_handler function bounds changed")

    replacement = r'''def headless_pipeline_handler(text):
    marker = "V3_HEADLESS_BUNDLE_ID_PROMPT_V1"
    decisions_marker = "V3_HEADLESS_PIPELINE_UI_DECISIONS_V1"

    def replace_swift_function_local(source, signature, replacement_text, label):
        if source.count(signature) != 1:
            raise SystemExit(f"v3 service: expected one {label} implementation")
        method_start = source.index(signature)
        brace = source.index("{", method_start)
        depth = 0
        for index in range(brace, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    return source[:method_start] + replacement_text + source[index + 1:]
        raise SystemExit(f"v3 service: unbalanced {label} implementation")

    expected = {
        "func resolveBundleIDMismatch(targetID: String, activeEffectiveID: String) async -> Bool":
            """func resolveBundleIDMismatch(targetID: String, activeEffectiveID: String) async -> Bool {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: no UI context means fail closed.
    return false
}""",
        "func reviewPermissions(_ permissions: [ALTEntitlement], for app: AppProtocol, mode: PermissionReviewMode) async throws":
            """func reviewPermissions(_ permissions: [ALTEntitlement], for app: AppProtocol, mode: PermissionReviewMode) async throws {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: permission review cannot be approved headlessly.
    throw OperationError.invalidOperationContext("PipelineHandler: Cannot review permissions because presenting view controller is unavailable")
}""",
        "func selectAppExtensionsToRemove(":
            """func selectAppExtensionsToRemove(
        appBundle: ALTApplication,
        localAppExtensions: [ALTApplication],
        excessExtensions: Set<ALTApplication>
    ) async throws -> ExtensionRemovalDecision {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: keep all extensions without the review UI.
    return .keepAll(useMainProfile: false)
}""",
        "func resolveUnsupportediOSVersion(errorDescription: String, appName: String, compatibleVersion: String) async throws -> Bool":
            """func resolveUnsupportediOSVersion(errorDescription: String, appName: String, compatibleVersion: String) async throws -> Bool {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: do not download an unrequested compatibility version.
    return false
}""",
        "func requestBackgroundSuspension() async":
            """func requestBackgroundSuspension() async {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: background suspension is host-owned.
}""",
        "func resolveInfoPlistCustomization(
        targets: [InfoPlistTarget],
        initialBundleID: String,
        appendTeamID: Bool,
        installedAppIdentities: [String: String],
        teamID: String
    ) async throws -> (modifiedPlists: [String: [String]?, appendTeamID: Bool)?":
            "",
    }
    # The exact generic signature above varies by Swift parser formatting, so handle
    # the two customization overloads separately below with regex-free extraction.
    customization_targets_sig = """    func resolveInfoPlistCustomization(
        targets: [InfoPlistTarget],
        initialBundleID: String,
        appendTeamID: Bool,
        installedAppIdentities: [String: String],
        teamID: String
    ) async throws -> (modifiedPlists: [String: [String: Any]], appendTeamID: Bool)?"""
    # Use signature discovery by function name when result type changes.
    def replace_named_async_function(source, name, replacement_text, occurrence=1):
        pattern = rf"(?m)^    (?:@MainActor\n    )?func {re.escape(name)}\("
        matches = list(re.finditer(pattern, source))
        if len(matches) < occurrence:
            raise SystemExit(f"v3 service: expected {occurrence} {name} implementation")
        method_start = matches[occurrence - 1].start()
        brace = source.index("{", method_start)
        depth = 0
        for index in range(brace, len(source)):
            if source[index] == "{":
                depth += 1
            elif source[index] == "}":
                depth -= 1
                if depth == 0:
                    return source[:method_start] + replacement_text + source[index + 1:]
        raise SystemExit(f"v3 service: unbalanced {name} implementation")

    # Remove presenter state irrespective of minor source formatting drift.
    presenter_re = re.compile(
        r"(?ms)^    let isResignActive: Bool\s*\n"
        r"^\s*private let presenterProvider: PresenterProvider\?\s*\n"
        r"^\s*init\(\s*\n"
        r"^\s*isResignActive: Bool = false,\s*\n"
        r"^\s*presenterProvider: PresenterProvider\? = nil\s*\n"
        r"^\s*\)\s*\{\s*\n"
        r"^\s*self\.isResignActive = isResignActive\s*\n"
        r"^\s*self\.presenterProvider = presenterProvider\s*\n"
        r"^\s*\}\s*\n"
        r"^\s*@MainActor\s*\n"
        r"^\s*private var isPresenterAvailable: Bool\s*\{\s*"
        r".*?"
        r"^\s*@MainActor\s*\n"
        r"^\s*private var activePresenter: UIViewController\?\s*\{\s*"
        r".*?"
        r"^\s*\}\s*\n",
    )
    text, count = presenter_re.subn(
        "    let isResignActive = false\n\n"
        "    // V3_HEADLESS_PIPELINE_PRESENTER_REMOVED_V1: presenter state is never retained in the embedded service.\n",
        text,
        count=1,
    )
    if count != 1:
        # If a previous adapter already inserted the marker, still fail only when
        # legacy presenter state can be found; this keeps the transform deterministic.
        if "V3_HEADLESS_PIPELINE_PRESENTER_REMOVED_V1" not in text:
            raise SystemExit("v3 service: unable to remove PipelineHandler presenter state")

    replacements = [
        (
            "func resolveBundleIDMismatch(targetID: String, activeEffectiveID: String) async -> Bool",
            """    func resolveBundleIDMismatch(targetID: String, activeEffectiveID: String) async -> Bool {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: no UI context means fail closed.
    return false
}""",
        ),
        (
            "func reviewPermissions(_ permissions: [ALTEntitlement], for app: AppProtocol, mode: PermissionReviewMode) async throws",
            """    func reviewPermissions(_ permissions: [ALTEntitlement], for app: AppProtocol, mode: PermissionReviewMode) async throws {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: permission review cannot be approved headlessly.
    throw OperationError.invalidOperationContext("PipelineHandler: Cannot review permissions because presenting view controller is unavailable")
}""",
        ),
        (
            "func selectAppExtensionsToRemove(",
            """    func selectAppExtensionsToRemove(
        appBundle: ALTApplication,
        localAppExtensions: [ALTApplication],
        excessExtensions: Set<ALTApplication>
    ) async throws -> ExtensionRemovalDecision {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: keep all extensions without the review UI.
    return .keepAll(useMainProfile: false)
}""",
        ),
        (
            "func resolveUnsupportediOSVersion(errorDescription: String, appName: String, compatibleVersion: String) async throws -> Bool",
            """    func resolveUnsupportediOSVersion(errorDescription: String, appName: String, compatibleVersion: String) async throws -> Bool {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: do not download an unrequested compatibility version.
    return false
}""",
        ),
        (
            "func requestBackgroundSuspension() async",
            """    func requestBackgroundSuspension() async {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: background suspension is host-owned.
}""",
        ),
        (
            "func resolveBundleIDOverride(initialBundleID: String) async throws -> (customID: String, appendTeamID: Bool)?",
            """    func resolveBundleIDOverride(initialBundleID: String) async throws -> (customID: String, appendTeamID: Bool)? {
    // V3_HEADLESS_BUNDLE_ID_PROMPT_V1: the combined host owns the interactive prompt.
    return (initialBundleID, true)
}""",
        ),
        (
            "func resolveAppGroupMismatch(originalGroup: String, correctedGroup: String) async throws -> AppGroupResolution",
            """    func resolveAppGroupMismatch(originalGroup: String, correctedGroup: String) async throws -> AppGroupResolution {
    // V3_HEADLESS_PIPELINE_UI_DECISIONS_V1: preserve the validated corrected group without UI.
    return .correctAndProceed(correctedGroup)
}""",
    ]
    for signature, replacement_text in replacements:
        if signature not in text:
            raise SystemExit(f"v3 service: missing PipelineHandler function {signature!r}")
        text = replace_swift_function_local(text, signature, replacement_text, signature)

    # Newer SideStore added Info.plist/entitlement customization handlers which
    # are UI-only. Headless mode keeps the original values.
    info_targets = r"""    @MainActor
    func resolveInfoPlistCustomization(
        targets: [InfoPlistTarget],
        initialBundleID: String,
        appendTeamID: Bool,
        installedAppIdentities: [String: String],
        teamID: String
    )"""
    if text.count(info_targets) != 1:
        raise SystemExit("v3 service: expected one Info.plist customization target overload")
    text = replace_named_async_function(
        text,
        "resolveInfoPlistCustomization",
        """    func resolveInfoPlistCustomization(
        targets: [InfoPlistTarget],
        initialBundleID: String,
        appendTeamID: Bool,
        installedAppIdentities: [String: String],
        teamID: String
    ) async throws -> (modifiedPlists: [String: [String: any Sendable]], appendTeamID: Bool)? {
        var result: [String: [String: any Sendable]] = [:]
        for target in targets {
            result[target.id] = target.initialPlist
        }
        return (result, appendTeamID)
    }""",
        occurrence=1,
    )
    text = replace_named_async_function(
        text,
        "resolveInfoPlistCustomization",
        """    func resolveInfoPlistCustomization(
        initialPlist: [String: any Sendable],
        initialBundleID: String,
        appendTeamID: Bool,
        installedAppIdentities: [String: String],
        teamID: String
    ) async throws -> (modifiedPlist: [String: any Sendable], appendTeamID: Bool)? {
        return (initialPlist, appendTeamID)
    }""",
        occurrence=1,
    )

    text = replace_named_async_function(
        text,
        "resolveEntitlementsCustomization",
        """    func resolveEntitlementsCustomization(
        targets: [EntitlementsTarget],
        teamType: ALTTeamType
    ) async throws -> [String: [String: any Sendable]]? {
        var result: [String: [String: any Sendable]] = [:]
        for target in targets {
            result[target.id] = target.initialEntitlements
        }
        return result
    }""",
        occurrence=1,
    )
    text = replace_named_async_function(
        text,
        "resolveEntitlementsCustomization",
        """    func resolveEntitlementsCustomization(
        initialEntitlements: [String: any Sendable],
        bundleID: String,
        teamType: ALTTeamType
    ) async throws -> [String: any Sendable]? {
        return initialEntitlements
    }""",
        occurrence=1,
    )

    forbidden = (
        "presenterProvider",
        "activePresenter",
        "isPresenterAvailable",
        "isResignActive:",
        "UIAlertController",
        "ReviewPermissionsViewController",
        "AppExtensionViewHostingController",
        "presentingViewController",
        "InfoPlistCustomizationSheetView",
        "InfoPlistCustomizationView",
        "EntitlementsCustomizationSheetView",
        "EntitlementsCustomizationView",
    )
    if any(token in text for token in forbidden):
        raise SystemExit("v3 service: legacy PipelineHandler presenter/UI state remains")
    return text
'''
    new_text = text[:start] + replacement + text[end:]
    if new_text == text:
        raise SystemExit("v3 service: PipelineHandler builder rewrite produced no change")
    return new_text

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
    text = rewrite_pipeline_handler_builder(text)
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
    pipeline = """return PipelineHandler(
            isResignActive: presentingViewController is ResignAltStoreViewController,
            presenterProvider: { [weak presentingViewController] in
                presentingViewController?.presentedViewController ?? presentingViewController
            }
        )"""
    # Newer SideStore removed the old AppManager sign-in/deactivate wrappers,
    # but retained one presenter-aware PipelineHandler factory for normal UI
    # operations. The embedded service must use the presenter-free handler.
    if (
        "func signIn(presentingViewController: UIViewController?," not in text
        and "func deactivateApps(for appBundle: ALTApplication" not in text
    ):
        if pipeline in text:
            text = text.replace(pipeline, "return PipelineHandler()", 1)
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