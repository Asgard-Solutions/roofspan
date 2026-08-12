// RoofSpan Office — minimal BAFunctions native hook for the WiX v4 Burn bundle (bundle.wxs).
//
// PURPOSE (single responsibility, K.I.S.S.):
//   Seed the Hidden Burn variable `PgSuperPassword` with a cryptographically random PostgreSQL
//   superuser/bootstrap password BEFORE the chain executes, for a NEW RoofSpan-managed PostgreSQL
//   install only. This is the smallest officially-supported WiX v4 mechanism to run RNG code inside
//   Burn while KEEPING the stock WixStandardBootstrapperApplication UI (BAFunctions, referenced from
//   bundle.wxs via bal:IsBAFunctions="yes"). WixStdBA has no built-in secure-RNG variable generation.
//
// FLOW:
//   OnDetectComplete (runs after Detect, before Plan):
//     * If PgSuperPassword is ALREADY non-empty  -> do nothing (enterprise/external override supplied).
//     * Else if RoofSpanPgPresent == 1           -> do nothing (RoofSpan-managed PG already installed;
//                                                     upgrade/repair preserves existing creds).
//     * Else (fresh RoofSpan-managed install)    -> generate 32 CSPRNG bytes -> 64 hex chars and store
//                                                     via SetVariableString. Because PgSuperPassword is
//                                                     Hidden, Burn redacts it in logs (incl. the EDB and
//                                                     MSI command lines). It is never persisted by Burn.
//
// The generated superuser password is used ONLY to authenticate + provision; RoofSpan then creates its
// least-privilege `roofspan` role with a SEPARATE application password (see winbuild/bootstrap_db.py).
//
// HUMAN REQUIRED (Windows build): compile against the NuGet
//   WixToolset.WixStandardBootstrapperApplicationFunctionApi
// which provides BalBaseBAFunctions.h / IBAFunctions.h / the BA_FUNCTIONS_* structs. The exact method
// signatures below follow the documented v4 BAFunctions pattern; reconcile them against the pinned NuGet
// header version at build time. Export BAFunctionsCreate via RoofSpanBaFunctions.def. See README.md.

#include <windows.h>
#include <bcrypt.h>
#include <strsafe.h>

// Provided by the WixStandardBootstrapperApplicationFunctionApi NuGet package.
#include "BalBaseBootstrapperApplicationProc.h"
#include "BalBaseBAFunctions.h"
#include "BalBaseBAFunctionsProc.h"

#pragma comment(lib, "bcrypt.lib")

static const LPCWSTR ROOFSPAN_PG_SUPERPASSWORD = L"PgSuperPassword";
static const LPCWSTR ROOFSPAN_PG_PRESENT       = L"RoofSpanPgPresent";
static const DWORD   ROOFSPAN_PG_PW_BYTES      = 32; // -> 64 hex chars

// CSPRNG -> lowercase hex string. Returns S_OK and fills wzOut (must hold cch >= 2*cbBytes + 1).
static HRESULT GenerateHexPassword(DWORD cbBytes, LPWSTR wzOut, size_t cchOut)
{
    if (cchOut < static_cast<size_t>(cbBytes) * 2 + 1) return E_INVALIDARG;

    BYTE rgbRandom[64] = { 0 };
    if (cbBytes > sizeof(rgbRandom)) return E_INVALIDARG;

    NTSTATUS status = ::BCryptGenRandom(nullptr, rgbRandom, cbBytes, BCRYPT_USE_SYSTEM_PREFERRED_RNG);
    if (status != 0) return HRESULT_FROM_NT(status);

    static const wchar_t kHex[] = L"0123456789abcdef";
    for (DWORD i = 0; i < cbBytes; ++i)
    {
        wzOut[i * 2]     = kHex[(rgbRandom[i] >> 4) & 0x0F];
        wzOut[i * 2 + 1] = kHex[rgbRandom[i] & 0x0F];
    }
    wzOut[cbBytes * 2] = L'\0';
    ::SecureZeroMemory(rgbRandom, sizeof(rgbRandom));
    return S_OK;
}

