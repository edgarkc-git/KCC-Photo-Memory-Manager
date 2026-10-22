# Known issues

## v2.2.0

Two test-only defects, found on Windows 11 in the release check. The product
itself behaves correctly; only the tests are wrong there. On macOS all cases pass.

- **W11-1** `tests/doctor_cases.py` `the_prep_stop_quotes_a_product_path_with_a_space`
  fails on Windows. The test expects the POSIX form of the doctor line. Windows
  correctly prints the PowerShell form (`& "<python>" "<path>\photo_run.py" doctor`),
  with both paths quoted.
- **W11-2** `tests/doctor_cases.py` `a_copy_with_neither_says_it_does_not_know`
  fails on Windows. The test's setup cannot delete a read-only file inside a
  temporary `.git` folder (`PermissionError`), so the case never reaches the
  check it guards.

Result on Windows 11: `doctor_cases` 32 of 34. `doctor` and `fresh_owner_smoke`
pass. Both defects are older than v2.2.0 and are planned for a later release.
