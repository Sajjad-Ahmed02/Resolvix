# pgvector setup

Resolvix requires a PostgreSQL server with the `pgvector` extension available.
The extension is part of the normal PostgreSQL installation, not a separate
database server. Do not add Qdrant for the initial release.

## Recommended: Docker

The pgvector project publishes PostgreSQL images with the extension prebuilt:

```powershell
docker run -d --name resolvix-postgres `
  -e POSTGRES_USER=postgres `
  -e POSTGRES_PASSWORD=password `
  -e POSTGRES_DB=resolvix_db `
  -p 5432:5432 `
  pgvector/pgvector:pg18
```

Then set `backend/.env`:

```dotenv
DATABASE_URL=postgresql+psycopg://postgres:password@localhost:5432/resolvix_db
```

`alembic upgrade head` creates the extension automatically.

## Linux packages

Install the package matching the PostgreSQL major version, for example:

```bash
sudo apt install postgresql-18-pgvector
```

Or build and install from the official source:

```bash
git clone --branch v0.8.7 https://github.com/pgvector/pgvector.git
cd pgvector
make
sudo make install
```

## Windows (local PostgreSQL 18 used by this project)

The official pgvector project does not publish Windows binaries. This project
used the prebuilt Windows archives from
[andreiramani/pgvector_pgsql_windows](https://github.com/andreiramani/pgvector_pgsql_windows).
The archive must match the PostgreSQL major version.

The local PostgreSQL 18 service runs as `NT AUTHORITY\Network Service`. The
extension files must therefore be readable by that service account. The
following locations were used:

```
C:\ProgramData\Resolvix\pgvector\pg18\
  lib\vector.dll
  extension\vector.control
  extension\vector--*.sql
```

Installation steps:

1. Download `vector.v0.8.7-pg18.zip` from the release page and extract it.
2. Copy `lib\vector.dll` to `C:\ProgramData\Resolvix\pgvector\pg18\lib\`.
3. Copy `share\extension\*` to `C:\ProgramData\Resolvix\pgvector\pg18\extension\`.
4. Grant the PostgreSQL service account read access:

   ```powershell
   icacls "C:\ProgramData\Resolvix\pgvector\pg18" `
     /grant "NETWORK SERVICE:(OI)(CI)RX" /T
   ```

5. Point the project database at the non-standard directories. PostgreSQL 18
   supports `extension_control_path`; the list separator on Windows is `;` and
   `$system` / `$libdir` must stay literal:

   ```sql
   ALTER DATABASE resolvix_db
     SET extension_control_path =
       'C:\ProgramData\Resolvix\pgvector\pg18;$system';

   ALTER DATABASE resolvix_db
     SET dynamic_library_path =
       'C:\ProgramData\Resolvix\pgvector\pg18\lib;$libdir';
   ```

   These are database-scoped settings, so they do not affect other databases on
   the same server. Reconnect after changing them.

6. Create the extension in the project database:

   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

7. Verify:

   ```sql
   SELECT extname, extversion FROM pg_extension WHERE extname = 'vector';
   SELECT '[1,2,3]'::vector;
   ```

### Clean database on this Windows machine

If `resolvix_db` is dropped and recreated, re-apply the two
`ALTER DATABASE` settings above before running `alembic upgrade head`. The
extension archive itself remains in `C:\ProgramData\Resolvix\pgvector\pg18`.

### Alternative: standard installation

If pgvector is installed into the PostgreSQL installation's normal `lib` and
`share\extension` directories, no `extension_control_path` or
`dynamic_library_path` changes are needed. This usually requires administrator
rights on Windows. Docker is the simplest portable option.

## Verification

```powershell
cd backend
.\venv\Scripts\python.exe -m scripts.verify
```

The script confirms the extension version, `vector(384)` column, HNSW cosine
index, vector insert/retrieve, and a cosine-distance query.