class CRoofSpanBAFunctions : public CBalBaseBAFunctions
{
public:
    // Runs after Burn's Detect phase and before Plan — the correct point to seed the credential so it
    // is available to BOTH the EDB ExePackage (--superpassword) and the MSI (PG_SUPERPASSWORD).
    virtual STDMETHODIMP OnDetectComplete(
        __in HRESULT hrStatus,
        __in BOOL fEligibleForCleanup
        )
    {
        SeedSuperPasswordIfNeeded();
        return CBalBaseBAFunctions::OnDetectComplete(hrStatus, fEligibleForCleanup);
    }

private:
    void SeedSuperPasswordIfNeeded()
    {
        // 1) Enterprise/external override already supplied? Never overwrite it.
        LPWSTR sczExisting = nullptr;
        HRESULT hr = m_pEngine->GetVariableString(ROOFSPAN_PG_SUPERPASSWORD, nullptr, nullptr);
        // (GetVariableString with a sizing call; use BalGetStringVariable helper in practice.)
        if (SUCCEEDED(BalGetStringVariable(ROOFSPAN_PG_SUPERPASSWORD, &sczExisting)) &&
            sczExisting && *sczExisting)
        {
            SecureFree(sczExisting);
            return; // override present
        }
        SecureFree(sczExisting);

        // 2) RoofSpan-managed PostgreSQL already installed (upgrade/repair)? No new credential needed.
        LONGLONG llPresent = 0;
        if (SUCCEEDED(m_pEngine->GetVariableNumeric(ROOFSPAN_PG_PRESENT, &llPresent)) && llPresent == 1)
        {
            return;
        }

        // 3) Fresh RoofSpan-managed install: generate and store the CSPRNG bootstrap credential.
        WCHAR wzPassword[ROOFSPAN_PG_PW_BYTES * 2 + 1] = { 0 };
        if (SUCCEEDED(GenerateHexPassword(ROOFSPAN_PG_PW_BYTES, wzPassword, ARRAYSIZE(wzPassword))))
        {
            // Hidden variable -> Burn redacts in logs. fFormatted = FALSE (store literally).
            m_pEngine->SetVariableString(ROOFSPAN_PG_SUPERPASSWORD, wzPassword, FALSE);
            ::SecureZeroMemory(wzPassword, sizeof(wzPassword));
        }
        // If generation fails, PgSuperPassword stays empty; the EDB install / MSI bootstrap then fail
        // closed (bootstrap_db.require_bootstrap_password), rolling back the install. Never fail open.
    }

    static void SecureFree(LPWSTR& sz)
    {
        if (sz)
        {
            ::SecureZeroMemory(sz, wcslen(sz) * sizeof(WCHAR));
            ::StrTrimW(sz, L""); // no-op guard; real code uses ReleaseStr from dutil
            sz = nullptr;
        }
    }

public:
    CRoofSpanBAFunctions(HMODULE hModule, IBootstrapperEngine* pEngine, const BA_FUNCTIONS_CREATE_ARGS* pArgs)
        : CBalBaseBAFunctions(hModule, pEngine, pArgs) {}
};

// Burn/WixStdBA loads this exported entry point (see RoofSpanBaFunctions.def).
extern "C" HRESULT WINAPI BAFunctionsCreate(
    __in const BA_FUNCTIONS_CREATE_ARGS* pArgs,
    __inout BA_FUNCTIONS_CREATE_RESULTS* pResults
    )
{
    HRESULT hr = S_OK;
    IBootstrapperEngine* pEngine = nullptr;

    hr = BalInitializeFromCreateArgs(pArgs->pBootstrapperCreateArgs, &pEngine);
    if (FAILED(hr)) return hr;

    CRoofSpanBAFunctions* pBAFunctions =
        new CRoofSpanBAFunctions(pArgs->hInstance, pEngine, pArgs);
    if (!pBAFunctions) { hr = E_OUTOFMEMORY; goto LExit; }

    pResults->pfnBAFunctionsProc = BalBaseBAFunctionsProc;
    pResults->pvBAFunctionsProcContext = pBAFunctions;
    pBAFunctions = nullptr;

LExit:
    if (pEngine) pEngine->Release();
    return hr;
}
