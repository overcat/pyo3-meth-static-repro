"""
PyO3 >= 0.28 sets METH_STATIC on every module-level `#[pyfunction]`.

This script compares an ordinary `#[pyfunction]` with the same function declared
with `pass_module`, which does not get the flag. It does this for each calling
convention that PyO3 uses. It prints `ml_flags` and `__self__` of both functions
and the time per call. It exits with status 1 if an ordinary function has
METH_STATIC. README.md explains the cause.
"""

import ctypes
import sys
import time

import meth_static_repro as m

METH = {
    0x0001: "METH_VARARGS",
    0x0002: "METH_KEYWORDS",
    0x0004: "METH_NOARGS",
    0x0008: "METH_O",
    0x0010: "METH_CLASS",
    0x0020: "METH_STATIC",
    0x0040: "METH_COEXIST",
    0x0080: "METH_FASTCALL",
    0x0200: "METH_METHOD",
}
METH_STATIC = 0x0020

# (row label, suffix of the two function names, arguments they are called with)
CASES = [
    ("no parameters", "noargs", ""),
    ("one parameter", "onearg", "None"),
    ("**kwargs", "kwargs", ""),
]

LOOP = """\
def loop(function, n):
    for _ in range(n):
        function({arguments})
"""


def ml_flags(function):
    """Return the `ml_flags` of the function's `PyMethodDef`. This calls the C
    API function `PyCFunction_GetFlags`, so it requires CPython."""
    get_flags = ctypes.pythonapi.PyCFunction_GetFlags
    get_flags.argtypes = [ctypes.py_object]
    get_flags.restype = ctypes.c_int
    return get_flags(function)


def make_loop(arguments):
    """Return a new loop function. Each timed function gets its own loop, so
    that each call site has its own inline cache and is specialized separately."""
    namespace = {}
    exec(LOOP.format(arguments=arguments), namespace)
    return namespace["loop"]


def time_pair(functions, arguments, n=2_000_000, rounds=7):
    """Return the best time per call in ns for each function. The rounds
    alternate between the functions."""
    loops = [make_loop(arguments) for _ in functions]
    best = [float("inf")] * len(functions)
    for _ in range(rounds):
        for i, (loop, function) in enumerate(zip(loops, functions)):
            start = time.perf_counter_ns()
            loop(function, n)
            best[i] = min(best[i], (time.perf_counter_ns() - start) / n)
    return best


def main():
    if sys.implementation.name != "cpython":
        sys.exit("this script calls CPython's C API through ctypes.pythonapi; run it with CPython")
    gil = getattr(sys, "_is_gil_enabled", lambda: True)()
    print(f"CPython {sys.version.split()[0]}" + ("" if gil else " (free-threaded)"))
    print()
    print(f"{'':15}{'plain #[pyfunction]':32}#[pyfunction(pass_module)]")
    columns = f"{'ml_flags':10}{'__self__':10}{'ns/call':12}"
    print(f"{'':15}{columns}{columns}difference")

    legend = {METH_STATIC: "METH_STATIC"}
    static = False
    for label, suffix, arguments in CASES:
        functions = [getattr(m, f"plain_{suffix}"), getattr(m, f"with_module_{suffix}")]
        times = time_pair(functions, arguments)
        row = f"{label:15}"
        for function, ns in zip(functions, times):
            flags = ml_flags(function)
            owner = "None" if function.__self__ is None else type(function.__self__).__name__
            row += f"{flags:#06x}    {owner:10}{ns:7.1f}     "
        legend[ml_flags(functions[1])] = "|".join(
            name for bit, name in METH.items() if ml_flags(functions[1]) & bit
        )
        static = static or bool(ml_flags(functions[0]) & METH_STATIC)
        plain, with_module = times
        # `+ 0.0` turns a rounded -0.0 into 0.0
        difference = round(plain - with_module, 1) + 0.0
        percent = round((plain / with_module - 1) * 100) + 0.0
        print(f"{row}{difference:+5.1f} ns {percent:+4.0f}%")

    print()
    for flags, names in legend.items():
        print(f"{flags:#06x} = {names}")
    print()
    if static:
        print("BUG: the plain `#[pyfunction]`s are METH_STATIC")
        sys.exit(1)
    print("OK: the plain `#[pyfunction]`s are not METH_STATIC")


if __name__ == "__main__":
    main()
