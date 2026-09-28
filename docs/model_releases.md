# Model Releases

## Bucket Versioning

| Bucket  | Versioning | Version Cleanup | COLDLINE Transition                   |
|---------|------------|-----------------|---------------------------------------|
| base    | Enabled    | Keep 1 version  | After 14 days (current + non-current) |
| staging | Enabled    | Keep 1 version  | None                                  |
| mart    | Enabled    | Keep 1 version  | None                                  |
| models  | Enabled    | Keep 1 version  | None                                  |

---

## Model Update System

The CLI automatically checks for model updates and allows users to download new versions. This section explains how the system works and how to release new models.

### How Updates Work

1. **Client-side**: When users run `zest`, the CLI periodically calls the `/check_version` endpoint (see `zest_cli/model.py`)
2. **Server-side**: The Cloud Function (`functions/version.py`) queries Firestore for the latest versions
3. **Comparison**: Semantic versions are compared (e.g., "1.0.0" vs "2.0.0")
4. **Download**: If an update is available, users can download directly from the public GCS bucket

```
+--------------+     POST /check_version      +------------------+
|   Zest CLI   | ---------------------------> |  Cloud Function  |
|              |                              |                  |
|  model.py    |  <--------------------------- |   version.py     |
+--------------+   JSON: versions, URLs       +--------+---------+
       |                                              |
       |                                              | Query
       |                                              v
       |         HTTPS download              +------------------+
       |  <--------------------------------- |    Firestore     |
       |                                     | versions/current |
       v                                     +------------------+
+--------------+
| GCS Bucket   |
| nlcli-models |
+--------------+
```

### Releasing a New Model

Follow these steps to release a model update for users:

#### Step 1: Upload the Model to GCS

Upload the new `.gguf` model file to the `nlcli-models` bucket:

```bash
gsutil cp path/to/new_model.gguf gs://nlcli-models/qwen3.5_9b_Q5_K_M.gguf
```

The bucket has versioning enabled, so the previous model is preserved automatically.

`model_size_bytes` is read live from this file's GCS metadata (`functions/version.py` and
`functions/signed_url.py` call `bucket.get_blob(...).size`), so there is no separate size
field to keep in sync -- uploading the file is enough.

#### Step 2: Update Firestore Version Document

Update the `versions/current` document in Firestore with the new version info:

```bash
# Using Firebase CLI (or update via Firebase Console)
firebase firestore:delete versions/current --project <ZEST_PROJECT_ID>
```

Then create/update the document in the Firebase Console or via the Admin SDK:

**Firestore Path**: `versions/current`

**Document Fields**:
| Field | Type | Example | Description |
|-------|------|---------|-------------|
| `cli_version` | string | "1.0.0" | Current CLI version (update on each release) |
| `model_version` | string | "1.0.0" | Model version (update on each release) |
| `update_message` | string | "Improved accuracy" | Optional message shown to users |
| `update_url` | string | "https://zestcli.com" | URL for CLI updates |

#### Step 3: Verify the Update

Test that the update is detected:

```bash
# Clear local update check cache (updates check once per interval)
# Then run zest to trigger update check
zest "test command"
```

Or test the endpoint directly:

```bash
curl -X POST https://europe-west1-<ZEST_PROJECT_ID>.cloudfunctions.net/check_version \
  -H "Content-Type: application/json" \
  -d '{"current_version": "1.0.0", "current_model_version": "1.0.0"}'
```

### Staging vs Production

| Environment | Firebase Project | Bucket |
|-------------|------------------|--------|
| Development | Set in `.firebaserc` | `nlcli-models` |
| Production | Set in `.firebaserc` | `nlcli-models` |

To test with the dev project:
```bash
firebase use dev
firebase deploy --only functions
```

### Rollback

If a model update causes issues, you can rollback:

1. **Revert Firestore**: Update `versions/current` to the previous version number
2. **Restore model file** (if needed): GCS keeps 1 previous version
   ```bash
   # List versions
   gsutil ls -a gs://nlcli-models/qwen3.5_9b_Q5_K_M.gguf

   # Copy old version back to current
   gsutil cp gs://nlcli-models/qwen3.5_9b_Q5_K_M.gguf#<generation> gs://nlcli-models/qwen3.5_9b_Q5_K_M.gguf
   ```

---

## Test Install

After building the DMG you can open it via the Finder or command line:

<img width="785" height="455" alt="Screenshot 2025-12-31 at 20 57 31" src="https://github.com/user-attachments/assets/798d6302-ceb3-44ad-b495-97dc01fdc6e7" />

- Drag to Applications.
- Open. As this is not a notarised app, it will take a moment. (It is quicker to right click + open.)
- A popup with instructions appears:

<img width="411" height="388" alt="Screenshot 2025-12-31 at 21 06 56" src="https://github.com/user-attachments/assets/5f6c9bab-33ea-4860-922a-33a8f87cd79f" />

- Run the `zest` tool in the command line, e.g. `zest what time is it`. You will be prompted to enter the email you purchased with. You will receive a 1-time-password.
- Enter the OTP. One account is allowed to have 2 machine IDs. If more than 2 slots are used, this will fail, and you will need to run `zest --logout` or `zest --uninstall` on another machine.
