# RoofSpan BAFunctions — Burn-side PostgreSQL bootstrap credential generator

A tiny **BAFunctions** native DLL that supplements the stock WiX v5 `WixStandardBootstrapperApplication`
(WixStdBA). It keeps the standard installer UI and adds exactly one behavior.

## What it does
`OnPlanBegin` (after Detect, before the chain executes):
- If `PgSuperPassword` is already non-empty → **do nothing** (enterprise/external override supplied).
- Else if `RoofSpanPgPresent == 1` → **do nothing** (RoofSpan-managed PostgreSQL already installed; upgrade
  preserves existing credentials).
- Else (fresh RoofSpan-managed install) → generate **32 CSPRNG bytes (`BCryptGenRandom`) → 64 hex chars**
  and store via `BalSetStringVariable`. If RNG/set fails, it **cancels** planning (`*pfCancel = TRUE`) and
  returns the failure HRESULT — **fail closed**, never proceeding into EDB with an empty `--superpassword`.

`PgSuperPassword` is `Hidden="yes"` in `bundle.wxs`, so Burn **redacts** it in logs, including the EDB
`--superpassword` command line and the MSI `PG_SUPERPASSWORD`. It is not persisted by Burn. The RoofSpan
**application** DB password is a *separate* random value (see `winbuild/bootstrap_db.py`) and is the only
password written to the deployed `DATABASE_URL`.

## Files
| File | Purpose |
| --- | --- |
| `RoofSpanBaFunctions.cpp` | `CRoofSpanBAFunctions : CBalBaseBAFunctions`, `OnPlanBegin` logic, `CreateBAFunctions`. |
| `dllmain.cpp` | `DllMain` + exported `BAFunctionsCreate` / `BAFunctionsDestroy` (PCH create unit). |
| `pch.h` | Precompiled header (WiX v5 SDK includes + `bcrypt.h`). |
| `RoofSpanBaFunctions.def` | Exports `BAFunctionsCreate`, `BAFunctionsDestroy`. |
| `RoofSpanBaFunctions.vcxproj` | Reproducible x64 MSBuild project; **pins** the WiX v5 native SDK. |
| `build_bafunctions.ps1` | Restore + build; prints the produced DLL path. |

## Pinned dependencies (WiX v5)
`RoofSpanBaFunctions.vcxproj` pins:
- `WixToolset.BootstrapperApplicationApi` **5.0.2**
- `WixToolset.WixStandardBootstrapperApplicationFunctionApi` **5.0.2**

`WixToolset.DUtil` is pulled transitively. The BAFunctions FunctionApi package line begins at 5.0.0 — there
is no v4 equivalent — so the installer standardizes on **WiX v5**. Keep these pins in lockstep with the
installed `wix` toolset major version (`dotnet tool install --global wix --version 5.*`).

## Build (HUMAN REQUIRED — Windows)
From a *Developer PowerShell for VS 2022* (Desktop C++ workload installed):

```powershell
cd windows\bafunctions
.\build_bafunctions.ps1 -Configuration Release -Platform x64
# -> bin\x64\Release\RoofSpanBaFunctions.dll
```

You normally don't run this directly: `installer\build.ps1` calls it automatically before the Burn bundle
(pass `-BaFunctionsDll <path>` only to override with a pre-built/CI DLL). The build flow is:

```
build_bafunctions.ps1 -> RoofSpanBaFunctions.dll
  -> installer\build.ps1 consumes it (-d BaFunctionsDll=...)
  -> wix build RoofSpan.wxs  (MSI)
  -> wix build bundle.wxs    (Burn bundle, references the DLL via bal:IsBAFunctions="yes")
```

## Runtime validation (HUMAN REQUIRED, later gate — not required to prove the build)
- Fresh install, no unrelated PostgreSQL: EDB installs `RoofSpanPostgreSQL` on port **5442** with the
  generated superpassword; the MSI provisions the `roofspan` role/db and writes the deployed `DATABASE_URL`.
  Confirm `PgSuperPassword` appears **redacted** (`*****`) in the Burn log.
- Fresh install with an unrelated PostgreSQL on 5432: RoofSpan still installs its own instance on 5442.
- Upgrade of an existing RoofSpan install: EDB skipped (`RoofSpanPgPresent`), no new password generated,
  deployed config preserved.
- Enterprise override (`-DPgSuperPassword=...` / a `PgSuperPassword` supplied to Burn): the supplied
  credential is used and the hook generates nothing.
