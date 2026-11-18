# Known issues

## v2.5.0

Measured in the v2.5.0 release checks: the full test set, a real trip slice
and a picture pass on macOS, and a picture pass on Windows 11. Nothing here
touches your original photos: the product stays copy-only.

### All platforms

- **Confirming your home country can change folder names, most of all outside
  Taiwan.** Until your pack has a confirmed country, the engine knows only
  Taiwan's borders: an owner living elsewhere gets no day abroad and no trip
  offers. Once you confirm your country (the onboarding question, the Review
  folders HOME-COUNTRY row, or `photo_settings.py country`), days outside it
  and outside every home valid that day become days abroad, from the next run
  that sorts the days. Their batches are labelled as abroad, Review folders
  can offer a trip folder for them, and a stop with no landmark is named by
  its town abroad but by its district at home (before, for an owner outside
  Taiwan, by its town everywhere). Folders already copied keep their names.
- **Home country outside Taiwan: day types keep their Taiwan names.** Once your
  pack's country is confirmed, "abroad" follows your homes and their dates
  for any country, but the day types are still called `TW_HOME`/`TW_AWAY`
  internally, and the islands table holds Taiwan's island groups only. A
  photo taken at sea, far from any coast, counts as in your home country.
- **Setting your home country in the middle of a dump can offer one extra
  trip.** If you answer the home-country question on Review folders while you
  have a home abroad that is valid on that dump's days, that one dump may
  offer a trip that also covers the days you spent at that home: its days were
  sorted before the country was set. Skip that row; from the next dump, days
  at a home abroad count as home.
- **The onboarding country question still says "outside TW" in its help
  text,** even when it suggests another country. The suggestion is right; the
  sentence is only about which homes the question is for.
- **A NAME-CHECK row is answered at `check`, before the freeze** (as in
  v2.4.0). If you leave it open and freeze, answering it later needs
  `photo_index.py unfreeze`, then render, check and freeze again. It never
  blocks the copy.
- **Dropping a place word from a trip's leg on Review folders also changes the
  trip parent's name.** This passed the test set but is not yet run on a real
  trip.

## v2.4.0

Measured in the v2.4.0 release checks: the full test set, and a real dump
slice on macOS run up to the freeze. Nothing here touches your original
photos: the product stays copy-only.

### All platforms

- **The picture-pass time estimate can still be far too low** (as in v2.3.0).
  Plan for longer than the estimate.
- **A slow map service still shows no progress** while it retries (as in
  v2.3.0). It has not hung; let it finish.
- **The freeze can still warn that a Review folders row was refused when it was
  applied** (as in v2.3.0). Check the folder name on disk.
- **A NAME-CHECK row is answered at `check`, before the freeze.** If you leave
  it open and freeze, answering it later needs `photo_index.py unfreeze`, then
  render, check and freeze again. It never blocks the copy.
- **Renaming a trip parent, dropping a place from it, and retrying a landmark
  lookup after the copy** passed the test set but were not yet run on a real
  trip dump.

## v2.3.0

Measured in the v2.3.0 release checks: a 6,032-file dump and a scratch dump
stopped and resumed on macOS, and a fresh clone with a 119-photo dump on
Windows 11. Nothing here touches your original photos: the product stays
copy-only.

### All platforms

- **The picture-pass time estimate can be far too low.** Measured: 18 minutes
  shown, 1 hour 8 minutes taken on the 6,032-file dump; 1 minute shown,
  7 minutes taken on Windows 11. Plan for longer than the estimate.
- **A slow map service shows no progress.** While the map service retries,
  `photo_run.py cluster` can print nothing for many minutes (16 minutes
  measured). It has not hung; let it finish. A lookup that still fails is
  named by its town and says so.
- **A pet page can show a box that is not an animal** (measured: a pine cone;
  animal statues were boxed too). Answer `skip: N.M not-a-subject` for that box.
- **The freeze can warn that a Review folders row was refused when it was
  applied.** Check the folder name on disk; if it shows your answer, the row
  was applied.

### Windows 11: system resources

Measured on one PC: 16 GB memory, CPU only (no graphics card used),
Python 3.14.3, `PYTHONUTF8=1` set.

- **Memory:** the picture pass (photo vectors, animal detection and identity
  on the CPU) ran out of memory while a Claude Code session was open, and the
  session's shell was stopped part way. Run that stage in your own PowerShell
  window while the agent waits, with other large programs closed; it then
  finished all 119 photos. On a 16 GB PC, treat this as the normal way to run
  the picture pass.
- **Downloads:** `doctor`'s install plan downloads the CPU build of torch
  (about 200 MB), and the first picture pass downloads the model weights once
  (CLIP about 600 MB, the animal detector about 170 MB, DINOv2 about 330 MB).
- **Time:** the picture pass ran at about 3.5 seconds per photo on the CPU
  (119 photos in 7 minutes).

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
  the dump's index is made to retry the lookups; after that, even after the
  copy, run `photo_index.py retry-landmarks <dump> --go`.

### Windows 11

Two test-only defects, both fixed in v2.3.0 (`doctor_cases` 34 of 34 on
Windows 11). Run every command with `PYTHONUTF8=1` set (see docs/INSTALL.md).

- **W11-1** (fixed in v2.3.0) `tests/doctor_cases.py`
  `the_prep_stop_quotes_a_product_path_with_a_space` expected the POSIX form
  of the doctor line on Windows.
- **W11-2** (fixed in v2.3.0) `tests/doctor_cases.py`
  `a_copy_with_neither_says_it_does_not_know` could not delete a read-only
  file inside a temporary `.git` folder (`PermissionError`).
