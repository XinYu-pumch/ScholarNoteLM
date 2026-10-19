/* Finder entry point: launch only the interpreter shipped in this app. */
#include <mach-o/dyld.h>
#include <limits.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>

int main(int argc, char **argv) {
    char executable[PATH_MAX], resolved[PATH_MAX];
    uint32_t size = sizeof(executable);
    if (_NSGetExecutablePath(executable, &size) || !realpath(executable, resolved)) return 1;
    for (int i = 0; i < 3; i++) {
        char *slash = strrchr(resolved, '/');
        if (!slash) return 1;
        *slash = 0;
    }
    char *python, *script;
    if (asprintf(&python, "%s/Contents/Resources/payload/runtimes/python/cpython-3.12.9-macos-aarch64-none/bin/python3.12", resolved) < 0 ||
        asprintf(&script, "%s/Contents/Resources/payload/scripts/standalone/macos-bootstrap.py", resolved) < 0) return 1;
    char **args = calloc((size_t)argc + 8, sizeof(char *));
    if (!args) return 1;
    args[0] = python; args[1] = "-I"; args[2] = "-S"; args[3] = "-B"; args[4] = script;
    args[5] = "--bundle"; args[6] = resolved;
    for (int i = 1; i < argc; i++) args[i + 6] = argv[i];
    execv(python, args);
    perror("ScholarNoteLM bundled Python could not start");
    return 1;
}
