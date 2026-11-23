# Análisis profundo del proyecto RCSyncitMF

**Fecha:** 2026-11-22
**Rama analizada:** `main` (árbol de trabajo limpio)
**Commits base:** `d32d604` (chore: use app logo as system icon) … `adb0186` (initial)
**Herramientas ejecutadas:** pytest 22/22, ruff check (pass), mypy (pass)

---

## 1. Resumen ejecutivo

RCSyncitMF es una aplicación de escritorio GNOME (GTK 4 + libadwaita) en Python que actúa como gestor multi-perfil de `rclone`: perfiles (`.conf`), remotos, unions, mounts (FUSE) y sincronización de **estructura de directorios** entre upstreams de un union. Fase Alpha (pyproject 1.0.1, pero `__version__` interno 0.1.0).

**Estado general:** El código pasa ruff, mypy y 22 tests. Los bloqueadores reportados en la iteración anterior (Copiar/Mover en FilesPage, bloqueos de UI en MountsPage, invalidación de caché de rclone bin, traducciones) ya están corregidos en el árbol actual. Permanecen **problemas de bloqueo del hilo de UI** (`RemoteDialog._ensure_dump`, `profile_store.is_encrypted` en profile_detail, `mount_manager.clear_vfs_cache`), **inconsistencias de versión**, **integridad referencial** al renombrar/borrar perfiles, y **cobertura de tests limitada** (solo 3 módulos de servicio).

No se encontró `plan.md` en el repositorio: la verificación de cumplimiento de plan no aplica; el análisis se hizo contra el código, README, manifest y el `review.md` previo.

---

## 2. Stack y arquitectura

| Componente | Detalle |
|---|---|
| Lenguaje | Python ≥ 3.11 (probado aquí en 3.14) |
| UI | PyGObject (GTK 4 + libadwaita) |
| Config | TOML (`tomllib`/`tomli-w`) + migración legacy JSON |
| Async/UI bridge | `ui/async_helper.run_async` (thread + `GLib.idle_add`) |
| Backend | `rclone` CLI vía `asyncio.create_subprocess_exec` |
| Empaquetado | setuptools, Flatpak (GNOME 51), pipx |
| i18n | JSON (`es`, `en`) |

### Estructura de paquetes

```
src/rcsyncitmf/
  application.py      # Adw.Application, lifecycle, auto_sync
  window.py           # MainWindow, sidebar, stack, drag&drop
  config.py           # XDG paths, settings, migraciones
  i18n.py             # traducciones JSON
  models/             # (vacío)
  services/
    rclone.py         # wrapper async CLI
    profile_store.py  # perfiles, metadata, password cache
    mount_manager.py  # mounts, VFS cache, bookmarks
    union_sync.py     # planificador 3-vías de directorios
    sync_state.py     # baselines por (perfil, union)
    auto_sync.py      # daemon periódico
  ui/
    async_helper.py
    pages/            # profiles, files, remotes, unions, mounts, settings
    dialogs/          # profile_detail, remote_dialog, union_dialog
  resources/          # CSS, iconos
  locales/            # es.json, en.json
```

---

## 3. Verificación de calidad automatizada

| Herramienta | Resultado |
|---|---|
| `pytest -q` | **22/22 passed** (0.03s) |
| `ruff check src tests` | **All checks passed** |
| `ruff format --check src tests` | **30 files already formatted** |
| `mypy src/rcsyncitmf` | **Success: no issues (27 archivos)** |

### Cobertura de tests

- `tests/test_profile_store.py` (6): create/list/delete/rename/import/meta.
- `tests/test_mount_manager.py` (9): mountpoint, cache, safe_remote, read log, custom dir, cleanup.
- `tests/test_union_sync.py` (7): parse, collapse, join, build_mirror_plan, apply.

**Sin tests para:** `rclone.py`, `config.py`, `sync_state.py`, `auto_sync.py`, `profile_store.is_encrypted`/`encrypted_flag`, `union_sync.normalize_union_cache_times`, `remote_dialog` (lógica de `_collect_opts`), `files_page` (transfer/mounted targets), `mounts_page`, `window`, `application`, `i18n`.

