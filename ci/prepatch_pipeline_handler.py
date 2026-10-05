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
    next_func = re.search(
        r"(?m)^    (?:@MainActor\\n    )?(?:func|private func|public func) ",
        source[start + len(signature):],
    )
    if next_func:
        end = start + len(signature) + next_func.start()
        return source[:start] + replacement + source[end:]
    class_end = re.search(r"(?m)^}\\s*$", source[start:])
    if class_end:
        end = start + class_end.start()
        return source[:start] + replacement + source[end:]
    raise SystemExit(f"pipeline prepatch: could not locate end of {signature!r}")

def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: prepatch_pipeline_handler.py <side-store-root>")
    root = Path(sys.argv[1]).resolve()
    path = root / "SideStore/Handlers/PipelineHandler.swift"
    text = path.read_text(encoding="utf-8")

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
        "    let isResignActive = false\n\n" +
        f"    // {MARKER}: presenter state is never retained in the embedded service.\n",
        text, count=1
    )
    if count != 1:
        raise SystemExit(f"pipeline prepatch: presenter block not found uniquely ({count})")

    replacements = [
        (
            "    func resolveBundleIDMismatch(targetID: String, activeEffectiveID: String) async -> Bool",
            f"    func resolveBundleIDMismatch(targetID: String, activeEffectiveID: String) async -> Bool {{\n    // {DECISIONS}: no UI context means fail closed.\n    return false\n}}",
        ),
        (
            "    func reviewPermissions(_ permissions: [ALTEntitlement], for app: AppProtocol, mode: PermissionReviewMode) async throws",
            f"    func reviewPermissions(_ permissions: [ALTEntitlement], for app: AppProtocol, mode: PermissionReviewMode) async throws {{\n    // {DECISIONS}: permission review cannot be approved headlessly.\n    throw OperationError.invalidOperationContext(\"PipelineHandler: Cannot review permissions because presenting view controller is unavailable\")\n}}",
        ),
        (
            "    func selectAppExtensionsToRemove(",
            f"    func selectAppExtensionsToRemove(\n        appBundle: ALTApplication,\n        localAppExtensions: [ALTApplication],\n        excessExtensions: Set<ALTApplication>\n    ) async throws -> ExtensionRemovalDecision {{\n    // {DECISIONS}: keep all extensions without the review UI.\n    return .keepAll(useMainProfile: false)\n}}",
        ),
        (
            "    func resolveUnsupportediOSVersion(errorDescription: String, appName: String, compatibleVersion: String) async throws -> Bool",
            f"    func resolveUnsupportediOSVersion(errorDescription: String, appName: String, compatibleVersion: String) async throws -> Bool {{\n    // {DECISIONS}: do not download an unrequested compatibility version.\n    return false\n}}",
        ),
        (
            "    func requestBackgroundSuspension() async",
            f"    func requestBackgroundSuspension() async {{\n    // {DECISIONS}: suspension is controlled by the host lifecycle.\n}}",
        ),
        (
            "    func resolveBundleIDOverride(initialBundleID: String) async throws -> (customID: String, appendTeamID: Bool)?",
            f"    func resolveBundleIDOverride(initialBundleID: String) async throws -> (customID: String, appendTeamID: Bool)? {{\n    // {MARKER}: the combined host owns the interactive prompt.\n    return (initialBundleID, true)\n}}",
        ),
        (
            "    func resolveAppGroupMismatch(originalGroup: String, correctedGroup: String) async throws -> AppGroupResolution",
            f"    func resolveAppGroupMismatch(originalGroup: String, correctedGroup: String) async throws -> AppGroupResolution {{\n    // {DECISIONS}: preserve the validated corrected group without UI.\n    return .correctAndProceed(correctedGroup)\n}}",
        ),
    ]
    for signature, replacement in replacements:
        text = replace_function(text, signature, replacement)

    info_target = "    func resolveInfoPlistCustomization(\n        targets: [InfoPlistTarget],"
    info_single = "    func resolveInfoPlistCustomization(\n        initialPlist: [String: any Sendable],"
    ent_target = "    func resolveEntitlementsCustomization(\n        targets: [EntitlementsTarget],"
    ent_single = "    func resolveEntitlementsCustomization(\n        initialEntitlements: [String: any Sendable],"

    text = replace_function(text, info_target,
        "    func resolveInfoPlistCustomization(\n"
        "        targets: [InfoPlistTarget],\n"
        "        initialBundleID: String,\n"
        "        appendTeamID: Bool,\n"
        "        installedAppIdentities: [String: String],\n"
        "        teamID: String\n"
        "    ) async throws -> (modifiedPlists: [String: [String: any Sendable]], appendTeamID: Bool)? {\n"
        "        var result: [String: [String: any Sendable]] = [:]\n"
        "        for target in targets { result[target.id] = target.initialPlist }\n"
        "        return (result, appendTeamID)\n"
        "    }"
    )
    text = replace_function(text, info_single,
        "    func resolveInfoPlistCustomization(\n"
        "        initialPlist: [String: any Sendable],\n"
        "        initialBundleID: String,\n"
        "        appendTeamID: Bool,\n"
        "        installedAppIdentities: [String: String],\n"
        "        teamID: String\n"
        "    ) async throws -> (modifiedPlist: [String: any Sendable], appendTeamID: Bool)? {\n"
        "        return (initialPlist, appendTeamID)\n"
        "    }"
    )
    text = replace_function(text, ent_target,
        "    func resolveEntitlementsCustomization(\n"
        "        targets: [EntitlementsTarget],\n"
        "        teamType: ALTTeamType\n"
        "    ) async throws -> [String: [String: any Sendable]]? {\n"
        "        var result: [String: [String: any Sendable]] = [:]\n"
        "        for target in targets { result[target.id] = target.initialEntitlements }\n"
        "        return result\n"
        "    }"
    )
    text = replace_function(text, ent_single,
        "    func resolveEntitlementsCustomization(\n"
        "        initialEntitlements: [String: any Sendable],\n"
        "        bundleID: String,\n"
        "        teamType: ALTTeamType\n"
        "    ) async throws -> [String: any Sendable]? {\n"
        "        return initialEntitlements\n"
        "    }"
    )

    # Newer SideStore adds three more presenter-backed customization methods at the
    # tail of PipelineHandler. Keep protocol-compatible headless defaults and drop
    # the private image-picker helper, which is only used by that UI path.
    tail_start = "\n    @MainActor\n    func resolveAppGroupMismatch("
    tail_end = "\n}\n\nprivate final class ImagePickerDelegateHandler"
    if tail_start not in text or tail_end not in text:
        raise SystemExit("pipeline prepatch: newer customization tail layout changed")
    start = text.index(tail_start)
    end = text.index(tail_end, start)
    tail_replacement = (
        "\n    @MainActor\n"
        "    func resolveAppGroupMismatch(originalGroup: String, correctedGroup: String) async throws -> AppGroupResolution {\n"
        f"    // {DECISIONS}: preserve the validated corrected group without UI.\n"
        "    return .correctAndProceed(correctedGroup)\n"
        "    }\n\n"
        "    @MainActor\n"
        "    func resolveAppIconCustomization(appName: String) async throws -> URL? {\n"
        f"    // {DECISIONS}: the embedded service never presents icon pickers.\n"
        "    return nil\n"
        "    }\n\n"
        "    @MainActor\n"
        "    func resolveProvisioningProfileCustomization(appName: String, bundleID: String) async throws -> ProfileCustomizationChoice? {\n"
        f"    // {DECISIONS}: use the automatic profile without a UI choice.\n"
        "    return .defaultProfile\n"
        "    }\n"
    )
    text = text[:start] + tail_replacement + text[end:]
    helper_start = text.find("\n\nprivate final class ImagePickerDelegateHandler")
    if helper_start >= 0:
        text = text[:helper_start] + "\n";
    forbidden = (
        "presenterProvider", "activePresenter", "isPresenterAvailable",
        "isResignActive:", "UIAlertController", "ReviewPermissionsViewController",
        "AppExtensionViewHostingController", "presentingViewController",
        "InfoPlistCustomizationSheetView", "InfoPlistCustomizationView",
        "EntitlementsCustomizationSheetView", "EntitlementsCustomizationView",
    )
    remaining = [item for item in forbidden if item in text]
    if remaining:
        details = []
        lines = text.splitlines()
        for item in remaining:
            for number, line in enumerate(lines, 1):
                if item in line:
                    details.append(f"{item}@{number}: {line.strip()}")
        raise SystemExit("pipeline prepatch: forbidden headless UI tokens remain: " + "; ".join(details))

    path.write_text(text, encoding="utf-8")
    print("PipelineHandler prepatch applied and verified")

if __name__ == "__main__":
    main()