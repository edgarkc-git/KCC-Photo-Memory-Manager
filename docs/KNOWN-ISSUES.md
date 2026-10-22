# Known issues

## v2.2.0

Measured in the v2.2.0 release checks: a fresh install and a sample dump on
macOS, a real 951-file dump on macOS, and a fresh clone on Windows 11.
Nothing here touches your original photos: the product stays copy-only.

### All platforms (found on macOS)

- **A later photo set's pet pages can ask only about earlier sets.** The page may
  show animals from photo sets you sorted before, and none from this one. Answer
  or skip them; nothing is copied again.
- **Close-ups of one animal can be asked as several animals.** Crops of one pet
  (paws, a tail) can come as separate questions; there is no "same animal
  again" answer yet. Skip the extra crops.
- **No command removes one pet from one folder name.** `photo_subjects.py review
  --detach` takes back a whole group of photos, not one folder.
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

Two test-only defects. The product itself behaves correctly; only the tests are
wrong there. On macOS all cases pass.

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
Run every command with `PYTHONUTF8=1` set (see docs/INSTALL.md).
