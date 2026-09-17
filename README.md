# PyO3 >= 0.28 sets `METH_STATIC` on every `#[pyfunction]`

This project reproduces the problem. `src/lib.rs` defines three pairs of functions with empty
bodies. There is one pair for each calling convention that PyO3 uses.

```rust
#[pyfunction]
fn plain_noargs() {}
#[pyfunction(pass_module)]
fn with_module_noargs(_module: &Bound<'_, PyModule>) {}

#[pyfunction]
fn plain_onearg(_arg: &Bound<'_, PyAny>) {}
#[pyfunction(pass_module)]
fn with_module_onearg(_module: &Bound<'_, PyModule>, _arg: &Bound<'_, PyAny>) {}

#[pyfunction(signature = (**_kwargs))]
fn plain_kwargs(_kwargs: Option<&Bound<'_, PyDict>>) {}
#[pyfunction(pass_module, signature = (**_kwargs))]
fn with_module_kwargs(_module: &Bound<'_, PyModule>, _kwargs: Option<&Bound<'_, PyDict>>) {}
```

Since PyO3 0.28, the `PyMethodDef` of every `plain_*` function has the `METH_STATIC` flag. Its
`__self__` is `None` instead of the module. The `with_module_*` functions do not have the flag.
They are the control group.

On CPython 3.11 and newer, a call of `plain_onearg` is about 2 to 4 ns (10 to 21%) slower than a
call of `with_module_onearg`. The other two pairs show no difference.

## Run it

```sh
python -m venv .venv
.venv/bin/pip install .
.venv/bin/python repro.py
```

Output with CPython 3.14.6 and PyO3 0.29.2 on a Ryzen 7 9700X (Linux, x86-64):

```text
CPython 3.14.6

               plain #[pyfunction]             #[pyfunction(pass_module)]
               ml_flags  __self__  ns/call     ml_flags  __self__  ns/call     difference
no parameters  0x0024    None         13.1     0x0004    module       13.0      +0.1 ns   +1%
one parameter  0x00a2    None         19.6     0x0082    module       16.4      +3.3 ns  +20%
**kwargs       0x0023    None         16.8     0x0003    module       16.7      +0.1 ns   +1%

0x0020 = METH_STATIC
0x0004 = METH_NOARGS
0x0082 = METH_KEYWORDS|METH_FASTCALL
0x0003 = METH_VARARGS|METH_KEYWORDS

BUG: the plain `#[pyfunction]`s are METH_STATIC
```

`repro.py` reads `ml_flags` by calling `PyCFunction_GetFlags` through `ctypes.pythonapi`, so it
requires CPython. It times each pair in alternating rounds. It exits with status 1 if a plain
function has `METH_STATIC`.

To test another PyO3 version, change the `pyo3 = "=0.29.2"` line in `Cargo.toml` and run
`.venv/bin/pip install .` again.

## Results

The tables show the time of the plain function minus the time of its control, in ns per call.

By PyO3 version, with CPython 3.14.6:

| PyO3 | `METH_STATIC` | no parameters | one parameter | `**kwargs` |
| --- | --- | ---: | ---: | ---: |
| 0.27.2 | no | +0.0 | +0.0 | +0.0 |
| [`bee3fda26`][parent] (parent of `1999aa9ec`) | no | +0.0 | +0.1 | +0.0 |
| [`1999aa9ec`][culprit] (#5581) | yes | +0.2 | +2.7 | +0.2 |
| 0.28.2 (0.28.0 and 0.28.1 are yanked) | yes | +0.2 | +2.5 | +0.1 |
| 0.29.2 | yes | +0.0 | +2.7 | +0.1 |
| [`b3d1fd32`][fix] (PyO3 main with the candidate fix) | no | +0.0 | +0.0 | +0.0 |

By CPython version, with PyO3 0.29.2:

| CPython | no parameters | one parameter | `**kwargs` |
| --- | ---: | ---: | ---: |
| 3.9.25 | +0.0 | -0.1 | +0.2 |
| 3.10.20 | +0.3 | +0.5 | +0.1 |
| 3.11.15 | +0.1 | +3.7 | +0.4 |
| 3.12.13 | -0.2 | +2.3 | +0.0 |
| 3.13.14 | -0.2 | +2.6 | +0.0 |
| 3.14.6 | +0.0 | +2.7 | +0.1 |
| 3.14.6 free-threaded | +0.0 | +2.8 | +0.0 |
| 3.15.0b3 | -0.1 | +2.2 | +0.1 |

The flag is set on every CPython version. CPython 3.9 and 3.10 do not have a specializing
interpreter, and they show no difference. `pass_module` therefore does not make a function faster
by itself.

Each time is the best of 7 rounds of 2,000,000 calls, pinned to one core. Absolute times differ
between builds because the code is placed at different addresses. For example, one build of this
project ran both `**kwargs` functions at 27.3 ns instead of 16.6 ns, while executing the same 514
instructions per iteration. Only the two columns of one row are comparable. The instruction counts
below are not affected by code placement.

`repro.py` does not run on other interpreters. The following command runs on any interpreter:

```sh
python -c "import meth_static_repro as m; print(m.plain_onearg.__self__)"
```

It prints `None` on GraalPy 25.0. It prints the module on PyPy 7.3.23. On PyPy 7.3.19 these
functions have no `__self__` attribute. PyPy ignores the flag. Its C API layer
[removes `METH_STATIC`][pypy] from the flags before it dispatches a call, and it always passes the
module.

## Cause

### PyO3

[#5581][culprit] moved the code that adds `METH_CLASS` and `METH_STATIC`. The code was in
`impl_py_method_def`, which only `#[pymethods]` uses. It is now in `FnSpec::get_methoddef`, which
`#[pyfunction]` also uses. The flag is selected by `FnType` ([`method.rs`][flags]):

