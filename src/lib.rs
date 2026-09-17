//! Three pairs of functions with empty bodies. There is one pair for each
//! calling convention that PyO3 uses.
//!
//! The `plain_*` functions are ordinary `#[pyfunction]`s. Since PyO3 0.28 their
//! `PyMethodDef` has the `METH_STATIC` flag.
//!
//! The `with_module_*` functions are the control group. They use `pass_module`,
//! so PyO3 classifies them as `FnType::FnModule` instead of `FnType::FnStatic`,
//! and they do not get the flag.

use pyo3::prelude::*;
use pyo3::types::PyDict;

// No parameters: METH_NOARGS

#[pyfunction]
fn plain_noargs() {}

#[pyfunction(pass_module)]
fn with_module_noargs(_module: &Bound<'_, PyModule>) {}

// Parameters but no `**kwargs`: METH_FASTCALL | METH_KEYWORDS

#[pyfunction]
fn plain_onearg(_arg: &Bound<'_, PyAny>) {}

#[pyfunction(pass_module)]
fn with_module_onearg(_module: &Bound<'_, PyModule>, _arg: &Bound<'_, PyAny>) {}

// `**kwargs`: METH_VARARGS | METH_KEYWORDS

#[pyfunction(signature = (**_kwargs))]
fn plain_kwargs(_kwargs: Option<&Bound<'_, PyDict>>) {}

#[pyfunction(pass_module, signature = (**_kwargs))]
fn with_module_kwargs(_module: &Bound<'_, PyModule>, _kwargs: Option<&Bound<'_, PyDict>>) {}

#[pymodule]
fn meth_static_repro(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(plain_noargs, m)?)?;
    m.add_function(wrap_pyfunction!(with_module_noargs, m)?)?;
    m.add_function(wrap_pyfunction!(plain_onearg, m)?)?;
    m.add_function(wrap_pyfunction!(with_module_onearg, m)?)?;
    m.add_function(wrap_pyfunction!(plain_kwargs, m)?)?;
    m.add_function(wrap_pyfunction!(with_module_kwargs, m)?)?;
    Ok(())
}
