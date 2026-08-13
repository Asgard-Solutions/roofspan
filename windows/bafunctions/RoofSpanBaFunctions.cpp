// RoofSpan Office — BAFunctions native hook for the WiX v5 Burn bundle (installer\bundle.wxs).
//
// Single responsibility: ensure the Hidden Burn variable `PgSuperPassword` holds the PostgreSQL
// superuser/bootstrap password BEFORE the chain executes — recovered from machine-protected (DPAPI)
// storage on a rerun/retry, or freshly CSPRNG-generated (and persisted) on a genuinely new install. This
// keeps the stock WixStandardBootstrapperApplication UI (referenced via bal:BAFunctions="yes").
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

// --- Retry-safe DPAPI (LOCAL_MACHINE) persistence of the bootstrap superpassword -------------------
// If PostgreSQL installs but the RoofSpan MSI later rolls back, PostgreSQL stays (Permanent) but the
// generated superpassword would otherwise be lost. We persist it machine-protected so a rerun of
// RoofSpanSetup.exe recovers it. RoofSpanBootstrap.exe deletes this file once provisioning succeeds.
static const BYTE ROOFSPAN_DPAPI_ENTROPY[] = "RoofSpan.PgBootstrap.v1"; // additional entropy (NOT the secret)

static HRESULT RoofSpanSecretPath(__out_ecount_z(cch) LPWSTR wzPath, __in size_t cch)
{
    HRESULT hr = S_OK;
    WCHAR wzProgramData[MAX_PATH] = { 0 };
    WCHAR wzDir[MAX_PATH] = { 0 };

    if (FAILED(::SHGetFolderPathW(NULL, CSIDL_COMMON_APPDATA, NULL, SHGFP_TYPE_CURRENT, wzProgramData)))
    {
        ExitFunction1(hr = E_FAIL);
    }
    hr = ::StringCchPrintfW(wzDir, countof(wzDir), L"%s\\RoofSpan\\bootstrap", wzProgramData);
    ExitOnFailure(hr, "format bootstrap dir");
    ::SHCreateDirectoryExW(NULL, wzDir, NULL); // best-effort; ignore ERROR_ALREADY_EXISTS
    hr = ::StringCchPrintfW(wzPath, cch, L"%s\\pgsuper.bin", wzDir);

LExit:
    return hr;
}