```rust
FnType::FnStatic => quote! { .flags(#pyo3_path::ffi::METH_STATIC) },
```

`FnType::FnStatic` is documented as "a pyfunction or a pymethod annotated with `#[staticmethod]`"
([`method.rs`][fnstatic]). A `#[pyfunction]` without `pass_module` gets this type in
[`pyfunction.rs`][pyfunction]. As a result, module-level functions also get `METH_STATIC`.

### CPython

`PyCFunction_GET_SELF` returns `NULL` for a builtin function that has `METH_STATIC`. For this
reason `__self__` is `None`.

The slowdown is caused by the specializing interpreter. `specialize_c_call` masks the flags before
it selects a specialized instruction ([`specialize.c`][specialize]):

```c
switch (PyCFunction_GET_FLAGS(callable) &
    (METH_VARARGS | METH_FASTCALL | METH_NOARGS | METH_O |
    METH_KEYWORDS | METH_METHOD)) {
```

The mask removes `METH_STATIC`, so the call site is specialized to
`CALL_BUILTIN_FAST_WITH_KEYWORDS`. The guard of that instruction compares all flags
([`bytecodes.c`][guard]):

```c
DEOPT_IF(PyCFunction_GET_FLAGS(callable_o) != (METH_FASTCALL | METH_KEYWORDS));
```

The guard fails on every call, and the generic `CALL` instruction runs instead. On CPython 3.14.6
the call site is specialized again every 52 calls. Specialization selects the same instruction each
time, so the guard continues to fail.

Only one pair is slower. Of the three calling conventions that PyO3 uses, only
`METH_FASTCALL | METH_KEYWORDS` is specialized to an instruction with such a guard. PyO3
[selects][convention] this convention for a function that has parameters and no `**kwargs`. It uses
`METH_NOARGS` and `METH_VARARGS | METH_KEYWORDS` for the other functions. For these two, the
`switch` above takes the `default:` branch and selects `CALL_NON_PY_GENERAL`. That instruction does
not check the flags.

## Instruction counts

`tools/count_instructions.py` single-steps 110 loop iterations under gdb, after a warm-up, and
counts the instructions. The counts do not depend on timing noise or on code placement.

```sh
gdb -q -batch -x tools/count_instructions.py --args .venv/bin/python tools/loop.py plain_onearg
gdb -q -batch -x tools/count_instructions.py --args .venv/bin/python tools/loop.py with_module_onearg
```

