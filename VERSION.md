# Version Baseline

## Primary baseline — LiveContainer Nightly 20260918

The project now uses the 20260918 LiveContainer + SideStore nightly IPA as the primary clean baseline.

- LiveContainer: 3.8.10
- LiveContainer source commit: 4dbe0f9a626de801184a42c0be8d2cb105058e3d
- Embedded SideStore: 0.7.0-20260918.492+12a496ca
- SideStore CFBundleVersion: 0700
- SideStore source commit: 12a496ca1c766a102193634879823d16610bf1cd
- Baseline IPA SHA-256: bec41bc21d75a0f2e85a0aa589ce5772e24e410deb017486758a3bc0503c8de7

The nightly IPA is currently mirrored at LiveContainerMirror/LiveContainer/releases/download/nightly/LiveContainer+SideStore.ipa

## Secondary comparison baseline — NRG-Wardog Unified v3.1.0

- Public release: v3.1.0
- LiveContainer: 3.8.9
- LiveContainer commit: 12377cf3b91d51739a33f14a302e5f522b238593
- Embedded SideStore: 0.7.0
- SideStore CFBundleVersion: 0700
- SideStore bundle commit: ff25922e5c13ccfafd83bda5092910d848ebd409
- Builder: 651587433eb7142089509e558dcfba9eb69d0470
- IPA SHA-256: 2337e08a71b2af4fee930b59ccd28522563acd81e908069e56f6d27d1636daf4

## Project rule

AutoRefresh changes are layered on top of the primary nightly baseline. Every test build receives a unique version suffix based on the GitHub Actions Run Number.
