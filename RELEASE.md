# Releasing `isabelle-semantic-embedding` and `isabelle-semantic-data`

This adds to the SKILL conda-release (xqyww123/isabelle-packaging-ci, `.claude/skills/conda-release/SKILL.md`).

`isabelle-semantic-embedding`, the library, has no steps of its own. `isabelle-semantic-data`, the data package, has
the steps below.

## `isabelle-semantic-data`

It ships the snapshot of the semantic database that the owner put on Hugging Face, so what was synced is what ships,
never a local database. That snapshot is uploaded beforehand, by the SKILL sync-semantic-embedding-db (in MLML) and
only on the owner's order: that upload is never a release step. The upload of the built `.conda` in step 5 below is
one.

The package is built on a big-memory machine, not on the runner: rattler-build needs about twice the finished `.conda`
in RAM, and the `.conda` is about 9 GB (its payload 19 GB). The runner still does everything else:
`release-semantic-db.yml` takes the finished `.conda` through its `prebuilt` input and checks, publishes and
smoke-tests it as it would a package it built itself.

On a machine with ≥ 40 GB RAM, ≥ 60 GB disk and a fast link (cslh19 did it: export 1 min, rattler-build 8 min, upload
30 min), work in a new, empty directory outside every repository checkout. The snapshot extracts to a directory named
`Isabelle_Semantic_Embedding`, the name of the live database in `~/.cache` and of this repository's Python package
directory (which, in the working directory, would also shadow the library of step 1), and step 3 deletes it.

1. An environment with the **channel's own library**, so the export is the one CI would have run:

   ```sh
   micromamba create -p env --override-channels -c https://conda-ci.qiyuan.me -c conda-forge python=3.12 "isabelle-semantic-embedding>=0.3.0" huggingface_hub zstd
   ```
2. Download the snapshot, with the cached HF token:
   `hf_hub_download(repo_id="ANTPG/MLML-data", repo_type="dataset", filename="contrib/Semantic_Embedding/Isabelle_Semantic_Embedding.tar.zst")`.
   The path it returns is a **symlink**: `readlink -f` it, since `zstd` refuses symlinked inputs and `stat` without
   `-L` reports the link's size. Check its size against the `size` of its entry in MLML's `data/manifest.json` as
   pushed (`git -C ~/Current/MLML fetch origin`, then `git -C ~/Current/MLML show origin/main:data/manifest.json`); if
   they differ, stop and ask the owner.
3. `zstd -dc … | tar -x` in that directory, then export and delete the extracted database:

   ```sh
   SEMANTIC_DB_DIR=<the tarball's single top directory> env/bin/isabelle-semantics export payload
   ```
4. Build with rattler-build at the version the workflow pins, with `--recipe` the path of
   `conda/isabelle-semantic-data/recipe.yaml` in a checkout of this repository at the head of its default branch,
   `SEMANTIC_DATA_PAYLOAD` set to the absolute path of step 3's `payload` directory and `SEMANTIC_DATA_VERSION` set to
   the version of that payload's own `MANIFEST.json` (not MLML's `data/manifest.json`):

   ```sh
   env/bin/python -c "import json; from Isabelle_Semantic_Embedding.snapshot_sync import version_of_created_at as v; print(v(json.load(open('payload/MANIFEST.json'))['created_at']))"
   ```

   Pass `--build-num <N>`, the build number the SKILL gives ("8. The build number"; 0 on a first run, since every
   export is a new version), `--no-test` and `-c https://conda-ci.qiyuan.me -c conda-forge`, and put **`TMPDIR` on a
   real disk**: rattler-build stages the archive under `/tmp`, which on cslh19 is a 32 GB tmpfs that a 9 GB archive
   fills.
5. Upload the `.conda` to the dataset `ANTPG/MLML-data` under `contrib/Semantic_Embedding/conda/`
   (`HfApi().upload_file(..., repo_id="ANTPG/MLML-data", repo_type="dataset")`, commit message naming the machine).
   This is a release artifact, not a dev-sync file: it is **not** added to `data/manifest.json`.
6. One dispatch (the SKILL, "6. A dispatch"), with `build_number` the number step 4 built with:

   ```sh
   gh workflow run release-semantic-db.yml -R xqyww123/Isabelle_Semantic_Embedding -f prebuilt=contrib/Semantic_Embedding/conda/<name>.conda -f build_number=<N> -f dry_run=false
   ```

   The sanity step fails when the package's version disagrees with its `MANIFEST.json`, or its build number with
   `build_number`. The uploaded `.conda` keeps what it was built with: the build number, the recipe, and the payload
   exported by step 1's library. So when a new run (the SKILL, "9. When a job fails") needs another build number
   ("8. The build number") or a fix in the recipe or in `isabelle-semantic-embedding`, build a new one: start again at
   step 3 (step 4 moved the payload into the package; the new export is a new version), or at step 1 for a fix in
   `isabelle-semantic-embedding`; build with the SKILL's number, and upload the new file in step 5. Any other new run
   dispatches the same file.
