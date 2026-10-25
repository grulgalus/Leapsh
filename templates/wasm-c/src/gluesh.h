/* ABI v1 pro WASM pluginy leapsh. Sestavení: leapsh-compile-plugin .  (potřebuje clang a lld) */
#ifndef LEAPSH_H
#define LEAPSH_H
#define LEAPSH_IMPORT(n) __attribute__((import_module("leapsh"), import_name(n)))
#define LEAPSH_EXPORT(n) __attribute__((export_name(n)))

LEAPSH_IMPORT("say")         extern void leapsh_say(const char *ptr, int len);
LEAPSH_IMPORT("warn")        extern void leapsh_warn(const char *ptr, int len);
LEAPSH_IMPORT("result")      extern void leapsh_result(const char *ptr, int len);
LEAPSH_IMPORT("setting_int") extern int  leapsh_setting_int(const char *key, int len, int dflt);
LEAPSH_IMPORT("time_ms")     extern long long leapsh_time_ms(void);
#endif
