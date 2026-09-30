// Dante AutoLab bootstrap.
// Native Win64, no CRT, read-only against user-owned local game files.
// This file intentionally contains no proprietary game code or assets.

typedef unsigned char u8;
typedef unsigned int u32;
typedef unsigned long DWORD;
typedef int BOOL;
typedef long long i64;
typedef unsigned long long u64;
typedef unsigned long long SIZE_T;
typedef void* HANDLE;
typedef void* LPVOID;
typedef const void* LPCVOID;
typedef const char* LPCSTR;
typedef char* LPSTR;
typedef struct { i64 QuadPart; } LARGE_INTEGER;

#define WINAPI __stdcall
#define DLLIMPORT __declspec(dllimport)
#define INVALID_HANDLE_VALUE ((HANDLE)(i64)-1)
#define GENERIC_READ 0x80000000UL
#define GENERIC_WRITE 0x40000000UL
#define FILE_SHARE_READ 0x00000001UL
#define OPEN_EXISTING 3UL
#define CREATE_ALWAYS 2UL
#define FILE_ATTRIBUTE_NORMAL 0x00000080UL
#define FILE_BEGIN 0UL
#define MB_OK 0x00000000UL
#define MB_ICONINFORMATION 0x00000040UL
#define MB_ICONERROR 0x00000010UL

DLLIMPORT HANDLE WINAPI CreateFileA(LPCSTR,DWORD,DWORD,LPVOID,DWORD,DWORD,HANDLE);
DLLIMPORT BOOL WINAPI ReadFile(HANDLE,LPVOID,DWORD,DWORD*,LPVOID);
DLLIMPORT BOOL WINAPI WriteFile(HANDLE,LPCVOID,DWORD,DWORD*,LPVOID);
DLLIMPORT BOOL WINAPI CloseHandle(HANDLE);
DLLIMPORT BOOL WINAPI SetFilePointerEx(HANDLE,LARGE_INTEGER,LARGE_INTEGER*,DWORD);
DLLIMPORT BOOL WINAPI GetFileSizeEx(HANDLE,LARGE_INTEGER*);
DLLIMPORT BOOL WINAPI CreateDirectoryA(LPCSTR,LPVOID);
DLLIMPORT int WINAPI MessageBoxA(void*,LPCSTR,LPCSTR,unsigned int);
DLLIMPORT int WINAPI wsprintfA(LPSTR,LPCSTR,...);

int _fltused = 0;

static HANDLE g_log = 0;
static u8 g_bigh_head[65536];

static u32 slen(const char* s) {
    u32 n = 0;
    while (s && s[n]) n++;
    return n;
}
static void write_raw(HANDLE h, const char* s) {
    DWORD w = 0;
    if (h && h != INVALID_HANDLE_VALUE) WriteFile(h, s, slen(s), &w, 0);
}
static void log_line(const char* s) {
    write_raw(g_log, s);
    write_raw(g_log, "\r\n");
}
static u32 be32(const u8* p) {
    return ((u32)p[0] << 24) | ((u32)p[1] << 16) | ((u32)p[2] << 8) | p[3];
}
static int seek_read(HANDLE f, u64 off, void* dst, u32 size) {
    LARGE_INTEGER li;
    DWORD got = 0;
    li.QuadPart = (i64)off;
    if (!SetFilePointerEx(f, li, 0, FILE_BEGIN)) return 0;
    if (!ReadFile(f, dst, size, &got, 0)) return 0;
    return got == size;
}

