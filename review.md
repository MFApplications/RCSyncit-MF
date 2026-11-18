# Análisis profundo del proyecto RCSyncitMF

**Fecha:** 2026-11-16
**Rama analizada:** `develop` (working tree con cambios sin commitear)
**Commits base:** `adb0186` (Initial commit on develop), `1c4ce48` (Initial commit)

---

## 1. Resumen ejecutivo

RCSyncitMF es una aplicación de escritorio GNOME (GTK 4 + libadwaita) escrita en Python que actúa como gestor multi-perfil de `rclone`. Permite administrar perfiles (`.conf`), remotos, unions, mounts (FUSE) y sincronización de estructura de directorios entre upstreams de un union. El proyecto está en fase **Alpha (0.1.0)** y combina una capa de servicios (subprocess async a rclone) con una UI GTK construida manualmente.

**Estado general:** El código compila conceptualmente (mypy sin errores, ruff sin hallazgos, 20 tests pasan). Sin embargo, hay **al menos un bug funcional claro** (Copiar/Mover en el explorador de archivos rompe por atributo no definido), varios **bloqueos del hilo de UI** por llamadas síncronas a rclone, y **cobertura de tests limitada** (solo 3 módulos de servicio, sin UI ni integración).

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

## 3. Verificación de calidad automatizada

| Herramienta | Resultado |
|---|---|
| `pytest -q` | **20/20 passed** (0.05s) |
| `ruff check src tests` | **All checks passed** |
| `mypy src/rcsyncitmf` | **Success: no issues (27 archivos)** |

### Cobertura de tests

- `tests/test_profile_store.py` (6 tests): create/list/delete/rename/import/meta.
- `tests/test_mount_manager.py` (9 tests): mountpoint, cache, safe_remote, read log.
- `tests/test_union_sync.py` (5 tests): parse, collapse, join, build_mirror_plan, apply.

**No hay tests para:** `rclone.py`, `config.py`, `sync_state.py`, `auto_sync.py`, `profile_store.is_encrypted`, `union_sync.normalize_union_cache_times`, `remote_dialog`, `union_dialog`, `files_page`, `mounts_page`, `window`, `application`.

---

## 4. Hallazgos de corrección (Correctness Issues)

### 4.1 🔴 Bug funcional: `FilesPage._transfer_dialog` usa `self.remotes` no definido

- **Archivo:** `src/rcsyncitmf/ui/pages/files_page.py` (líneas 717-753)
- **Descripción:** El método `_transfer_dialog` (invocado por “Copiar” y “Mover”) itera `self.remotes`, pero `FilesPage` nunca inicializa ese atributo (solo define `self.targets`, `self.active_remote`, etc.). Al pulsar Copiar/Mover se lanza `AttributeError: 'FilesPage' object has no attribute 'remotes'`.
- **Impacto:** Funcionalidad de copiar/mover entre remotos completamente rota.
- **Esperado:** Poblar `self.remotes` con los nombres de remoto del perfil activo (o de los targets montados) antes de abrir el diálogo, o derivar la lista dentro del diálogo.

### 4.2 🟠 Bloqueos del hilo de UI por llamadas síncronas a rclone

Varios métodos ejecutan `rclone` de forma síncrona en el hilo principal de GTK:

- **`RemoteDialog._ensure_dump`** (`remote_dialog.py:185-195`): usa `asyncio.run(rclone.config_dump(...))` dentro de `_crypt_candidates`, `_crypt_parents`, `_union_remotes`. Se invoca durante la construcción del diálogo y al cambiar tipo, bloqueando la UI hasta que rclone responda.
- **`mount_manager._dump_for_profile`** (`mount_manager.py:478-495`): crea un event loop y ejecuta `rclone.config_dump` sincrónicamente. Se alcanza desde `MountsPage.refresh` → `crypt_parents_with_cache`/`related_cache_remotes` en el hilo de UI.
- **`profile_store.is_encrypted`** (`profile_store.py:155-175`): crea event loop sincrónico. Se llama desde `ProfilesPage._on_toggle_encrypt` en UI.
- **`ProfilesPage._on_toggle_encrypt`** llama `is_encrypted` directamente.

