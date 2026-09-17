"""
Counts the machine instructions of loop iterations by single-stepping them
under gdb, after a warm-up. The result is deterministic, and no perf
permissions are required. The per-symbol counts require a python binary that
has symbols.

    gdb -q -batch -x tools/count_instructions.py --args python tools/loop.py plain_onearg
    gdb -q -batch -x tools/count_instructions.py --args python tools/loop.py with_module_onearg

The last argument is any function name that `tools/loop.py` accepts.
"""

import collections
import os
import re
import tempfile

import gdb

WARMUP = 2000  # calls to skip first, so that the call site has been specialized
ITERATIONS = 110  # loop iterations to single-step

function = gdb.parameter("args").split()[1]


def pc():
    return int(gdb.parse_and_eval("$pc"))


def in_extension(address):
    return "meth_static_repro" in (gdb.solib_name(address) or "")


gdb.execute("set pagination off")
gdb.execute("set confirm off")

# `tools/loop.py` writes the address of the function's C entry point to this
# file and then calls getppid(). The first `run` stops at that system call.
entry_file = tempfile.NamedTemporaryFile(prefix="ml_meth-", delete=False).name
gdb.execute(f"set environment METH_STATIC_REPRO_ENTRY_FILE {entry_file}")
gdb.execute("catch syscall getppid")
gdb.execute("run")
with open(entry_file) as file:
    entry = int(file.read(), 16)
os.unlink(entry_file)
gdb.execute("delete")
gdb.Breakpoint(f"*{entry}").ignore_count = WARMUP
gdb.execute("continue")

# The interpreter resumes at this instruction after the call returns. One loop
# iteration runs from one stop at this address to the next.
frame = gdb.newest_frame()
while in_extension(frame.pc()):
    frame = frame.older()
resume = frame.pc()
gdb.execute("delete")
gdb.execute(f"tbreak *{resume}")
gdb.execute("continue")

names = {}


def name(address):
    if address not in names:
        text = gdb.execute(f"info symbol {address}", to_string=True)
        match = re.match(r"(.+?)(?: \+ \d+)? in section", text)
        symbol = match.group(1) if match else "?"
        symbol = re.sub(r"\.llvm\.\d+", "", symbol)  # LTO suffix of local symbols
        names[address] = symbol if len(symbol) <= 90 else symbol[:87] + "..."
    return names[address]


per_iteration = []
per_symbol = collections.Counter()
inside = 0
address = pc()
for _ in range(ITERATIONS):
    count = 0
    while True:
        per_symbol[name(address)] += 1
        inside += in_extension(address)
        gdb.execute("stepi", to_string=True)
        count += 1
        address = pc()
        if address == resume:
            break
    per_iteration.append(count)
gdb.execute("kill")

total = sum(per_iteration)
print()
print(f"{function}: instructions per loop iteration, over {ITERATIONS} iterations")
print(f"  mean {total / ITERATIONS:.1f}   min {min(per_iteration)}   max {max(per_iteration)}")
print(f"  mean inside the extension {inside / ITERATIONS:.1f}, outside {(total - inside) / ITERATIONS:.1f}")
slow = {i: n for i, n in enumerate(per_iteration) if n != min(per_iteration)}
print(f"  iterations above the minimum, as {{index: instructions}}: {slow}")
print("  mean per symbol:")
for symbol, count in per_symbol.most_common():
    print(f"  {count / ITERATIONS:8.1f}  {symbol}")
