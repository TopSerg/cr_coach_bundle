# Fetch status

Дата сборки: 2026-09-03.

В runtime-среде сборки обычный `git clone` не может соединиться с `github.com` (outbound network blocked). GitHub API и web inspection доступны только через внутренние инструменты, которые не предоставляют массовый binary/tarball export в локальную файловую систему.

Поэтому:

- upstream repositories НЕ притворяются скачанными;
- в `repos/` нет фальшивых snapshots;
- `scripts/fetch_upstreams.*` скачивают всё на нормальной машине с интернетом;
- `scripts/fetch_heavy_assets.sh` отдельно скачивает большие HF/release assets;
- `starter/` — наш новый glue-code, не upstream snapshot;
- `project_source/ANALYSIS_AND_PLAN_RU.txt` — сохранённый план проекта.

Это сделано намеренно, чтобы архив был честным и воспроизводимым.
