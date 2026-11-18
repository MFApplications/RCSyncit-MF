# Análisis de capacidades de rclone vs. RCSyncitMF

**Versión rclone analizada:** v1.76.0
**Fecha:** 2026-11-14

Este documento compara lo que rclone permite hacer con las funciones actuales de
RCSyncitMF, identificando huecos y propuestas de nuevas funciones/opciones.

---

## 1. Resumen de rclone

rclone es un gestor de archivos en la nube con soporte para **71 backends**
(drive, s3, dropbox, onedrive, mega, sftp, webdav, crypt, union, chunker,
combine, hasher, compress, alias, cache, archive, etc.) y decenas de comandos:

- **Transferencia:** `copy`, `sync`, `move`, `bisync`, `cat`, `rcat`, `touch`.
- **Listado/inspección:** `ls`, `lsd`, `lsf`, `lsjson`, `lsl`, `tree`, `size`,
  `about`, `hashsum`, `md5sum`, `sha1sum`, `checksum`, `check`, `cryptcheck`,
  `cryptdecode`.
- **Gestión de rutas:** `mkdir`, `rmdir`, `rmdirs`, `delete`, `deletefile`,
  `purge`, `dedupe`, `convmv`, `settier`, `cleanup`.
- **Montaje/servicio:** `mount`, `nfsmount`, `serve` (http/webdav/ftp/sftp/
  dlna/restic), `rcd` (remote control daemon), `gui`.
- **Configuración:** `config`, `authorize`, `obscure`, `link`, `backend`,
  `archive`, `selfupdate`, `completion`.
- **Otros:** `test`, `index`, `gitannex`, `ncdu`.

Flags globales relevantes: concurrencia (`--transfers`, `--checkers`),
ancho de banda (`--bwlimit`), reintentos (`--retries`, `--low-level-retries`),
timeout (`--timeout`, `--contimeout`), checksums (`--checksum`, `--size-only`),
metadatos (`--metadata`), enlaces (`--links`), filtros (`--include/--exclude`),
`--backup-dir`, `--suffix`, `--track-renames`, `--dry-run`, `--interactive`,
`--max-transfer`, `--max-delete`, `--order-by`, multi-thread, etc.

---

## 2. Funciones actuales de RCSyncitMF

| Área | Funcionalidad |
|---|---|
| Perfiles | Crear, importar, renombrar, eliminar, detectar `rclone.conf` por defecto, encriptación (metadata + cache de contraseña). |
| Remotos | CRUD tipado dinámico desde `rclone config providers` (excluye `local` y `union`), edición preservando campos no mostrados, crypt remotes, union remotes. |
| Unions | Crear union con upstreams, políticas (action/create/search), crypt opcional, sincronización de **estructura de directorios** (mirror, dry-run/apply, safety). |
| Auto-sync | Daemon periódico (crea, no borra) con baseline por (perfil, union). |
| Mounts | `rclone mount --daemon`, VFS/cache por perfil, desmontar, bookmarks GTK, limpiar cache, logs, detección de montado. |
| Ajustes | Concurrencia, profundidad de sync, binario rclone, auto-sync interval, idioma, presets VFS. |

---

## 3. Huecos / capacidades de rclone no expuestas

### A. Transferencia y sincronización de archivos (alto impacto)

- **`copy` / `copyto`**: copiar archivos entre remotos/local sin borrar en destino.
- **`sync`**: hacer destino idéntico al origen (modifica destino). La app solo sincroniza estructura de directorios, no archivos.
- **`move` / `moveto`**: mover archivos.
- **`bisync`**: sincronización bidireccional real (la app usa un mirror manual; bisync es el mecanismo nativo de rclone, con conflictos y estado).
- **`check`**: verificar que origen y destino coinciden.
- **`cryptcheck` / `cryptdecode`**: verificar integridad de remotos crypt y decodificar nombres.

### B. Inspección y administración de remotos

