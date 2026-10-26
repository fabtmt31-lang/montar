/* SPDX-License-Identifier: GPL-3.0-or-later
 *
 * Lanceur Windows de montar (bin\montar.exe) : Python est chargé dans ce processus même,
 * qui porte donc le nom et l'icône de montar (barre des tâches, gestionnaire des tâches).
 * Équivaut à « pythonw.exe -X utf8 -I -m montar [arguments] » ; placé dans bin\ à côté de
 * python.exe, Python y retrouve sa bibliothèque (lib\python3.x) comme d'habitude.
 */
#include <Python.h>
#include <windows.h>
#include <shellapi.h>

static const wchar_t *FIXED[] = {L"-X", L"utf8", L"-I", L"-m", L"montar"};
#define NFIXED (sizeof(FIXED) / sizeof(FIXED[0]))

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR line, int show)
{
    (void)instance; (void)previous; (void)line; (void)show;
    int argc = 0;
    wchar_t **argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (argv == NULL)
        return 1;
    wchar_t **args = (wchar_t **)LocalAlloc(LPTR, sizeof(wchar_t *) * (argc + NFIXED + 1));
    if (args == NULL)
        return 1;
    int n = 0;
    args[n++] = argv[0];
    for (size_t i = 0; i < NFIXED; i++)
        args[n++] = (wchar_t *)FIXED[i];
    for (int i = 1; i < argc; i++)  /* projet .montar éventuel, options de montar */
        args[n++] = argv[i];
    args[n] = NULL;
    int code = Py_Main(n, args);
    LocalFree(args);
    LocalFree(argv);
    return code;
}
