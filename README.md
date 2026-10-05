# LiveContainer + SideStore AutoRefresh

本專案以 **LiveContainer Nightly 20260918 + SideStore 0.7.0** 為乾淨基底，整合 NRG-Wardog sidestore-auto-refresh 的 AutoRefresh 修復與建置流程。

## 基底
- LiveContainer 3.8.10
- LiveContainer commit: 4dbe0f9a626de801184a42c0be8d2cb105058e3d
- Embedded SideStore: 0.7.0-20260918.492+12a496ca
- SideStore commit: 12a496ca1c766a102193634879823d16610bf1cd

## AutoRefresh
核心 AutoRefresh 程式碼採 NRG-Wardog v3.1.0 已驗證 builder 的 patches，並改為套在上述 20260918 nightly 基底，而不是使用 NRG v3.1.0 自帶的 LiveContainer 3.8.9。

## 建置
GitHub Actions 提供：
- nightly baseline verification
- LiveContainer + embedded SideStore source build
- AutoRefresh patches
- IPA static/package verification
- versioned artifact naming

每次測試 IPA 使用：
`LiveContainer-SideStore-AutoRefresh-nightly-20260918-build<RunNumber>.ipa`

## 狀態
目前先以乾淨 nightly baseline 建置成功作為基準；source build 如遇上游 mirror/CI 存取問題，會修正 CI，不改變基底版本。