- **`about`**: cuota/espacio usado y libre por remoto.
- **`size`**: tamaño total y número de objetos de una ruta.
- **`ls`/`lsd`/`lsf`/`lsjson`/`lsl`/`tree`**: navegación del contenido (la app no tiene explorador de archivos).
- **`dedupe`**: encontrar y resolver duplicados.
- **`cleanup`**: vaciar papelera (drive, dropbox, etc.).
- **`link`**: generar enlaces públicos a archivos/carpetas.
- **`settier`**: cambiar clase de almacenamiento (S3/GCS).
- **`convmv`**: convertir nombres de archivos/carpetas.
- **`backend`**: comandos específicos del backend (ej. `drive quota`, `s3 ls`, `onedrive`).

### C. Servicio y montaje

- **`nfsmount`**: montar vía NFS (alternativa a FUSE).
- **`serve`**: exponer un remoto como HTTP/WebDAV/FTP/SFTP/DLNA/restic.
- **`rcd` / `rc`**: control remoto por API (la app podría controlar un rclone daemon en lugar de subprocess por operación).
- **`gui`**: GUI web de rclone (podría embeberse o lanzarse).
- **`mount` opciones adicionales**: `--allow-other`, `--read-only`, `--volname`, `--attr-timeout`, `--daemon-timeout`, `--network-mode`, etc.

### D. Configuración y seguridad

- **`authorize`**: flujo OAuth para remotos cloud (la app crea remotos pero no guía autorización).
- **`obscure`**: ofuscar contraseñas para config.
- **`config` interactivo / `config show`**: ver/editar config cruda.
- **Contraseñas de config**: `--password-command`, `RCLONE_CONFIG_PASS` (ya usado).
- **Perfiles cifrados**: ya soportado parcialmente.

### E. Backends avanzados no destacados

- `chunker`: dividir archivos grandes.
- `combine`: combinar remotos (similar a union pero diferente semántica).
- `hasher`: mejores checksums.
- `compress`: compresión transparente.
- `alias`: alias de remoto.
- `cache`: caché de remoto (deprecated en favor de VFS).
- `archive`: leer archivos comprimidos como remoto.
- `memory`: almacenamiento en memoria (útil para tests).

### F. Flags globales no expuestos

- `--transfers`, `--checkers`: concurrencia de transferencia (la app solo expone concurrencia genérica).
- `--bwlimit` / `--bwlimit-file`: límite de ancho de banda y horarios.
- `--retries`, `--low-level-retries`, `--timeout`, `--contimeout`.
- Filtros: `--include`, `--exclude`, `--filter`, `--files-from`.
- `--backup-dir`, `--suffix`, `--suffix-keep-extension`, `--track-renames`.
- `--metadata`, `--links`.
- `--dry-run`, `--interactive`, `--max-transfer`, `--max-delete`, `--max-delete-size`.
- `--order-by`, `--immutable`, `--inplace`, `--checksum`, `--size-only`, `--update`.
- `--multi-thread-*`, `--buffer-size`.
- `--max-connections`, `--tpslimit`, `--tpslimit-burst`.
- `--no-check-certificate`, proxy, headers.

---

## 4. Comparativa resumida

| Capacidad de rclone | App actual | Estado |
|---|---|---|
| Gestión de config (.conf) | ✅ Perfiles | Completo |
| CRUD de remotos tipado | ✅ | Completo |
| Crypt remotes | ✅ | Completo |
| Union remotes | ✅ | Completo |
| Sync de estructura de dirs | ✅ (mirror manual) | Parcial (solo dirs, no archivos) |
| Auto-sync | ✅ (crea, no borra) | Parcial |
| Mount (FUSE) | ✅ | Parcial (sin NFS, opciones limitadas) |
| VFS/cache | ✅ | Parcial |
| Transferencia de archivos (copy/sync/move) | ❌ | Falta |
| Bisync bidireccional | ❌ | Falta |
| Explorador de archivos remoto | ❌ | Falta |
| Cuota/espacio (about/size) | ❌ | Falta |
| Limpieza de papelera | ❌ | Falta |
| Dedupe | ❌ | Falta |
| Enlaces públicos | ❌ | Falta |
| Check/cryptcheck | ❌ | Falta |
| Serve (HTTP/WebDAV/FTP/SFTP) | ❌ | Falta |
| NFS mount | ❌ | Falta |
| Remote control daemon (rcd) | ❌ | Falta |
| Autorización OAuth guiada | ❌ | Falta |
| Filtros (include/exclude) | ❌ | Falta |
| Límites de ancho de banda | ❌ | Falta |
| Backends avanzados (chunker, combine, etc.) | ⚠️ (creables como remoto) | Sin UI específica |