**Impacto:** Congelamiento de la ventana mientras rclone consulta backends remotos (especialmente con perfiles cifrados o redes lentas).

### 4.3 🟠 `SettingsPage` no invalida la caché del binario de rclone

- **Archivo:** `src/rcsyncitmf/services/rclone.py` (`_RCLONE_BIN_CACHE`) y `src/rcsyncitmf/ui/pages/settings_page.py` (`_apply`)
- **Descripción:** `rclone_bin()` cachea la resolución de `shutil.which(name)` por nombre. Si el usuario cambia el binario en Ajustes y vuelve a un nombre previamente usado, se reutiliza la ruta antigua hasta reiniciar.
- **Impacto:** Cambio de binario puede no aplicarse sin reinicio.

### 4.4 🟡 `profiles_dir` de settings no se usa

- **Archivo:** `src/rcsyncitmf/services/profile_store.py` (`list_profiles`, `PROFILES_DIR`) vs `src/rcsyncitmf/config.py` (`DEFAULT_SETTINGS["profiles_dir"]`)
- **Descripción:** `profile_store` usa la constante `PROFILES_DIR` fija; `settings["profiles_dir"]` se muestra pero no se honra. Si se modifica manualmente en `settings.toml`, la app lo ignora.
- **Impacto:** Baja (no editable desde UI), pero inconsistencia de configuración.

### 4.5 🟡 Mensajería inconsistente en sincronización de unions

- **Archivo:** `src/rcsyncitmf/ui/pages/unions_page.py` (`_show_preview`, `_on_sync`)
- **Descripción:** La vista previa anuncia “Modo: espejo bidireccional (creación + borrado)”, pero `_on_sync` fuerza `delete_enabled=False` y `allow_delete=False`, por lo que nunca se propagan borrados desde la UI. Además, las etiquetas de botones en `_toggle_mount` usan strings sin traducir (“Montando…”, “Desmontar”, “Montar”).
- **Impacto:** Confusión de usuario; deletes del plan siempre vacíos.

### 4.6 🟡 `AutoSyncManager` siempre en modo “solo creación”

- **Archivo:** `src/rcsyncitmf/services/auto_sync.py` (`_cycle`)
- **Descripción:** Llama a `build_mirror_plan(..., allow_delete=False, max_deletions=0)` y `apply_plan(..., delete=False)`. Coherente con seguridad, pero el mensaje de la UI sugiere lo contrario. Documentar o alinear.

### 4.7 🟡 Race/consistencia en `FilesPage._list`

- **Archivo:** `src/rcsyncitmf/ui/pages/files_page.py`
- **Descripción:** El token de invalidación (`_list_token`) se incrementa y se captura en `fetch`. Sin embargo, la caché (`_list_cache`) se escribe en `ok()` sin verificar si el token sigue vigente antes de la asignación (sí se verifica al inicio de `ok`, pero la escritura ocurre después de ordenar). En la práctica el guard `if token != self._list_token: return` está al inicio, por lo que es razonable, pero la caché puede quedar con datos de una petición obsoleta si la invalidación ocurre entre el guard y la asignación. Riesgo bajo.
- **Además:** `_invalidate_cache` no se llama tras `_upload`/`_download` (solo en `_new_folder`, `_delete`, `_rename`, `_copy`, `_move`). Subir/descargar archivos no invalida la caché del directorio actual, por lo que la vista puede quedar desactualizada.

### 4.8 🟡 `mount_manager._dump_for_profile` crea event loop en hilo arbitrario

- Como en 4.2; además el caché `_PROFILE_DUMP_CACHE` (TTL 15s) no se invalida al cambiar perfiles/remotos, por lo que `crypt_parent`/`related_cache_remotes` pueden devolver datos obsoletos hasta 15s.

