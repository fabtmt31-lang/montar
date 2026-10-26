/* SPDX-License-Identifier: GPL-3.0-or-later
 *
 * montar.exe à la racine du dossier (version portable) : lance bin\montar.exe avec les mêmes
 * arguments, pour qu'on le trouve sans fouiller dans bin\.
 */
#include <windows.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR line, int show)
{
    (void)instance; (void)previous; (void)show;
    wchar_t path[MAX_PATH];
    DWORD len = GetModuleFileNameW(NULL, path, MAX_PATH);
    if (len == 0 || len >= MAX_PATH)
        return 1;
    wchar_t *slash = wcsrchr(path, L'\\');
    if (slash == NULL)
        return 1;
    slash[1] = L'\0';
    wchar_t target[MAX_PATH];
    if (_snwprintf(target, MAX_PATH, L"%lsbin\\montar.exe", path) < 0)
        return 1;
    /* ligne de commande : programme cible puis arguments reçus (déjà mis entre guillemets) */
    size_t size = wcslen(target) + wcslen(line) + 4;
    wchar_t *command = (wchar_t *)LocalAlloc(LPTR, size * sizeof(wchar_t));
    if (command == NULL)
        return 1;
    _snwprintf(command, size, L"\"%ls\" %ls", target, line);
    STARTUPINFOW si = {sizeof(si)};
    PROCESS_INFORMATION pi;
    BOOL ok = CreateProcessW(target, command, NULL, NULL, FALSE, 0, NULL, path, &si, &pi);
    LocalFree(command);
    if (!ok)
        return 1;
    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