static HRESULT PersistSecret(__in LPCWSTR wzPw)
{
    HRESULT hr = S_OK;
    WCHAR wzPath[MAX_PATH] = { 0 };
    DATA_BLOB in = { 0 }, entropy = { 0 }, out = { 0 };
    HANDLE hFile = INVALID_HANDLE_VALUE;
    DWORD cbWritten = 0;

    hr = RoofSpanSecretPath(wzPath, countof(wzPath));
    ExitOnFailure(hr, "resolve secret path");

    in.pbData = (BYTE*)wzPw;
    in.cbData = (DWORD)((wcslen(wzPw) + 1) * sizeof(WCHAR));
    entropy.pbData = (BYTE*)ROOFSPAN_DPAPI_ENTROPY;
    entropy.cbData = sizeof(ROOFSPAN_DPAPI_ENTROPY);

    if (!::CryptProtectData(&in, L"RoofSpan PG bootstrap", &entropy, NULL, NULL,
                            CRYPTPROTECT_LOCAL_MACHINE, &out))
    {
        ExitWithLastError(hr, "CryptProtectData failed");
    }

    hFile = ::CreateFileW(wzPath, GENERIC_WRITE, 0, NULL, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (INVALID_HANDLE_VALUE == hFile)
    {
        ExitWithLastError(hr, "create bootstrap secret file");
    }
    if (!::WriteFile(hFile, out.pbData, out.cbData, &cbWritten, NULL) || cbWritten != out.cbData)
    {
        ExitWithLastError(hr, "write bootstrap secret file");
    }

LExit:
    if (INVALID_HANDLE_VALUE != hFile) ::CloseHandle(hFile);
    if (out.pbData) ::LocalFree(out.pbData);
    return hr;
}

static HRESULT RecoverSecret(__out_ecount_z(cch) LPWSTR wzOut, __in size_t cch)
{
    HRESULT hr = S_OK;
    WCHAR wzPath[MAX_PATH] = { 0 };
    HANDLE hFile = INVALID_HANDLE_VALUE;
    DATA_BLOB in = { 0 }, entropy = { 0 }, out = { 0 };
    BYTE* pbFile = NULL;
    DWORD cbFile = 0, cbRead = 0;

    *wzOut = L'\0';
    hr = RoofSpanSecretPath(wzPath, countof(wzPath));
    ExitOnFailure(hr, "resolve secret path");

    hFile = ::CreateFileW(wzPath, GENERIC_READ, FILE_SHARE_READ, NULL, OPEN_EXISTING,
                          FILE_ATTRIBUTE_NORMAL, NULL);
    if (INVALID_HANDLE_VALUE == hFile)
    {
        ExitFunction1(hr = HRESULT_FROM_WIN32(ERROR_FILE_NOT_FOUND)); // no persisted secret (normal fresh install)
    }
    cbFile = ::GetFileSize(hFile, NULL);
    if (INVALID_FILE_SIZE == cbFile || 0 == cbFile) ExitFunction1(hr = E_FAIL);

    pbFile = (BYTE*)::LocalAlloc(LPTR, cbFile);
    ExitOnNull(pbFile, hr, E_OUTOFMEMORY, "alloc secret buffer");
    if (!::ReadFile(hFile, pbFile, cbFile, &cbRead, NULL) || cbRead != cbFile)
    {
        ExitWithLastError(hr, "read bootstrap secret file");
    }

    in.pbData = pbFile;
    in.cbData = cbFile;
    entropy.pbData = (BYTE*)ROOFSPAN_DPAPI_ENTROPY;
    entropy.cbData = sizeof(ROOFSPAN_DPAPI_ENTROPY);
    if (!::CryptUnprotectData(&in, NULL, &entropy, NULL, NULL, CRYPTPROTECT_LOCAL_MACHINE, &out))
    {
        ExitWithLastError(hr, "CryptUnprotectData failed");
    }
    hr = ::StringCchCopyW(wzOut, cch, (LPCWSTR)out.pbData);

LExit:
    if (INVALID_HANDLE_VALUE != hFile) ::CloseHandle(hFile);
    if (pbFile) ::LocalFree(pbFile);
    if (out.pbData) { ::SecureZeroMemory(out.pbData, out.cbData); ::LocalFree(out.pbData); }
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

        // 2) Recover a previously persisted bootstrap credential (retry-safe): covers rerun after an MSI
        //    rollback AND the case where RoofSpanPostgreSQL is already installed. Machine-protected (DPAPI).
        hr = RecoverSecret(wzPassword, countof(wzPassword));
        if (SUCCEEDED(hr) && wzPassword[0])
        {
            hr = BalSetStringVariable(ROOFSPAN_PG_SUPERPASSWORD, wzPassword, FALSE);
            if (FAILED(hr)) { *pfCancel = TRUE; ExitFunction(); }
            BalLog(BOOTSTRAPPER_LOG_LEVEL_STANDARD, "RoofSpan: recovered persisted PostgreSQL bootstrap credential (value redacted).");
            ExitFunction();
        }
        hr = S_OK; // absence of a persisted secret is normal on a genuinely fresh install

        // 3) RoofSpan-managed PostgreSQL already installed but NO recoverable credential -> fail closed.
        //    A new random password could not authenticate to the existing instance, and we must NOT delete
        //    the customer's PostgreSQL/data. Surface a clear, non-secret cause instead of stranding silently.
        if (SUCCEEDED(BalGetNumericVariable(ROOFSPAN_PG_PRESENT, &llPresent)) && 1 == llPresent)
        {
            BalLog(BOOTSTRAPPER_LOG_LEVEL_ERROR,
                   "RoofSpan: RoofSpanPostgreSQL is present but its bootstrap credential could not be recovered; cancelling.");
            *pfCancel = TRUE;
            ExitFunction1(hr = E_FAIL);
        }

        // 4) Fresh RoofSpan-managed install: generate the CSPRNG bootstrap credential, PERSIST it (so a
        //    later rollback is recoverable), then hand it to the chain.
        hr = GenerateHexPassword(ROOFSPAN_PG_PW_BYTES, wzPassword, countof(wzPassword));
        if (FAILED(hr))
        {
            // FAIL CLOSED: never let WixStdBA proceed into EDB with an empty --superpassword.
            BalLog(BOOTSTRAPPER_LOG_LEVEL_ERROR, "RoofSpan: failed to generate PostgreSQL bootstrap credential (0x%x); cancelling.", hr);
            *pfCancel = TRUE;
            ExitFunction();
        }

        hr = PersistSecret(wzPassword); // must persist BEFORE the chain so a rollback is recoverable
        if (FAILED(hr))
        {
            BalLog(BOOTSTRAPPER_LOG_LEVEL_ERROR, "RoofSpan: failed to persist PostgreSQL bootstrap credential (0x%x); cancelling.", hr);
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

        BalLog(BOOTSTRAPPER_LOG_LEVEL_STANDARD, "RoofSpan: generated + persisted fresh PostgreSQL bootstrap credential (value redacted).");

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
