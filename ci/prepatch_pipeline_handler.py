#!/usr/bin/env python3
"""Pre-adapt newer SideStore PipelineHandler before the legacy v3 builder runs."""
from __future__ import annotations

from pathlib import Path
import re
import sys

MARKER = "V3_HEADLESS_PIPELINE_PRESENTER_REMOVED_V1"
DECISIONS = "V3_HEADLESS_PIPELINE_UI_DECISIONS_V1"

def replace_function(source: str, signature: str, replacement: str) -> str:
    if source.count(signature) != 1:
        raise SystemExit(f"pipeline prepatch: expected one {signature!r}, found {source.count(signature)}")
    start = source.index(signature)
    brace = source.index("{", start)
    depth = 0
    for i in range(brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[:start] + replacement + source[i + 1:]
    raise SystemExit(f"pipeline prepatch: unbalanced {signature!r}")

def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: prepatch_pipeline_handler.py <side-store-root>")
    root = Path(sys.argv[1]).resolve()
    path = root / "SideStore/Handlers/PipelineHandler.swift"
    text = path.read_text(encoding="utf-8")

    if MARKER in text:
        return

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
        r"^\s*private var isPresenterAvailable: Bool\s*\{.*?\n\s*\}\s*\n"
        r"^\s*@MainActor\s*\n"
        r"^\s*private var activePresenter: UIViewController\?\s*\{.*?\n\s*\}\s*\n"
    )
    text, count = presenter_re.subn(
        "    let isResignActive = false\n\n"
        f"    // {MARKER}: presenter state is never retained in the embedded service.\n",
        text,
        count=1,
    )
    if count != 1:
        raise SystemExit(f"pipeline prepatch: presenter block not found uniquely ({count})")

    replacements = [
        (
            "    func resolveBundleIDMismatch(targetID: String, activeEffectiveID: String) async -> Bool",
            f'''    func resolveBundleIDMismatch(targetID: String, activeEffectiveID: String) async -> Bool {{
    // {DECISIONS}: no UI context means fail closed.
    return false
}}''',
        ),
        (
            "    func reviewPermissions(_ permissions: [ALTEntitlement], for app: AppProtocol, mode: PermissionReviewMode) async throws",
            f'''    func reviewPermissions(_ permissions: [ALTEntitlement], for app: AppProtocol, mode: PermissionReviewMode) async throws {{
    // {DECISIONS}: permission review cannot be approved headlessly.
    throw OperationError.invalidOperationContext("PipelineHandler: Cannot review permissions because presenting view controller is unavailable")
}}''',
        ),
        (
            "    func selectAppExtensionsToRemove(",
            f'''    func selectAppExtensionsToRemove(
        appBundle: ALTApplication,
        localAppExtensions: [ALTApplication],
        excessExtensions: Set<ALTApplication>
    ) async throws -> ExtensionRemovalDecision {{
    // {DECISIONS}: keep all extensions without the review UI.
    return .keepAll(useMainProfile: false)
}}''',
        ),
        (
            "    func resolveUnsupportediOSVersion(errorDescription: String, appName: String, compatibleVersion: String) async throws -> Bool",
            f'''    func resolveUnsupportediOSVersion(errorDescription: String, appName: String, compatibleVersion: String) async throws -> Bool {{
    // {DECISIONS}: do not download an unrequested compatibility version.
    return false
}}''',
        ),
        (
            "    func requestBackgroundSuspension() async",
            f'''    func requestBackgroundSuspension() async {{
    // {DECISIONS}: background suspension is host-owned.
}}''',
        ),
        (
            "    func resolveBundleIDOverride(initialBundleID: String) async throws -> (customID: String, appendTeamID: Bool)?",
            f'''    func resolveBundleIDOverride(initialBundleID: String) async throws -> (customID: String, appendTeamID: Bool)? {{
    // {MARKER}: the combined host owns the interactive prompt.
    return (initialBundleID, true)
}}''',
        ),
        (
            "    func resolveAppGroupMismatch(originalGroup: String, correctedGroup: String) async throws -> AppGroupResolution",
            f'''    func resolveAppGroupMismatch(originalGroup: String, correctedGroup: String) async throws -> AppGroupResolution {{
    // {DECISIONS}: preserve the validated corrected group without UI.
    return .correctAndProceed(correctedGroup)
}}''',
    ]
    for signature, replacement in replacements:
        text = replace_function(text, signature, replacement)

    info_target_sig = "    func resolveInfoPlistCustomization(\n        targets: [InfoPlistTarget],"
    info_single_sig = "    func resolveInfoPlistCustomization(\n        initialPlist: [String: any Sendable],"
    ent_target_sig = "    func resolveEntitlementsCustomization(\n        targets: [EntitlementsTarget],"
    ent_single_sig = "    func resolveEntitlementsCustomization(\n        initialEntitlements: [String: any Sendable],"

    text = replace_function(
        text,
        info_target_sig,
        '''    func resolveInfoPlistCustomization(
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
    }''',
    )
    text = replace_function(
        text,
        info_single_sig,
        '''    func resolveInfoPlistCustomization(
        initialPlist: [String: any Sendable],
        initialBundleID: String,
        appendTeamID: Bool,
        installedAppIdentities: [String: String],
        teamID: String
    ) async throws -> (modifiedPlist: [String: any Sendable], appendTeamID: Bool)? {
        return (initialPlist, appendTeamID)
    }''',
    )
    text = replace_function(
        text,
        ent_target_sig,
        '''    func resolveEntitlementsCustomization(
        targets: [EntitlementsTarget],
        teamType: ALTTeamType
    ) async throws -> [String: [String: any Sendable]]? {
        var result: [String: [String: any Sendable]] = [:]
        for target in targets {
            result[target.id] = target.initialEntitlements
        }
        return result
    }''',
    )
    text = replace_function(
        text,
        ent_single_sig,
        '''    func resolveEntitlementsCustomization(
        initialEntitlements: [String: any Sendable],
        bundleID: String,
        teamType: ALTTeamType
    ) async throws -> [String: any Sendable]? {
        return initialEntitlements
    }''',
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
    remaining = [item for item in forbidden if item in text]
    if remaining:
        raise SystemExit("pipeline prepatch: forbidden headless UI tokens remain: " + ", ".join(remaining))

    path.write_text(text, encoding="utf-8")
    print("PipelineHandler prepatch applied and verified")

if __name__ == "__main__":
    main()
