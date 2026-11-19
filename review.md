# Análisis profundo del proyecto RCSyncitMF

**Fecha:** 2026-11-19
**Rama analizada:** `develop` (árbol de trabajo limpio)
**Commits base:** `a2664fa` (último en develop)
**Alcance:** revisión de corrección, integración, diseño, i18n, Flatpak y calidad automatizada. No se encontró `plan.md` en el repositorio, por lo que la sección de cumplimiento del plan se marca como no aplicable.

---

## 1. Resumen ejecutivo

RCSyncitMF es una aplicación de escritorio GNOME (GTK 4 + libadwaita) en Python que actúa como gestor multi-perfil de `rclone`. Permite administrar perfiles (`.conf`), remotos, unions, mounts (FUSE) y sincronización de la **estructura de directorios** entre upstreams de un union. Versión actual `1.0.0`, fase Alpha.

**Estado general:** El código pasa las tres verificaciones automatizadas (22 tests, ruff sin hallazgos, mypy sin errores en 27 archivos). La iteración anterior corrigió el blocker de Copiar/Mover en el explorador, el bloqueo de caché de directorio, la invalidación del binario de rclone y el bloqueo de `MountsPage`/`ProfilesPage`. Sin embargo, **varios puntos de bloqueo del hilo de UI por llamadas síncronas a rclone siguen presentes** (en `RemoteDialog`, `profile_detail`, `mount_manager._dump_for_profile`), hay inconsistencias de mensajería en la sincronización de unions y varios detalles de integración sin cubrir por tests.

---

## 2. Stack y arquitectura

| Componente | Detalle |
|---|---|
| Lenguaje | Python ≥ 3.11 (probado en 3.13) |
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

### Flujo de datos

1. **Perfiles**: archivos `.conf` en `~/.config/rcsyncitmf/profiles`. Metadata en `.meta.toml` (cifrado, VFS).
2. **Remotos**: leídos con `rclone config dump` y editados con `config create/update/delete`.
3. **Unions**: remotos de tipo `union`; sincronización solo de **estructura de directorios** (mkdir/purge/rmdir), no archivos.
4. **Mounts**: `rclone mount --daemon` con opciones VFS por perfil; persistidos en `mounts.toml`.
5. **Auto-sync**: daemon thread que recorre perfiles/unions y aplica `build_mirror_plan` (solo creaciones, sin borrados).

---

## 3. Calidad automatizada

| Herramienta | Resultado |
|---|---|
| `pytest -q` | **22/22 passed** (0.04s) |
| `ruff check src tests` | **All checks passed** |
| `mypy src/rcsyncitmf` | **Success: no issues (27 archivos)** |

### Cobertura de tests

- `tests/test_profile_store.py` (6 tests): create/list/delete/rename/import/meta.
- `tests/test_mount_manager.py` (9 tests): mountpoint, cache, safe_remote, read log, custom dir, cleanup.
- `tests/test_union_sync.py` (7 tests): parse, collapse, join, build_mirror_plan, apply.

**No hay tests para:** `rclone.py`, `config.py`, `sync_state.py`, `auto_sync.py`, `profile_store.is_encrypted`, `union_sync.normalize_union_cache_times`, `remote_dialog`, `union_dialog`, `files_page`, `mounts_page`, `window`, `application`, `profile_detail`.

---

## 4. Cumplimiento del plan

No se encontró `plan.md` (ni `research.md`) en el repositorio. Por lo tanto, no es posible evaluar cumplimiento contra un plan aprobado. La revisión siguiente se basa en la corrección general del código y en la coherencia interna del proyecto.

---

## 5. Hallazgos de corrección (Correctness Issues)

### 5.1 🔴 High — Bloqueos del hilo de UI por llamadas síncronas a rclone (parcialmente pendiente)

La iteración anterior movió `MountsPage` y `ProfilesPage` a variantes asíncronas, pero varios puntos siguen ejecutando `rclone` de forma síncrona en el hilo principal de GTK:

- **`RemoteDialog._ensure_dump`** (`remote_dialog.py:181-195`): usa `asyncio.run(rclone.config_dump(...))`. Se invoca durante la construcción del diálogo y al cambiar tipo (crypt/union), bloqueando la UI hasta que rclone responda. Afecta `_crypt_candidates`, `_crypt_parents`, `_union_remotes`.
- **`profile_store.is_encrypted`** (`profile_store.py:167-189`): crea un event loop sincrónico. Aún se usa en `ProfileDetailDialog._load_accounts` (`profile_detail.py:202`) en el manejador de error, bloqueando la UI al fallar la carga de un perfil cifrado.
- **`mount_manager._dump_for_profile`** (`mount_manager.py:554-578`): crea un event loop sincrónico. Se usa por `crypt_parent` y `related_cache_remotes` (síncronos). `MountsPage` ya usa las variantes async, pero `related_cache_remotes` sigue siendo síncrono y se llama desde `clear_vfs_cache` (bloqueando el event loop async breve).
- **`rclone.list_providers`** (`rclone.py`, función síncrona con `subprocess.run`): se llama en `RemoteDialog.__init__` (`remote_dialog.py:100`) durante la construcción del diálogo, pudiendo bloquear hasta 30 s si rclone tarda.

**Impacto:** congelamiento de la ventana con perfiles cifrados, redes lentas o rclone lento.

### 5.2 🟠 Medium — Mensajería inconsistente en sincronización de unions

- **Archivo:** `src/rcsyncitmf/ui/pages/unions_page.py` (`_on_sync`, `_show_preview`)
- **Descripción:** La vista previa anuncia “creaciones; borrados deshabilitados por seguridad”, pero `_on_sync` fuerza `delete_enabled=False` y `allow_delete=False`, por lo que nunca se propagan borrados desde la UI. Además, `_show_preview` muestra una nota sobre `action_policy` (`epall`/`all`) que sugiere que los borrados se propagan automáticamente, cuando en realidad están deshabilitados siempre. La interfaz también ofrece un switch “Purge (borrado recursivo)” que no tiene efecto porque no hay operaciones de borrado.
- **Impacto:** confusión del usuario; la UI promete funcionalidad que no se ejecuta.

### 5.3 🟠 Medium — `profiles_dir` de settings no se honra

- **Archivos:** `src/rcsyncitmf/services/profile_store.py` (`list_profiles`, constante `PROFILES_DIR`) vs `src/rcsyncitmf/config.py` (`DEFAULT_SETTINGS["profiles_dir"]`)
- **Descripción:** `profile_store` usa la constante fija `PROFILES_DIR`; `settings["profiles_dir"]` se muestra en Ajustes pero no se usa. Modificarlo manualmente en `settings.toml` se ignora.
- **Impacto:** baja (no editable desde UI), pero inconsistencia de configuración.

### 5.4 🟠 Medium — Desajuste de mountpoint en el fallback de `mount()`

- **Archivo:** `src/rcsyncitmf/services/mount_manager.py` (`mount`, bloque `except (OSError, PermissionError)`)
- **Descripción:** Si `mkdir` falla, `mount()` reasigna `mountpoint` a una ruta bajo `~/.local/share/rcsyncitmf/mnt/...` y persiste esa nueva ruta en `mounts.toml`. Sin embargo, la UI (`RemotesPage._toggle_mount`, `UnionsPage._toggle_mount`) ignora el valor devuelto por `mount()` y sigue usando la ruta original capturada (`mp`) en los callbacks `ok_mount`, por lo que el botón/etiqueta puede quedar con la ruta antigua. `do_mount` retorna `mp` (original), no el mountpoint efectivo.
- **Impacto:** ruta mostrada incorrecta cuando se usa el fallback (poco frecuente, solo con permisos insuficientes).

### 5.5 🟡 Low — `profile_detail` no invalida la caché de dump al borrar remotos

- **Archivo:** `src/rcsyncitmf/ui/dialogs/profile_detail.py` (`_delete_remote`)
- **Descripción:** Llama a `rclone.delete_remote` pero no invoca `mount_manager._invalidate_profile_dump_cache(self.profile)`. La caché de dump (TTL 15 s) puede devolver datos obsoletos en `MountsPage`/`RemotesPage` tras borrar un remoto. Otros puntos de mutación (`remote_dialog`, `union_dialog`, `profile_store`) sí invalidan.
- **Impacto:** datos obsoletos hasta 15 s tras borrar un remoto desde el detalle del perfil.

### 5.6 🟡 Low — Cadenas sin traducir (i18n incompleta)

- **Archivos:** `src/rcsyncitmf/window.py` (`check_default_rclone_config`, `_menu_shortcuts`, `stack.add_titled(..., "settings", "Ajustes")`), `src/rcsyncitmf/ui/pages/unions_page.py` (`_toggle_mount` ya traducido parcialmente, notas de `action_policy` hardcodeadas en español), `src/rcsyncitmf/ui/pages/mounts_page.py` (etiqueta `(crypt sobre {parent})`), `src/rcsyncitmf/application.py` (mensajes ya traducidos en su mayoría).
- **Descripción:** Varias cadenas quedan en español aun con idioma `en`, y el título de la página de Ajustes en el stack no usa `_()`.
- **Impacto:** experiencia inconsistente en inglés.