---

## 5. Propuestas de nuevas funciones (priorizadas)

### P1 — Alto valor, esfuerzo moderado

1. **Explorador de archivos remoto** (pestaña "Archivos"): listar con `lsjson`/`tree`, crear carpetas (`mkdir`), borrar (`delete`/`purge`), renombrar/mover (`moveto`), subir/bajar (integrar `copy`/`copyto`), ver tamaño. Reutiliza el patrón async de la app.
2. **Copiar/Sincronizar archivos entre remotos**: wizard para `copy`/`sync` con dry-run, progreso y filtros. Exponer `--dry-run`, `--checksum`, `--size-only`, `--update`.
3. **`about`/`size` en detalle de remoto/perfil**: mostrar cuota y tamaño. Fácil de integrar en `ProfileDetailDialog` o nueva vista.
4. **`cleanup` (vaciar papelera)**: botón en remotos que soportan papelera (drive, dropbox).
5. **`link` (enlace público)**: generar y copiar enlace para un archivo/carpeta.
6. **`dedupe`**: herramienta para resolver duplicados por nombre.
7. **Opciones de mount ampliadas**: `--allow-other`, `--read-only`, `--volname`, `--attr-timeout`, `--network-mode`, `--daemon-timeout` en VFS settings.
8. **Filtros globales en ajustes**: include/exclude patterns aplicables a sync/mount.

### P2 — Alto valor, esfuerzo alto

9. **Bisync bidireccional nativo**: usar `rclone bisync` con estado persistente, conflictos y `--resync`. Reemplazaría o complementaría el mirror manual de uniones.
10. **Serve**: exponer un remoto como HTTP/WebDAV/FTP/SFTP local (útil para compartir).
11. **NFS mount**: opción `nfsmount` cuando FUSE no esté disponible.
12. **Autorización OAuth guiada**: `rclone authorize` con captura del token y creación del remoto.
13. **Remote control daemon (rcd)**: en lugar de lanzar subprocess por operación, mantener un `rclone rcd` y usar `rclone rc` (mejor rendimiento, progreso, stats). Gran refactor.
14. **Backend-specific panels**: comandos `backend` para drive/s3/etc. (quota, presign, etc.).

### P3 — Mejoras de settings/UX

15. Exponer `--transfers`, `--checkers`, `--bwlimit`, `--retries`, `--timeout` en Ajustes.
16. `--backup-dir`, `--suffix`, `--track-renames` para sync.
17. `--metadata`, `--links`.
18. `--order-by`, `--max-transfer`, `--max-delete`.
19. Límite de ancho de banda programado (horarios).
20. Estadísticas en vivo (stats de rclone) durante transferencias.

---

## 6. Riesgos y consideraciones

- **Alcance:** la app pasaría de "gestor de config + union sync + mounts" a "cliente completo de rclone"; el esfuerzo y la superficie de bugs crecen mucho. Recomendable iterar por P1.
- **Threading/UI:** las operaciones largas (copy/sync) deben usar `run_async` y mostrar progreso (rclone `--stats` o `rcd`).
- **Seguridad:** exposición de serve/rcd implica puertos locales; requiere autenticación y revisión de seguridad.
- **Compatibilidad Flatpak:** `serve`, `mount` con `--allow-other` y `rcd` pueden tener restricciones de sandbox.
- **Complejidad de bisync:** requiere estado persistente y manejo de conflictos; no sustituir el mirror actual sin pruebas.

---

## 7. Recomendación inmediata

Implementar **P1.1–P1.6** (explorador + copy/sync + about/size + cleanup + link + dedupe) y **P1.7–P1.8** (opciones de mount y filtros), manteniendo el alcance actual. Dejar P2/P3 para iteraciones posteriores según demanda.
EOF
echo done