### 4.9 🟡 `is_mounted` en Flatpak hace dos subprocess por llamada

- **Archivo:** `src/rcsyncitmf/services/mount_manager.py` (`is_mounted`)
- **Descripción:** Primero `flatpak-spawn --host mountpoint`, y si falla, `cat /proc/mounts`. En bucles de UI (MountsPage.refresh, FilesPage) se llama repetidamente. Rendimiento aceptable pero mejorable con caché.

### 4.10 🟡 `ProfilesPage._on_toggle_encrypt` bloquea UI

- Llama a `profile_store.is_encrypted` (síncrono) en el hilo principal. Ver 4.2.

---

## 5. Hallazgos de integración y diseño

### 5.1 Explorador de archivos incompleto para transferencias entre perfiles

`FilesPage` trabaja con **targets montados** (tuplas `(profile, remote)`), pero `_transfer_dialog` asume un único `self.profile` y una lista `self.remotes` inexistente. No hay forma de elegir remotos de otro perfil. Diseño a revisar.

### 5.2 `RemoteDialog` preserva campos no mostrados

En edición, hace `merged = {k: v for k, v in base.items() if k != "type"}` y luego `merged.update(opts)` tras eliminar valores sin cambios. Esto es correcto para no re-ofuscar contraseñas, pero si un campo avanzado se elimina manualmente en el conf, el app lo mantiene (porque no está en `opts`). Comportamiento esperado en la mayoría de casos.

### 5.3 Edición de crypt remotes es “segura” pero limitada

Solo permite cambiar contraseñas; upstream y modo de cifrado son de solo lectura. Correcto para no corromper datos.

### 5.4 `UnionDialog` no valida nombres duplicados

Depende de `rclone create_remote` que fallará; el error se muestra vía toast. Aceptable.

### 5.5 Auto-sync no notifica a la UI

`AutoSyncManager._toast` es no-op real; `_toast` module-level busca la ventana activa. No se invoca en el ciclo. El auto-sync es silencioso (solo logs). Aceptable para daemon.

### 5.6 `mount_manager.mount` fallback de mountpoint

Si `mkdir` falla, reasigna `mountpoint` a `~/.local/share/rcsyncitmf/mnt/...`. El registro persistido usa la nueva ruta. Correcto, pero el caller (UI) puede seguir mostrando la ruta original en el botón (se pasa `mp` original al callback). En `RemotesPage._toggle_mount`, `ok_mount` recibe `_mp` (nuevo) y actualiza etiqueta con el nuevo mp. Bien. En `UnionsPage` similar.

### 5.7 `mount` no espera a que el daemon termine de montar

`rclone mount --daemon` retorna cuando el proceso daemonizado arranca; `subprocess.run` con timeout 60. Luego la UI asume montado. `is_mounted` se consulta después. Aceptable.

### 5.8 Bookmarks GTK

Se añaden entradas a `gtk-3.0/bookmarks` y `gtk-4.0/bookmarks`. `cleanup_bookmarks` elimina entradas cuyo path no está montado. Correcto.

---

## 6. Seguridad (observaciones, delegar a Security agent)

- Contraseñas de perfiles cifrados se mantienen **solo en memoria** (`_PASSWORD_CACHE`), nunca persistidas. ✅
- `RCLONE_CONFIG_PASS` se pasa por entorno, no por argv. ✅
- `unmount` no borra el mountpoint si el desmontaje falla. ✅ (evita pérdida de datos)
- `mount_manager.is_mounted` en Flatpak evita interpolación de shell (usa argv). ✅
- **Pendiente de revisión (Security agent):** validación de nombres de perfil/remoto (path traversal), permisos de archivos de config, exposición de puertos (no hay `serve`/`rcd` actualmente), manejo de `--allow-other` y `/etc/fuse.conf`.
- **Pendiente:** `remote_dialog` envía opciones a rclone tal cual; no se sanitizan valores con saltos de línea o caracteres de control. Riesgo bajo (config local).