### 5.7 🟡 Low — `FilesPage` carrera de token en caché

- **Archivo:** `src/rcsyncitmf/ui/pages/files_page.py` (`_list`)
- **Descripción:** El token `_list_token` se verifica al inicio de `ok()`, pero la escritura a `_list_cache` ocurre después de ordenar/filtrar. Si la invalidación ocurre entre el guard y la asignación, la caché puede quedar con datos de una petición obsoleta. Riesgo bajo.
- **Además:** tras `_download` no se invalida caché (correcto, no modifica listado), pero `_open_file` descarga a un directorio temporal que no se limpia.

### 5.8 🟡 Low — `RemoteDialog` no permite borrar valores en edición

- **Archivo:** `src/rcsyncitmf/ui/dialogs/remote_dialog.py` (`_collect_opts`, `_on_response`)
- **Descripción:** En edición, los campos con valor vacío se omiten de `opts`, por lo que `merged` conserva el valor anterior. No es posible vaciar un campo existente desde la UI (solo añadir/cambiar).
- **Impacto:** edición limitada; menor.

### 5.9 🟡 Low — Versión hardcodeada en el diálogo “Acerca de”

- **Archivo:** `src/rcsyncitmf/window.py` (`_menu_about`): `dlg.set_version("1.0.0")` en lugar de usar `__version__`.
- **Impacto:** si se cambia la versión en `pyproject.toml`, la UI no se actualiza automáticamente.

### 5.10 🟡 Low — `AutoSyncManager` siempre en modo “solo creación”

- **Archivo:** `src/rcsyncitmf/services/auto_sync.py` (`_cycle`)
- **Descripción:** Llama a `build_mirror_plan(..., allow_delete=False, max_deletions=0)` y `apply_plan(..., delete=False)`. Coherente con seguridad, pero la UI/mensajes sugieren lo contrario. Documentar o alinear.

---

## 6. Integración y diseño

### 6.1 Explorador de archivos y transferencias entre perfiles

`FilesPage` trabaja con **targets montados** (tuplas `(profile, remote)`), y `_transfer_dialog` (Copiar/Mover) obtiene la lista de remotos del perfil activo de forma asíncrona (`_fetch_remotes_then`). Funciona para transferencias dentro del mismo perfil. No hay forma de elegir remotos de otro perfil ni targets montados de otros perfiles; diseño a revisar si se quiere transferencia cross-profile.

### 6.2 Edición de crypt remotes es “segura” pero limitada

Solo permite cambiar contraseñas; upstream y modo de cifrado son de solo lectura. Correcto para no corromper datos. Sin embargo, si un campo avanzado se elimina manualmente en el `.conf`, la app lo mantiene (porque no está en `opts`). Comportamiento esperado en la mayoría de casos.

### 6.3 `mount()` no espera a que el daemon termine de montar

`rclone mount --daemon` retorna cuando el proceso daemonizado arranca; `subprocess.run` con timeout 60. Luego la UI asume montado y consulta `is_mounted`. Aceptable, pero en redes lentas puede reportar “montado” antes de estar listo.

### 6.4 Bookmarks GTK

Se añaden entradas a `gtk-3.0/bookmarks` y `gtk-4.0/bookmarks`. `cleanup_bookmarks` elimina entradas cuyo path no está montado. Correcto.

### 6.5 `mount_manager.is_mounted` hace dos subprocess por llamada en Flatpak

Se llama repetidamente en bucles de UI (`MountsPage.refresh`, `FilesPage._load_mounted_targets`, `RemotesPage._load_remotes_for`, `UnionsPage._add_union_row`). Rendimiento aceptable pero mejorable con caché/memoización.

---

## 7. Seguridad (observaciones; delegar a Security agent)

- Contraseñas de perfiles cifrados se mantienen **solo en memoria** (`_PASSWORD_CACHE`), nunca persistidas. ✅
- `RCLONE_CONFIG_PASS` se pasa por entorno, no por argv. ✅
- `unmount` no borra el mountpoint si el desmontaje falla. ✅
- `mount_manager.is_mounted` en Flatpak evita interpolación de shell (usa argv). ✅
- `unmount` usa lista de comandos (sin shell). ✅
- **Pendiente de revisión (Security agent):**
  - Validación de nombres de perfil/remoto (path traversal). `create_profile` valida `/` y prefijo `.`; `import_profile_unique` copia por nombre; pero los nombres de remoto/union no se validan contra `..` o caracteres de control.
  - Permisos de archivos de config (`.conf`, `.meta.toml`, `mounts.toml`) — no se ajustan explícitamente (umask del proceso).
  - Exposición de puertos: no hay `serve`/`rcd` actualmente, por lo que la superficie es baja.
  - Manejo de `--allow-other` y `/etc/fuse.conf` (permisos de otros usuarios).
  - `remote_dialog` envía opciones a rclone tal cual; no se sanitizan valores con saltos de línea o caracteres de control. Riesgo bajo (config local).
  - `mount()` fallback usa `profile.stem` y `remote` como componentes de ruta sin sanitización; un nombre malicioso podría escapar del directorio base. Riesgo bajo (nombres provienen de config local).

