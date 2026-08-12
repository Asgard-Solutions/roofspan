#pragma once
// RoofSpan BAFunctions — precompiled header. Mirrors the WiX v5 BAFunctions sample include set.

#include <windows.h>
#include <bcrypt.h>
#include <msiquery.h>
#include <objbase.h>
#include <shlwapi.h>
#include <stdlib.h>
#include <strsafe.h>

// WiX v5 native SDK headers (from the WixToolset.BootstrapperApplicationApi /
// WixToolset.WixStandardBootstrapperApplicationFunctionApi + WixToolset.DUtil NuGet packages).
#include "dutil.h"
#include "strutil.h"
#include "regutil.h"

#include "BootstrapperApplicationBase.h"

#include "BAFunctions.h"
#include "IBAFunctions.h"

HRESULT WINAPI CreateBAFunctions(
    __in HMODULE hModule,
    __in const BA_FUNCTIONS_CREATE_ARGS* pArgs,
    __inout BA_FUNCTIONS_CREATE_RESULTS* pResults
    );
