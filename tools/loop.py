"""
Calls one of the functions in a loop:

    python tools/loop.py plain_onearg [calls]

The name is one of `plain_` or `with_module_` followed by `noargs`, `onearg` or
`kwargs`.
"""

import ctypes
import os
import sys

import meth_static_repro as m


def loop_without_arguments(function, n):
    for _ in range(n):
        function()


def loop_with_one_argument(function, n):
    for _ in range(n):
        function(None)


name = sys.argv[1]
calls = int(sys.argv[2]) if len(sys.argv) > 2 else 3000
function = getattr(m, name)

# This block is for tools/count_instructions.py. It writes the address of the
# function's C entry point to a file. The C API function
# `PyCFunction_GetFunction` returns this address. The block then calls
# getppid(), and gdb stops at that system call. gdb cannot use a symbol name,
# because the linker merges functions that have identical code. This block
# requires CPython.
entry_file = os.environ.get("METH_STATIC_REPRO_ENTRY_FILE")
if entry_file:
    get_function = ctypes.pythonapi.PyCFunction_GetFunction
    get_function.argtypes = [ctypes.py_object]
    get_function.restype = ctypes.c_void_p
    with open(entry_file, "w") as file:
        file.write(hex(get_function(function)))
    os.getppid()

loop = loop_with_one_argument if name.endswith("_onearg") else loop_without_arguments
loop(function, calls)
