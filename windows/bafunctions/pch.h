#pragma once
// RoofSpan BAFunctions — precompiled header. Mirrors the OFFICIAL WiX v5 BAFunctions include set + order
// so every native type required by the BAL/BAFunctions headers is defined first. In particular
// BootstrapperApplicationBase.h -> balinfo.h uses STRINGDICT_HANDLE, which is defined by dictutil.h, and
// pulls thmutil (hence gdiplus.h / CommCtrl.h). These MUST precede the BootstrapperApplication/BAL headers.

#include <windows.h>

#pragma warning(push)
#pragma warning(disable:4458) // declaration of 'xxx' hides class member (from gdiplus.h)
#include <gdiplus.h>
#pragma warning(pop)

#include <bcrypt.h>       // BCryptGenRandom (CSPRNG for the PostgreSQL superuser password)
#include <msiquery.h>
#include <objbase.h>
#include <shlobj.h>
#include <shlwapi.h>
#include <stdlib.h>
#include <strsafe.h>
#include <CommCtrl.h>

// WiX v5 DUtil headers — must be included (in this order) BEFORE the BAL/BAFunctions headers so all
// handle/type definitions (e.g. STRINGDICT_HANDLE from dictutil.h) exist when balinfo.h is parsed.
#include "dutil.h"
#include "dictutil.h"
#include "fileutil.h"
#include "pathutil.h"
#include "strutil.h"
#include "regutil.h"

// WiX v5 Bootstrapper Application base + BAFunctions API (WixToolset.BootstrapperApplicationApi 5.0.2 +
// WixToolset.WixStandardBootstrapperApplicationFunctionApi 5.0.2).
#include "BootstrapperApplicationBase.h"

#include "BAFunctions.h"
#include "IBAFunctions.h"

HRESULT WINAPI CreateBAFunctions(
    __in HMODULE hModule,
    __in const BA_FUNCTIONS_CREATE_ARGS* pArgs,
    __inout BA_FUNCTIONS_CREATE_RESULTS* pResults
    );