---

## 4. Plan Compliance

No existe `plan.md` en el repositorio, por lo que no hay spec aprobada contra la que verificar ítem por ítem. Se reporta `N/A` para cumplimiento de plan; el análisis se basa en el código actual, README, manifest Flatpak y el `review.md` previo.

---

## 5. Hallazgos de corrección (Correctness Issues)

### 5.1 🔴 Alto — Bloqueos del hilo de UI por rclone síncrono (residuales)

Aunque `MountsPage.refresh` y `ProfilesPage` ya usan variantes asíncronas/no bloqueantes, quedan tres puntos que ejecutan rclone en el hilo principal de GTK:

1. **`RemoteDialog._ensure_dump`** (`src/rcsyncitmf/ui/dialogs/remote_dialog.py:181-195`) usa `asyncio.run(rclone.config_dump(...))`. Se invoca durante la construcción del diálogo y al cambiar el tipo, bloqueando la UI hasta que rclone responda (especialmente con perfiles cifrados o backends lentos).
   - **Impacto:** congelamiento de ventana al abrir/editar remotos.
   - **Sugerencia:** cachear el dump de forma asíncrona antes de presentar el diálogo (como ya hace `ProfileDetailDialog._load_accounts`) o cargarlo lazy en `_on_type_changed`.

2. **`profile_detail.py:202`** llama `profile_store.is_encrypted(self.profile)` (síncrono, crea event loop) en el manejador de error de `_load_accounts`. `is_encrypted` ya no se usa en `ProfilesPage` (que usa `encrypted_flag`), pero aquí sigue bloqueando.
   - **Sugerencia:** reemplazar por `profile_store.encrypted_flag(self.profile)` (no bloqueante) y, si es `None`, pedir contraseña.

3. **`mount_manager.clear_vfs_cache`** (`src/rcsyncitmf/services/mount_manager.py:618`) es `async` pero llama sincrónicamente a `related_cache_remotes(remote)` (`:599`), que recorre `_all_profile_dumps()` → `_dump_for_profile` → `asyncio.new_event_loop()` + `rclone.config_dump` para cada perfil. Bloquea el event loop.
   - **Sugerencia:** usar `async_crypt_parent_map`/una variante async de `related_cache_remotes` (ya existe `async_crypt_parents_with_cache` como patrón).

Además, los helpers síncronos `crypt_parent`, `related_cache_remotes`, `crypt_parents_with_cache` y `_dump_for_profile` siguen existiendo y pueden ser invocados por código de fallback (`MountsPage._add_mount_card` línea ~177/316 usa `mount_manager.crypt_parent(remote)` si `_crypt_parents` no está). Bajo carga esto sigue congelando la UI.

### 5.2 🟠 Medio — Integridad referencial al mutar perfiles

- `profile_store.rename_profile` (`profile_store.py`) renombra el `.conf` y migra metadata, pero **no actualiza** `mounts.toml` (que guarda `config` como path absoluto) ni `sync_state.toml` (clave por path resuelto). Tras renombrar, los mounts persistidos apuntan a un archivo inexistente y los baselines quedan huérfanos.
- `profile_store.delete_profile` borra el `.conf` y `.meta.toml` pero deja registros de mounts y baselines huérfanos.
  - **Sugerencia:** en ambas operaciones, limpiar/actualizar entradas en `mount_manager` (filtrar por `config`) y `sync_state` (por perfil).

### 5.3 🟠 Medio — Sync de unions condicionado a mount innecesariamente

- `UnionsPage._add_union_row` (`src/rcsyncitmf/ui/pages/unions_page.py:176`) hace `btn_sync.set_sensitive(initially_mounted)` y el tooltip indica que solo está disponible cuando el union está montado. Sin embargo, `union_sync` opera directamente sobre los remotos vía `rclone config dump`/`list_dirs`, sin requerir mount. El botón queda deshabilitado en el caso común de union no montado, impidiendo la sincronización.
  - **Sugerencia:** habilitar siempre el botón (o al menos no condicionarlo a `is_mounted`).

