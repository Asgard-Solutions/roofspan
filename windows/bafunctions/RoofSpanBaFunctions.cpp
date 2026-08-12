// RoofSpan Office — BAFunctions native hook for the WiX v5 Burn bundle (installer\bundle.wxs).
//
// Single responsibility: seed the Hidden Burn variable `PgSuperPassword` with a cryptographically random
// PostgreSQL superuser/bootstrap password BEFORE the chain executes, for a NEW RoofSpan-managed
// PostgreSQL install only. This is the smallest WiX-supported mechanism to run RNG code inside Burn while
// keeping the stock WixStandardBootstrapperApplication UI (referenced via bal:IsBAFunctions="yes").
//
// OnPlanBegin runs after Detect (so RoofSpanPgPresent + any enterprise override are known) and before the
// chain executes, so the value is available to BOTH the EDB ExePackage (--superpassword) and the MSI
// (PG_SUPERPASSWORD). Because PgSuperPassword is Hidden, Burn redacts it in all logs (incl. command lines).

#include "pch.h"
#include "BalBaseBAFunctions.h"
#include "BalBaseBAFunctionsProc.h"

static LPCWSTR ROOFSPAN_PG_SUPERPASSWORD = L"PgSuperPassword";
static LPCWSTR ROOFSPAN_PG_PRESENT       = L"RoofSpanPgPresent";
static const DWORD ROOFSPAN_PG_PW_BYTES  = 32; // -> 64 lowercase-hex characters

// CSPRNG -> lowercase hex. Returns S_OK and fills wzOut (must hold cchOut >= 2*cbBytes + 1).
static HRESULT GenerateHexPassword(
    __in DWORD cbBytes,
    __out_ecount_z(cchOut) LPWSTR wzOut,
    __in size_t cchOut
    )
{
    HRESULT hr = S_OK;
    BYTE rgbRandom[ROOFSPAN_PG_PW_BYTES] = { 0 };
    NTSTATUS status = 0;
    static const wchar_t kHex[] = L"0123456789abcdef";

    if (cbBytes > sizeof(rgbRandom) || cchOut < static_cast<size_t>(cbBytes) * 2 + 1)
    {
        ExitFunction1(hr = E_INVALIDARG);
    }

    status = ::BCryptGenRandom(NULL, rgbRandom, cbBytes, BCRYPT_USE_SYSTEM_PREFERRED_RNG);
    if (status != 0) // STATUS_SUCCESS == 0
    {
        ExitFunction1(hr = HRESULT_FROM_NT(status));
    }

    for (DWORD i = 0; i < cbBytes; ++i)
    {
        wzOut[i * 2]     = kHex[(rgbRandom[i] >> 4) & 0x0F];
        wzOut[i * 2 + 1] = kHex[rgbRandom[i] & 0x0F];
    }
    wzOut[cbBytes * 2] = L'\0';

LExit:
    ::SecureZeroMemory(rgbRandom, sizeof(rgbRandom));
    return hr;
}

class CRoofSpanBAFunctions : public CBalBaseBAFunctions
{
public: // IBAFunctions — runs after Detect, before the chain executes.
    virtual STDMETHODIMP OnPlanBegin(
        __in DWORD cPackages,
        __inout BOOL* pfCancel
        )
    {
        HRESULT hr = S_OK;
        LPWSTR sczExisting = NULL;
        LONGLONG llPresent = 0;
        WCHAR wzPassword[ROOFSPAN_PG_PW_BYTES * 2 + 1] = { 0 };

        UNREFERENCED_PARAMETER(cPackages);

        // 1) Enterprise/external override already supplied? Never overwrite it.
        if (SUCCEEDED(BalGetStringVariable(ROOFSPAN_PG_SUPERPASSWORD, &sczExisting)) &&
            sczExisting && *sczExisting)
        {
            BalLog(BOOTSTRAPPER_LOG_LEVEL_STANDARD, "RoofSpan: PgSuperPassword override supplied; not generating one.");
            ExitFunction();
        }

        // 2) RoofSpan-managed PostgreSQL already installed (upgrade/repair)? No new credential needed.
        if (SUCCEEDED(BalGetNumericVariable(ROOFSPAN_PG_PRESENT, &llPresent)) && 1 == llPresent)
        {
            BalLog(BOOTSTRAPPER_LOG_LEVEL_STANDARD, "RoofSpan: managed PostgreSQL already present; preserving existing credentials.");
            ExitFunction();
        }

        // 3) Fresh RoofSpan-managed install: generate + store the CSPRNG bootstrap credential.
        hr = GenerateHexPassword(ROOFSPAN_PG_PW_BYTES, wzPassword, countof(wzPassword));
        if (FAILED(hr))
        {
            // FAIL CLOSED: never let WixStdBA proceed into EDB with an empty --superpassword.
            BalLog(BOOTSTRAPPER_LOG_LEVEL_ERROR, "RoofSpan: failed to generate PostgreSQL bootstrap credential (0x%x); cancelling.", hr);
            *pfCancel = TRUE;
            ExitFunction();
        }

        hr = BalSetStringVariable(ROOFSPAN_PG_SUPERPASSWORD, wzPassword, FALSE);
        if (FAILED(hr))
        {
            BalLog(BOOTSTRAPPER_LOG_LEVEL_ERROR, "RoofSpan: failed to set PgSuperPassword variable (0x%x); cancelling.", hr);
            *pfCancel = TRUE;
            ExitFunction();
        }

        BalLog(BOOTSTRAPPER_LOG_LEVEL_STANDARD, "RoofSpan: generated fresh PostgreSQL bootstrap credential (value redacted).");

    LExit:
        ::SecureZeroMemory(wzPassword, sizeof(wzPassword));
        ReleaseStr(sczExisting);
        return hr;
    }

public:
    CRoofSpanBAFunctions(
        __in HMODULE hModule
        ) : CBalBaseBAFunctions(hModule)
    {
    }
};

HRESULT WINAPI CreateBAFunctions(
    __in HMODULE hModule,
    __in const BA_FUNCTIONS_CREATE_ARGS* pArgs,
    __inout BA_FUNCTIONS_CREATE_RESULTS* pResults
    )
{
    HRESULT hr = S_OK;
    CRoofSpanBAFunctions* pBAFunctions = NULL;

    pBAFunctions = new CRoofSpanBAFunctions(hModule);
    ExitOnNull(pBAFunctions, hr, E_OUTOFMEMORY, "Failed to create new CRoofSpanBAFunctions object.");

    hr = pBAFunctions->OnCreate(pArgs->pEngine, pArgs->pCommand);
    ExitOnFailure(hr, "Failed to call OnCreate on CRoofSpanBAFunctions.");

    pResults->pfnBAFunctionsProc = BalBaseBAFunctionsProc;
    pResults->pvBAFunctionsProcContext = pBAFunctions;
    pBAFunctions = NULL;

LExit:
    ReleaseObject(pBAFunctions);
    return hr;
}
