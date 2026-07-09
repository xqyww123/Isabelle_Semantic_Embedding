/* Batch extraction of raw buffer addresses from a list of Python objects.
 *
 * topk must tell the SIMD kernel where each candidate vector lives inside the
 * LMDB mmap. A memoryview does not expose its pointer, so Python's only recourse
 * is to wrap each one -- np.frombuffer(mv, uint8).ctypes.data -- purely to read
 * the address back out. That costs ~2.9us per key; over a 10^5 domain it is
 * ~230ms of pure overhead, more than the SIMD scan it feeds. The same loop here
 * runs at ~0.1us per key.
 *
 * ==========================================================================
 * INVARIANT: this file may reference Python *functions* but never Python *data*.
 * ==========================================================================
 * Tools/simd_vector.ML dlopens this same shared object from Isabelle/ML, which
 * has no Python in the process. Poly/ML uses RTLD_LAZY (libpolyml/polyffi.cpp:167),
 * so undefined *function* symbols are fine -- they resolve on first call, and ML
 * only ever calls dot_q15 / top_k_q15. But lazy binding does not cover data
 * relocations: one reference to Py_None (i.e. _Py_NoneStruct) or PyList_Type and
 * the ML-side dlopen fails outright at load. Verified both ways; test_ml_dlopen
 * guards it at build time.
 *
 * Hence: no Py_None (a missing record is detected by PyObject_GetBuffer failing,
 * which is what None does), and no PyList_Check (PyList_Size reports the error).
 * Nothing links libpython either -- the interpreter resolves the symbols, exactly
 * as it does for any extension module -- so this costs no size.
 *
 * The caller keeps the buffers alive and the LMDB read transaction open: the
 * addresses point into that transaction's MVCC snapshot of the mmap.
 *
 * CALL THIS THROUGH ctypes.PyDLL, NEVER ctypes.CDLL. CDLL drops the GIL for the
 * duration of the foreign call -- which is exactly why the SIMD kernel is bound
 * through it -- and touching the Python API without the GIL segfaults as soon as
 * anything allocates (PyObject_GetBuffer on a None raises, and raising allocates).
 */
#include <Python.h>
#include <stdint.h>

/* items    : list whose elements are buffer-exporting objects (memoryviews from a
 *            buffers=True transaction), or None where the key had no record.
 * expected : required byte length. Anything else is counted as skipped: a stale
 *            float32 record is D*4 bytes and would otherwise be read as a
 *            truncated vector, silently.
 * out_addrs[j], out_keep[j] : address, and index into `items`, of the j-th kept item.
 * out_missing[j]            : index into `items` of the j-th item without a buffer.
 * counts                    : {kept, missing, skipped}.  All three out arrays must
 *                             have room for len(items).
 * Returns 0, or -1 if `items` is not a list. */
int gather_addrs(PyObject *items, Py_ssize_t expected,
                 uintptr_t *out_addrs, int32_t *out_keep, int32_t *out_missing,
                 int32_t *counts) {
  const Py_ssize_t n = PyList_Size(items);
  if (n < 0) { PyErr_Clear(); return -1; }
  int32_t kept = 0, missing = 0, skipped = 0;
  Py_buffer view;
  for (Py_ssize_t i = 0; i < n; i++) {
    PyObject *o = PyList_GetItem(items, i); /* borrowed */
    if (o == NULL) { PyErr_Clear(); skipped++; continue; }
    if (PyObject_GetBuffer(o, &view, PyBUF_SIMPLE) != 0) {
      PyErr_Clear();                 /* None, or anything else without a buffer */
      out_missing[missing++] = (int32_t)i;
      continue;
    }
    if (view.len != expected) { PyBuffer_Release(&view); skipped++; continue; }
    out_addrs[kept] = (uintptr_t)view.buf;
    out_keep[kept] = (int32_t)i;
    kept++;
    /* Releasing the view leaves the address valid: the memoryview still holds the
       mmap, which outlives the read transaction the caller keeps open. */
    PyBuffer_Release(&view);
  }
  counts[0] = kept; counts[1] = missing; counts[2] = skipped;
  return 0;
}