### 5.4 🟠 Medio — Mensajería y semántica de borrados

- `UnionsPage._on_sync` fuerza `delete_enabled = False` y `mode = "mirror"`, y `_show_preview` muestra "solo creaciones". `build_mirror_plan` acepta `allow_delete`, pero la UI nunca lo activa. La nota sobre `action_policy` (líneas finales de `_show_preview`) puede sugerir propagación de borrados que en realidad no ocurre.
  - **Sugerencia:** alinear documentación/mensajes o exponer un toggle explícito de borrados (con confirmación).

### 5.5 🟡 Bajo — Inconsistencia de versión

- `src/rcsyncitmf/__init__.py:3` → `__version__ = "0.1.0"`
- `pyproject.toml` → `version = "1.0.1"`
- `window.py:332` (About) → `dlg.set_version("1.0.0")`
- `SettingsPage` muestra `__version__` (0.1.0).
  - **Sugerencia:** fuente única de verdad (leer de package metadata o constante compartida) y actualizar About.

### 5.6 🟡 Bajo — `profiles_dir` de settings ignorado

- `DEFAULT_SETTINGS` incluye `profiles_dir` y `SettingsPage` lo muestra, pero el código usa siempre `config.PROFILES_DIR` (`profile_store.list_profiles` → `PROFILES_DIR`). Cambiarlo en settings no tiene efecto.
  - **Sugerencia:** honrar `settings["profiles_dir"]` en `profile_store` o eliminar la opción.

### 5.7 🟡 Bajo — Rclone check en Flatpak con falso positivo por timeout

- `application.py:60-66`: si el hilo de comprobación supera 10s, `t.join(timeout=10)` retorna y `rclone_ok` queda `True` (valor por defecto de `result`), reportando rclone disponible cuando no se pudo verificar.
  - **Sugerencia:** inicializar `result["ok"] = False` o usar un flag `checked`.

### 5.8 🟡 Bajo — `is_mounted` en Flatpak no maneja rutas con espacios

- `mount_manager.is_mounted` (rama Flatpak) compara `parts[1] == mp` sobre `/proc/mounts`, cuyo formato escapa espacios como `\040`. Mountpoints con espacios no se detectarán.
  - **Sugerencia:** decodificar escapes (`\040` → espacio, `\011` → tab, `\012` → newline) antes de comparar.

### 5.9 🟡 Bajo — `AutoSyncManager` despierta cada 5 min aunque esté desactivado

- `auto_sync.py:40-45`: si `interval <= 0`, no ejecuta ciclo, pero `wait = interval if interval > 0 else 300`, por lo que el hilo despierta cada 300s sin hacer nada.
  - **Sugerencia:** usar un wait largo o `None`/evento cuando esté desactivado.

### 5.10 🟡 Bajo — Operaciones parciales sin rollback en creación de remotos/unions

- `RemoteDialog._on_response` (edición con renombrado) borra el remoto antiguo y crea el nuevo; si la creación falla, el remoto se pierde.
- `UnionDialog._on_response` crea el union y luego el crypt; si el segundo falla, el union queda creado.
  - **Sugerencia:** crear primero y borrar después, o validar previamente; al menos documentar.

### 5.11 🟡 Bajo — Cache de `_list` en FilesPage y cambio de remoto

- `FilesPage._transfer_dialog` captura `self.current_remote` en el momento de la respuesta (no al abrir), por lo que un cambio de remoto mientras el diálogo está abierto puede operar sobre el remoto equivocado.
  - **Sugerencia:** capturar `src_remote`/`profile` al abrir el diálogo.

### 5.12 🟡 Bajo — `FilesPage` solo transfiere dentro del perfil activo

- `_fetch_remotes_then` lista remotos del `profile` activo (el del remoto montado seleccionado). No permite copiar/mover entre perfiles distintos. Limitación de diseño, pero conviene documentar o ampliar.

### 5.13 🟢 Nit — Strings sin traducir / hardcoded

