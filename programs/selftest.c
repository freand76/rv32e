/*
 * A self-checking test program. The processor computes every result from volatile
 * operands, and GCC computes the expected value at compile time from the same
 * constants: the compiler is the reference. The M extension's corner cases, which are
 * undefined in C, are checked with inline assembly against the values in the spec.
 *
 * Prints what failed and "PASS" or "FAIL", and returns the number of failures (the exit
 * code). Built for rv32e: there is no M, GCC calls libgcc for the multiplications and
 * divisions (the M corner cases are only checked when built with M).
 */

#include <stdint.h>

#define CONSOLE_TX (*(volatile uint8_t *)0x10000000)

static int failures;
static int checks;

static void putch(char c) { CONSOLE_TX = (uint8_t)c; }

static void puts_(const char *s) {
    while (*s) putch(*s++);
}

static void put_hex(uint32_t value) {
    puts_("0x");
    for (int shift = 28; shift >= 0; shift -= 4) putch("0123456789abcdef"[(value >> shift) & 15]);
}

static void put_dec(int32_t value) {
    char buffer[12];
    int n = 0;
    uint32_t u = value < 0 ? -(uint32_t)value : (uint32_t)value;
    do {
        buffer[n++] = (char)('0' + u % 10);
        u /= 10;
    } while (u);
    if (value < 0) putch('-');
    while (n) putch(buffer[--n]);
}

static void check(const char *what, int line, uint32_t got, uint32_t expected) {
    checks++;
    if (got != expected) {
        failures++;
        puts_("FAIL ");
        puts_(what);
        puts_(" line ");
        put_dec(line);
        puts_(": got ");
        put_hex(got);
        puts_(" expected ");
        put_hex(expected);
        putch('\n');
    }
}

#define CHECK(what, got, expected) check(what, __LINE__, (uint32_t)(got), (uint32_t)(expected))

/* Values the processor can't know in advance: read through a volatile */
static volatile int32_t sink;
static int32_t v(int32_t x) {
    sink = x;
    return sink;
}

/* All the operations on one pair of constants a, b */
#define PAIR(A, B)                                                                         \
    do {                                                                                   \
        const int32_t a = (A), b = (B);                                                    \
        const uint32_t ua = (uint32_t)a, ub = (uint32_t)b;                                 \
        int32_t ra = v(a), rb = v(b);                                                      \
        uint32_t rua = (uint32_t)ra, rub = (uint32_t)rb;                                   \
        CHECK("add", rua + rub, ua + ub);                                                  \
        CHECK("sub", rua - rub, ua - ub);                                                  \
        CHECK("xor", rua ^ rub, ua ^ ub);                                                  \
        CHECK("or", rua | rub, ua | ub);                                                   \
        CHECK("and", rua & rub, ua & ub);                                                  \
        CHECK("slt", ra < rb, a < b);                                                      \
        CHECK("sltu", rua < rub, ua < ub);                                                 \
        CHECK("bge", ra >= rb ? 7 : 9, a >= b ? 7 : 9);                                    \
        CHECK("beq", ra == rb ? 3 : 5, a == b ? 3 : 5);                                    \
        CHECK("sll", rua << (rub & 31), ua << (ub & 31));                                  \
        CHECK("srl", rua >> (rub & 31), ua >> (ub & 31));                                  \
        CHECK("sra", ra >> (rb & 31), a >> (b & 31));                                      \
        CHECK("mul", rua * rub, ua * ub);                                                  \
        CHECK("mulh", ((int64_t)ra * rb) >> 32, ((int64_t)a * b) >> 32);                   \
        CHECK("mulhu", ((uint64_t)rua * rub) >> 32, ((uint64_t)ua * ub) >> 32);            \
        CHECK("mulhsu", ((int64_t)ra * (int64_t)(uint64_t)rub) >> 32,                      \
              ((int64_t)a * (int64_t)(uint64_t)ub) >> 32);                                 \
        if (b != 0 && !(a == INT32_MIN && b == -1)) {                                      \
            CHECK("div", ra / rb, b != 0 ? a / (b ? b : 1) : 0);                           \
            CHECK("rem", ra % rb, b != 0 ? a % (b ? b : 1) : 0);                           \
        }                                                                                  \
        if (ub != 0) {                                                                     \
            CHECK("divu", rua / rub, ua / (ub ? ub : 1));                                  \
            CHECK("remu", rua % rub, ua % (ub ? ub : 1));                                  \
        }                                                                                  \
    } while (0)

#define ROW(A)                                                                             \
    PAIR(A, 0);                                                                            \
    PAIR(A, 1);                                                                            \
    PAIR(A, -1);                                                                           \
    PAIR(A, INT32_MAX);                                                                    \
    PAIR(A, INT32_MIN);                                                                    \
    PAIR(A, -12345);                                                                       \
    PAIR(A, 0x01234567)

static void test_alu(void) {
    ROW(0);
    ROW(1);
    ROW(-1);
    ROW(INT32_MAX);
    ROW(INT32_MIN);
    ROW(-12345);
    ROW(0x01234567);
}

