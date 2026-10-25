/* WASM plugin pro leapsh napsaný v C (bez libc). Příkaz __NAME__, událost command_after, segment {__NAME__}. */
#include "leapsh.h"

static unsigned char heap[1 << 16];
static unsigned top = 0;
static unsigned counter = 0;

/* alokátor pro řetězce od shellu; shell je uvolňuje v opačném pořadí => stačí zásobník */
LEAPSH_EXPORT("leapsh_alloc") void *leapsh_alloc(int n) {
    unsigned size = ((unsigned)n + 7u) & ~7u;
    if (top + size > sizeof(heap)) return 0;
    void *p = heap + top;
    top += size;
    return p;
}

LEAPSH_EXPORT("leapsh_free") void leapsh_free(void *p, int n) {
    unsigned off = (unsigned)((unsigned char *)p - heap);
    if (off + (((unsigned)n + 7u) & ~7u) == top) top = off;
}

/* událost: vrať 0 (pokračuj) nebo 1 (zruš) */
LEAPSH_EXPORT("leapsh_event") int leapsh_event(const char *name, int nlen, const char *json, int jlen) {
    counter++;
    return 0;
}

/* příkaz: návratová hodnota = výstupní kód */
LEAPSH_EXPORT("leapsh_command") int leapsh_command(const char *name, int nlen, const char *args, int alen) {
    static const char msg[] = "Ahoj z WASM pluginu napsaného v C!";
    leapsh_say(msg, sizeof(msg) - 1);
    return 0;
}

/* segment promptu: text vrať přes leapsh_result() */
LEAPSH_EXPORT("leapsh_segment") int leapsh_segment(const char *name, int nlen) {
    char buf[12];
    int i = sizeof(buf);
    unsigned n = counter;
    do { buf[--i] = (char)('0' + n % 10); n /= 10; } while (n);
    leapsh_result(buf + i, (int)sizeof(buf) - i);
    return 0;
}