- `UnionsPage` y `MountsPage` contienen literales en español fuera de `_()` (ej. "(crypt sobre …)", "Última sync", "cache residual"). `RemoteDialog`/`UnionDialog` mezclan literales sin `_()`.
- `SettingsPage` versión y nombres hardcoded.
  - **Sugerencia:** pasar por `_()` o mover a locales.

### 5.14 🟢 Nit — `application.py` importa `Path` solo para checks

- Menor; no afecta.

---

## 6. Seguridad (delegado)

No se revisaron vulnerabilidades en profundidad (responsabilidad del security agent). Puntos a verificar por ese agente:
- Ejecución de `rclone` con argumentos construidos a partir de entrada de usuario (nombres de remoto, paths) → posible inyección de flags si un nombre empieza con `-`. Verificar que `rclone config create`/`update` y `mkdir`/`purge` citen correctamente (se pasan como argv, no shell, por lo que no hay shell injection; pero flag injection sigue siendo posible).
- Escritura en `~/.config/gtk-*/bookmarks` y directorios de mount.
- Cache de contraseñas solo en memoria (correcto).
- Permisos del Flatpak (`--filesystem=home`, `--device=all`).

---

## 7. Cobertura de tests y huecos

Tests existentes pasan (22). Huecos prioritarios:
- `rclone.run` (retries, timeout, password env, flatpak).
- `config` (migración JSON→TOML, legacy app dir).
- `sync_state` (claves por perfil/union).
- `mount_manager` (mount/unmount con subprocess mockeado, `is_mounted`, `_remove_empty_parents`).
- `remote_dialog._collect_opts` (union upstreams, cache_time a int).
- `files_page` (mounted targets, transfer dialog).
- `i18n._resolve_language`.

---

## 8. Flatpak / empaquetado

- Manifest runtime GNOME 51, permisos alineados con README. ✅
- `install.sh` referencia `data/icons/...svg` (existe). ✅
- `rclone` vía `flatpak-spawn --host`. ✅
- `default_mountpoint` en Flatpak usa `~/.local/share/rcsyncitmf/mnt`. ✅

---

## 9. Veredicto

**Verdict: `approve with nits`.** No hay bloqueador funcional nuevo: los bugs anteriores (Copiar/Mover, bloqueos en MountsPage, invalidación de rclone bin) están corregidos. Permanecen mejoras de alto impacto (bloqueos de UI residuales, integridad referencial al mutar perfiles, sync condicionado a mount) que conviene atender antes de la próxima release, pero no impiden el uso.

### High priority
1. Eliminar bloqueos de UI residuales (`RemoteDialog._ensure_dump`, `profile_detail` err handler, `clear_vfs_cache`).
2. Actualizar mounts/sync_state al renombrar o borrar perfiles.
3. Habilitar sincronización de unions sin requerir mount.

### Medium/Low
4. Alinear versión única (0.1.0 vs 1.0.1 vs 1.0.0).
5. Honrar o eliminar `profiles_dir` de settings.
6. Corregir falso positivo de rclone check en Flatpak por timeout.
7. Decodificar escapes en `is_mounted` para rutas con espacios.
8. Ajustar AutoSync para no despertar cada 5 min si está desactivado.
9. Documentar o ampliar transferencia entre perfiles.
10. Ampliar cobertura de tests (sección 7).

---

## 10. Próximos pasos

- Ejecutar **quality agent** para linting/formatting/análisis estático adicional.
- Ejecutar **security agent** para escaneo de vulnerabilidades y patrones de seguridad (sección 6).
- Atender high-priority antes de merge a `main`.

---

## 11. Anexo: comandos de verificación ejecutados

```
$ /tmp/opencode/venv/bin/python -m pytest -q
22 passed in 0.03s

$ /tmp/opencode/venv/bin/ruff check src tests
All checks passed!

$ /tmp/opencode/venv/bin/ruff format --check src tests
30 files already formatted

$ /tmp/opencode/venv/bin/mypy src/rcsyncitmf
Success: no issues found in 27 source files
```