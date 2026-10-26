# Known issues

## v2.2.0

Measured in the v2.2.0 release checks: a fresh install and a sample dump on
macOS, a real 951-file dump on macOS, and a fresh clone on Windows 11.
Nothing here touches your original photos: the product stays copy-only.

### All platforms (found on macOS)

- **A pet seen only at home can be paired with an away-day word.** If a proposed
  `[what]` is wrong, set the folder's own words with
  `photo_index.py group set-what`.
- **Place names abroad can come in the local script.** When the map has no name
  in your language, the local name is used. Change it on the Review folders page
  with "my word".
- **The map service can fail for a while (502/504).** A place lookup that
  failed is named by its town. Run `photo_run.py cluster <dump> --force` before
  the dump's index is made to retry the lookups.

### Windows 11

Two test-only defects, both fixed in v2.3.0 (`doctor_cases` 34 of 34 on
Windows 11). Run every command with `PYTHONUTF8=1` set (see docs/INSTALL.md).

- **W11-1** (fixed in v2.3.0) `tests/doctor_cases.py`
  `the_prep_stop_quotes_a_product_path_with_a_space` expected the POSIX form
  of the doctor line on Windows.
- **W11-2** (fixed in v2.3.0) `tests/doctor_cases.py`
  `a_copy_with_neither_says_it_does_not_know` could not delete a read-only
  file inside a temporary `.git` folder (`PermissionError`).