static int inspect_bigh(const char* path, int require_frontend_global) {
    HANDLE f;
    DWORD got = 0;
    LARGE_INTEGER size;
    char line[512];
    u32 count, need, i;
    int frontend_found = 0;

    f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, 0, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
    if (f == INVALID_HANDLE_VALUE) {
        wsprintfA(line, "[CHECK] missing required file: %s", path);
        log_line(line);
        return 0;
    }

    size.QuadPart = 0;
    GetFileSizeEx(f, &size);
    if (!ReadFile(f, g_bigh_head, sizeof(g_bigh_head), &got, 0) || got < 32) {
        wsprintfA(line, "[CHECK] cannot read BIGH header: %s", path);
        log_line(line);
        CloseHandle(f);
        return 0;
    }

    if (!(g_bigh_head[0]=='B' && g_bigh_head[1]=='I' && g_bigh_head[2]=='G' && g_bigh_head[3]=='H')) {
        wsprintfA(line, "[CHECK] BIGH magic missing: %s", path);
        log_line(line);
        CloseHandle(f);
        return 0;
    }

    count = be32(g_bigh_head + 8);
    need = 16 + count * 12;
    if (count == 0 || count > 10000 || need > got) {
        wsprintfA(line, "[CHECK] invalid BIGH index: %s count=%u", path, count);
        log_line(line);
        CloseHandle(f);
        return 0;
    }

    wsprintfA(line, "[PASS] %s BIGH index valid; entries=%u bytes=%u", path, count, need);
    log_line(line);

    if (require_frontend_global) {
        for (i = 0; i < count; i++) {
            const u8* e = g_bigh_head + 16 + i * 12;
            u32 key = be32(e + 8);
            if (key == 0xF9E85989U) {
                u32 off = be32(e + 0);
                u32 stored = be32(e + 4);
                u8 probe[16];
                if (stored >= 16 && seek_read(f, off, probe, 16)) {
                    frontend_found = 1;
                    wsprintfA(line,
                        "[PASS] frontend\\frontend_global.str resolved entry=%u off=0x%08X size=%u",
                        i, off, stored);
                    log_line(line);
                }
                break;
            }
        }
        if (!frontend_found) log_line("[CHECK] frontend\\frontend_global.str key 0xF9E85989 not resolved");
    }

    CloseHandle(f);
    return require_frontend_global ? frontend_found : 1;
}

static void inspect_optional(const char* path) {
    HANDLE f;
    LARGE_INTEGER size;
    char line[384];
    f = CreateFileA(path, GENERIC_READ, FILE_SHARE_READ, 0, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, 0);
    if (f == INVALID_HANDLE_VALUE) {
        wsprintfA(line, "[INFO] optional input not beside AutoLab: %s", path);
        log_line(line);
        return;
    }
    size.QuadPart = 0;
    if (GetFileSizeEx(f, &size)) {
        wsprintfA(line, "[PASS] optional input discovered: %s size=%u", path, (u32)size.QuadPart);
        log_line(line);
    } else {
        wsprintfA(line, "[PASS] optional input discovered: %s", path);
        log_line(line);
    }
    CloseHandle(f);
}

static int run(void) {
    int ok0, ok1;
    CreateDirectoryA("Dante_AutoLab_Result", 0);
    g_log = CreateFileA(
        "Dante_AutoLab_Result\\Dante_AutoLab_Summary.txt",
        GENERIC_WRITE, 0, 0, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, 0);

    if (g_log == INVALID_HANDLE_VALUE) return 0;

    log_line("DANTE AUTOLAB v0.1 - BOOTSTRAP / REGRESSION GATE");
    log_line("================================================");
    log_line("");
    log_line("Read-only native Win64 probe. No default.xex is loaded or executed.");
    log_line("No proprietary game assets are written into the repository or distributed by AutoLab.");
    log_line("");

    ok0 = inspect_bigh("bigfile0.viv", 1);
    ok1 = inspect_bigh("bigfile1.viv", 0);
    inspect_optional("default.xex");
    inspect_optional("default.xexp");

    log_line("");
    log_line("FROZEN CONTRACT CHECKPOINT");
    log_line("--------------------------");
    log_line("[INFO] RUN00 cartography + RUN01 T01-T24 are tracked as frozen research contracts.");
    log_line("[INFO] T25 corpus scan remains CHECK: literal ownership mapped; exact upstream function owner not yet proven.");
    log_line("[NEXT] AutoLab stage T26: deep ActionScript/native/Lua/localization upstream tracing.");
    log_line("");

    if (ok0 && ok1) {
        log_line("STATUS: PASS");
        log_line("AutoLab bootstrap is ready for chained research stages.");
    } else {
        log_line("STATUS: CHECK");
        log_line("Place bigfile0.viv and bigfile1.viv beside DanteAutoLab.exe and run again.");
    }

    CloseHandle(g_log);
    return ok0 && ok1;
}

void WinMainCRTStartup(void) {
    int ok = run();
    MessageBoxA(
        0,
        ok
          ? "AutoLab bootstrap PASS.\nResult: Dante_AutoLab_Result\\Dante_AutoLab_Summary.txt"
          : "AutoLab bootstrap CHECK.\nSee Dante_AutoLab_Result\\Dante_AutoLab_Summary.txt",
        "Dante AutoLab v0.1",
        ok ? (MB_OK | MB_ICONINFORMATION) : (MB_OK | MB_ICONERROR));
}