#if defined(__riscv_mul) || defined(__riscv_m)
/* The M extension corner cases, from the spec's table */
#define RTYPE(op, a, b)                                                                    \
    ({                                                                                     \
        uint32_t result;                                                                   \
        __asm__ volatile(op " %0, %1, %2" : "=r"(result) : "r"(v(a)), "r"(v(b)));          \
        result;                                                                            \
    })

static void test_m_corner_cases(void) {
    CHECK("div by 0", RTYPE("div", 1234, 0), 0xffffffff);
    CHECK("divu by 0", RTYPE("divu", 1234, 0), 0xffffffff);
    CHECK("rem by 0", RTYPE("rem", -1234, 0), -1234);
    CHECK("remu by 0", RTYPE("remu", 1234, 0), 1234);
    CHECK("div overflow", RTYPE("div", INT32_MIN, -1), INT32_MIN);
    CHECK("rem overflow", RTYPE("rem", INT32_MIN, -1), 0);
    CHECK("div -7/2", RTYPE("div", -7, 2), -3);
    CHECK("rem -7%2", RTYPE("rem", -7, 2), -1);
    CHECK("mulhsu -1*max", RTYPE("mulhsu", -1, -1), 0xffffffff);
    CHECK("mulhu max*max", RTYPE("mulhu", -1, -1), 0xfffffffe);
}
#endif

/* Byte and halfword loads and stores, sign and zero extension */
static void test_memory(void) {
    static volatile uint32_t word;
    volatile uint8_t *bytes = (volatile uint8_t *)&word;
    volatile uint16_t *halves = (volatile uint16_t *)&word;
    word = 0;
    bytes[0] = 0x81;
    bytes[1] = 0x02;
    bytes[2] = 0xf3;
    bytes[3] = 0x74;
    CHECK("sb", word, 0x74f30281);
    CHECK("lb", *(volatile int8_t *)&bytes[0], -127);
    CHECK("lbu", bytes[0], 0x81);
    CHECK("lb byte 2", *(volatile int8_t *)&bytes[2], (int8_t)0xf3);
    CHECK("lh", *(volatile int16_t *)&halves[1], (int16_t)0x74f3);
    CHECK("lhu", halves[0], 0x0281);
    halves[1] = 0xbeef;
    CHECK("sh", word, 0xbeef0281);
    CHECK("lh negative", *(volatile int16_t *)&halves[1], (int16_t)0xbeef);
}

/* Calls, recursion and the stack */
static int fib(int n) { return n < 2 ? n : fib(n - 1) + fib(n - 2); }

/* Indirect calls (JALR) */
static int add3(int x) { return x + 3; }
static int twice(int x) { return 2 * x; }
static int negate(int x) { return -x; }

static void test_control(void) {
    CHECK("fib(12)", fib(v(12)), 144);
    int (*const functions[])(int) = {add3, twice, negate};
    int x = v(5);
    for (int i = 0; i < 3; i++) x = functions[v(i)](x);
    CHECK("function pointers", x, -16);
    int sum = 0;
    for (int i = 0; i < 8; i++) {
        switch (v(i)) {
            case 0: sum += 1; break;
            case 1: sum += 10; break;
            case 2: sum += 100; break;
            case 3: sum += 1000; break;
            case 4: sum += 3; break;
            case 5: sum += 30; break;
            case 6: sum += 300; break;
            default: sum += 3000; break;
        }
    }
    CHECK("switch", sum, 4444);
}

/* A sort, and CRC-32 of "123456789" (its check value is 0xcbf43926) */
static void test_algorithms(void) {
    int32_t data[16];
    uint32_t seed = v(12345);
    for (int i = 0; i < 16; i++) {
        seed = seed * 1103515245u + 12345u;
        data[i] = (int32_t)(seed >> 8) - 0x400000;
    }
    for (int i = 1; i < 16; i++) {
        int32_t key = data[i];
        int j = i - 1;
        while (j >= 0 && data[j] > key) {
            data[j + 1] = data[j];
            j--;
        }
        data[j + 1] = key;
    }
    int sorted = 1;
    for (int i = 1; i < 16; i++) sorted &= data[i - 1] <= data[i];
    CHECK("sort", sorted, 1);

    const char *text = "123456789";
    uint32_t crc = 0xffffffff;
    for (const char *p = text; *p; p++) {
        crc ^= (uint8_t)*p;
        for (int bit = 0; bit < 8; bit++) crc = (crc >> 1) ^ (0xedb88320u & -(crc & 1));
    }
    CHECK("crc32", ~crc, 0xcbf43926);
}

int main(void) {
    puts_("RV32 self test\n");
    test_alu();
#if defined(__riscv_mul) || defined(__riscv_m)
    test_m_corner_cases();
#endif
    test_memory();
    test_control();
    test_algorithms();
    put_dec(checks);
    puts_(" checks, ");
    put_dec(failures);
    puts_(failures ? " failures\nFAIL\n" : " failures\nPASS\n");
    return failures;
}