Mean instructions per loop iteration with CPython 3.14.6 and PyO3 0.29.2:

| | total | inside the extension | outside |
| --- | ---: | ---: | ---: |
| `plain_noargs` | 426.0 | 71.0 | 355.0 |
| `with_module_noargs` | 425.0 | 71.0 | 354.0 |
| `plain_onearg` | 603.8 | 160.0 | 443.8 |
| `with_module_onearg` | 514.0 | 160.0 | 354.0 |
| `plain_kwargs` | 515.0 | 145.0 | 370.0 |
| `with_module_kwargs` | 514.0 | 145.0 | 369.0 |

An iteration of `plain_onearg` takes 602 instructions, or 700 when the call site is specialized
again. All other functions take the same number of instructions in every iteration.

Within each pair, the extension executes the same number of instructions. `plain_noargs` and
`plain_kwargs` execute one more instruction than their controls. This instruction is the
`METH_STATIC` check of `PyCFunction_GET_SELF`, in `cfunction_vectorcall_NOARGS` and
`cfunction_call`.

For `plain_onearg` and `with_module_onearg`, the counts differ only in the following symbols. The
values are mean instructions per iteration. A value of 0.0 means that the symbol is not executed.
The first two rows are handlers of bytecode instructions. Their symbols have the prefix
`_TAIL_CALL_` in this build of CPython, and the table omits it.

| | `plain_onearg` | `with_module_onearg` |
| --- | ---: | ---: |
| `CALL_BUILTIN_FAST_WITH_KEYWORDS` | 34.6 | 110.0 |
| `CALL` | 138.6 | 0.0 |
| `cfunction_vectorcall_FASTCALL_KEYWORDS` | 26.0 | 0.0 |
| `_Py_Specialize_Call` | 0.5 | 0.0 |

With the candidate fix ([`b3d1fd32`][fix]), `plain_onearg` takes 512.0 instructions per iteration,
and 354.0 of them are outside the extension. Its control has the same counts. The call site is not
specialized again.

The tool locates a function by the address that `PyCFunction_GetFunction` returns. It does not use
symbol names. The linker merges `with_module_noargs` into `plain_noargs` because their code is
identical, so `with_module_noargs` has no symbol.

## Fix and workaround

Candidate fix: [`b3d1fd32`][fix]. It adds the two flags in `impl_py_method_def` again, so that only
methods of a class get them. It also adds a test that a `#[pyfunction]` has neither flag. To test
it, enable the commented-out `pyo3` line in `Cargo.toml` and run `.venv/bin/pip install .` again.

Workaround: declare the function with `#[pyfunction(pass_module)]` and add an unused
`&Bound<'_, PyModule>` first parameter. Such a function does not get the flag.

[parent]: https://github.com/PyO3/pyo3/commit/bee3fda26e92272a8ecd874d4ab26f6eedcd3ef8
[culprit]: https://github.com/PyO3/pyo3/commit/1999aa9ecbb0a7c82179f810bd50a9bde135f3eb
[fix]: https://github.com/overcat/pyo3/commit/b3d1fd3277ee15d25943593aaab2cf17d20e7198
[flags]: https://github.com/PyO3/pyo3/blob/v0.29.2/pyo3-macros-backend/src/method.rs#L1076
[fnstatic]: https://github.com/PyO3/pyo3/blob/v0.29.2/pyo3-macros-backend/src/method.rs#L230-L231
[pyfunction]: https://github.com/PyO3/pyo3/blob/v0.29.2/pyo3-macros-backend/src/pyfunction.rs#L362-L372
[convention]: https://github.com/PyO3/pyo3/blob/v0.29.2/pyo3-macros-backend/src/method.rs#L557-L565
[pypy]: https://github.com/pypy/pypy/blob/4f564267b310cc77a7e53037cb5a9d4bc79abe3e/pypy/module/cpyext/methodobject.py#L126
[specialize]: https://github.com/python/cpython/blob/v3.14.6/Python/specialize.c#L2143-L2145
[guard]: https://github.com/python/cpython/blob/v3.14.6/Python/bytecodes.c#L4316