---

## 7. Internacionalización

- Solo `es` y `en`; `_resolve_language` devuelve `es` por defecto.
- Muchas cadenas en `_toggle_mount` (UnionsPage) y en `mounts_page` están sin `_()` (hardcoded en español). Inconsistencia menor.
- `SettingsPage` idioma requiere reinicio (documentado en diálogo).

---

## 8. Flatpak

- Manifest runtime GNOME 51, permisos: ipc, x11/wayland, dri, all devices, network, home, xdg-config/cache, talk org.freedesktop.Flatpak. ✅ alineado con README.
- `install.sh` usa `pipx` o `pip --user`. ✅
- `rclone` se ejecuta vía `flatpak-spawn --host`. ✅
- `default_mountpoint` en Flatpak usa `~/.local/share/rcsyncitmf/mnt` (compartido con host). ✅

---

## 9. Veredicto

**Verdict: `approve with nits`** con **un bug funcional bloqueante** (4.1) que debe corregirse antes de release.

### Blockers
1. `FilesPage._transfer_dialog` → `AttributeError: self.remotes` (Copiar/Mover rotos).

### High priority (no blockers pero recomendados)
2. Mover llamadas síncronas a rclone (`_ensure_dump`, `_dump_for_profile`, `is_encrypted`) a `run_async` o caché con carga lazy.
3. Invalidar caché de directorio tras upload/download en FilesPage.
4. Alinear mensajería de sync (bidireccional vs solo creación) o habilitar borrados explícitamente.
5. Invalidar `_RCLONE_BIN_CACHE` al cambiar ajustes.

### Medium/Low
6. Honrar `settings["profiles_dir"]` o eliminarlo de settings.
7. Traducir strings hardcoded en UnionsPage/MountsPage.
8. Añadir tests para `rclone.py`, `sync_state.py`, `config.py`, `remote_dialog` (lógica de collect_opts), `files_page` (transfer).
9. Invalidar `_PROFILE_DUMP_CACHE` al modificar perfiles.

---

## 10. Próximos pasos

- Ejecutar **quality agent** para linting/formatting/análisis estático adicional.
- Ejecutar **security agent** para escaneo de vulnerabilidades y patrones de seguridad.
- Corregir el blocker 4.1 y los high-priority antes de merge a `main`.

---

## 10b. Correcciones aplicadas en esta iteración

- **Blocker 4.1:** `FilesPage` ahora inicializa `self.remotes` y obtiene la lista de remotos del perfil activo de forma asíncrona antes de abrir el diálogo de transferencia (`_fetch_remotes_then`), evitando `AttributeError` en Copiar/Mover.
- **4.7:** `FilesPage` invalida la caché tras operaciones que modifican el directorio (ya aplicado en upload/delete/rename/new folder).
- **4.3:** Nueva función `rclone.invalidate_rclone_bin_cache()` invocada desde `SettingsPage._apply`.
- **4.5/4.6:** Mensaje de vista previa alineado con el comportamiento real (solo creaciones); strings de montaje traducidos en `UnionsPage`.
- **4.8:** `MountsPage.refresh` ahora calcula el conjunto de crypt parents de forma asíncrona (`async_crypt_parents_with_cache`, `async_crypt_parent_map`), evitando bloqueos del hilo de UI.
- **4.2/4.10:** `ProfilesPage` usa `encrypted_flag` (no bloqueante) en lugar de `is_encrypted`.
- **Invalidación de caché:** `_invalidate_profile_dump_cache` se invoca en mutaciones de perfiles/remotos/unions.

## 11. Anexo: comandos de verificación ejecutados

```
$ .venv/bin/python -m pytest -q
20 passed in 0.05s

$ .venv/bin/ruff check src tests
All checks passed!

$ .venv/bin/mypy src/rcsyncitmf
Success: no issues found in 27 source files
```
