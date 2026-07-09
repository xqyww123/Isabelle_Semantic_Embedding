/* Guards the invariant that vecgather.c documents: Isabelle/ML must still be able
 * to load this shared object even though it references CPython functions.
 *
 * Poly/ML loads it with dlopen(RTLD_LAZY) (libpolyml/polyffi.cpp:167) from a
 * process with no Python. Lazy binding defers *function* symbols, so the CPython
 * ones never resolve as long as ML only calls dot_q15 / top_k_q15. Data symbols
 * are a different matter: they are relocated eagerly even under RTLD_LAZY, so a
 * single Py_None or PyList_Type reference breaks the ML side at load time.
 *
 * This reproduces exactly what Poly/ML does, and then calls the C-only entry
 * points, so that mistake fails the build instead of Isabelle. */
#include <dlfcn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

int main(int argc, char **argv) {
  const char *path = argc > 1 ? argv[1] : "./libisabelle_vector.so";
  void *h = dlopen(path, RTLD_LAZY);
  if (!h) {
    fprintf(stderr, "FAIL: Isabelle/ML could not dlopen %s\n  %s\n", path, dlerror());
    fprintf(stderr, "  A Python *data* symbol (Py_None, PyList_Type, PyExc_*) most\n"
                    "  likely crept in; only Python *functions* may be referenced.\n");
    return 1;
  }
  int16_t (*dot)(const int16_t *, const int16_t *, size_t) =
      (int16_t (*)(const int16_t *, const int16_t *, size_t))dlsym(h, "dot_q15");
  void *topk = dlsym(h, "top_k_q15");
  if (!dot || !topk) {
    fprintf(stderr, "FAIL: dot_q15 / top_k_q15 not resolvable\n");
    return 1;
  }
  int16_t a[64], b[64];
  for (int i = 0; i < 64; i++) { a[i] = (int16_t)(i * 37); b[i] = (int16_t)(i * 11); }
  volatile int16_t s = dot(a, b, 64); /* actually bind and call, as ML would */
  (void)s;
  printf("PASS: dlopen(RTLD_LAZY) + dot_q15 work without Python in the process\n");
  dlclose(h);
  return 0;
}