---

## 8. Internacionalización

- Solo `es` y `en`; `_resolve_language` devuelve `es` por defecto.
- Muchas cadenas en `UnionsPage`, `MountsPage` y `window.py` están sin `_()` (hardcoded en español). Inconsistencia menor/media.
- `SettingsPage` idioma requiere reinicio (documentado en diálogo).

---

## 9. Flatpak

- Manifest runtime GNOME 51, permisos: ipc, x11/wayland, dri, all devices, network, home, xdg-config/cache, talk org.freedesktop.Flatpak. ✅ alineado con README.
- `install.sh` usa `pipx` o `pip --user`. ✅
- `rclone` se ejecuta vía `flatpak-spawn --host`. ✅
- `default_mountpoint` en Flatpak usa `~/.local/share/rcsyncitmf/mnt` (compartido con host). ✅
- `is_mounted` y `unmount` adaptados al sandbox. ✅

---

## 10. Veredicto

**Verdict: `approve with nits`** (sin blockers funcionales abiertos tras la iteración anterior).

### Pendientes recomendados (no blockers)

1. Mover llamadas síncronas a rclone (`RemoteDialog._ensure_dump`, `profile_store.is_encrypted` en `profile_detail`, `mount_manager._dump_for_profile`/`related_cache_remotes`, `rclone.list_providers`) a `run_async` o caché con carga lazy.
2. Alinear mensajería de sync (bidireccional vs solo creación) o habilitar borrados explícitamente; quitar o deshabilitar el switch de Purge si no hay borrados.
3. Honrar `settings["profiles_dir"]` o eliminarlo de settings.
4. Corregir desajuste de mountpoint en el fallback de `mount()` (retornar/usar el mountpoint efectivo en la UI).
5. Invalidar caché de dump en `profile_detail._delete_remote`.
6. Traducir cadenas hardcodeadas en `window.py`, `unions_page.py`, `mounts_page.py`.
7. Usar `__version__` en el diálogo “Acerca de”.
8. Añadir tests para `rclone.py`, `sync_state.py`, `config.py`, `remote_dialog` (lógica de `_collect_opts`), `files_page` (transfer), `profile_detail`.

---

## 11. Próximos pasos

- Ejecutar **quality agent** para linting/formatting/análisis estático adicional.
- Ejecutar **security agent** para escaneo de vulnerabilidades y patrones de seguridad.
- Corregir los pendientes de alta prioridad antes de merge a `main`.

---

## 12. Actualización post-implementación (Fases 0–9)

Se aplicaron las correcciones de las Fases 1–7 y se amplió la suite de tests (Fase 8).

- Fase 1: `RemoteDialog._ensure_dump`, `list_providers`, `profile_detail` y `mount_manager` sin bloqueos de UI.
- Fase 2: mensajería de sync de unions alineada (solo creaciones).
- Fase 3: `profiles_dir` de settings honrado.
- Fase 4: mountpoint efectivo en fallback de `mount()`.
- Fase 5: invalidación de caché en `profile_detail._delete_remote`.
- Fase 6: cadenas hardcodeadas envueltas en `_()`.
- Fase 7: `__version__`, cleanup de temporales, guard de token en caché, vaciado de campos en edición.
- Fase 8: +9 tests (sync_state, config, rclone básico, remote_dialog, files_page). Total 31 tests.

Verificación final:

```
$ .venv/bin/python -m pytest -q
31 passed in 0.13s

$ .venv/bin/ruff check src tests
All checks passed!

$ .venv/bin/mypy src/rcsyncitmf
Success: no issues found in 27 source files
```

## 13. Anexo: comandos de verificación ejecutados

```
$ .venv/bin/python -m pytest -q
22 passed in 0.04s

$ .venv/bin/ruff check src tests
All checks passed!

$ .venv/bin/mypy src/rcsyncitmf
Success: no issues found in 27 source files
```
