# RCSyncitMF

Gestor GNOME (libadwaita) para **rclone** con soporte de múltiples archivos de configuración (perfiles), remotos, unions y mounts, incluyendo sincronización de la estructura de directorios entre los upstreams de un union.

## Requisitos

- Python >= 3.11
- PyGObject (GTK 4 + libadwaita)
- rclone >= 1.60
- (Para mounts) FUSE (`/dev/fuse`) y `fusermount`

## Instalación (desarrollo)

```bash
python -m pip install -e .
rcsyncitmf
```

## Instalación como app de escritorio

```bash
./install.sh
```

## Flatpak

```bash
flatpak-builder --user --install --force-clean build com.rcsyncitmf.app.yml
flatpak run com.rcsyncitmf.app
```

## Uso

1. **Perfiles**: crea o importa archivos `.conf` de rclone en `~/.config/rcsyncitmf/profiles/`.
2. **Remotos**: dentro de un perfil, crea/edita/borra remotos (soporta local, drive, s3, dropbox, onedrive, union, etc.).
3. **Unions**: crea un union seleccionando upstreams; usa "Sincronizar carpetas" para propagar creación/borrado de directorios entre upstreams (dry-run por defecto).
4. **Mounts**: monta un remoto con `rclone mount --daemon`; desmonta con `fusermount -u`.
5. **Ajustes**: concurrencia, modo (unión/intersección), profundidad, dry-run por defecto.

## Instalación como aplicación de escritorio

```bash
mkdir -p ~/.local/share/applications ~/.local/share/icons/hicolor/scalable/apps
cp data/com.rcsyncitmf.app.desktop ~/.local/share/applications/
cp data/icons/com.rcsyncitmf.app.svg ~/.local/share/icons/hicolor/scalable/apps/
update-desktop-database ~/.local/share/applications/
```

(El `.desktop` y el icono se añadirán en la fase de packaging.)

## Estructura

```
src/rcsyncitmf/
  application.py   # Adw.Application
  window.py        # ventana principal (sidebar + stack)
  config.py        # rutas XDG y settings TOML
  services/        # rclone wrapper, profiles, union sync, mounts
  ui/pages/        # perfiles, remotos, unions, mounts, ajustes
  ui/dialogs/      # remote, union
  resources/       # CSS
```

## QA manual

- [ ] Crear/importar/eliminar perfil
- [ ] Crear/editar/borrar remoto (local y un cloud)
- [ ] Test connection en remoto
- [ ] Crear union y sincronizar carpetas (dry-run + apply)
- [ ] Montar/desmontar remoto
- [ ] Cambiar ajustes y verificar persistencia
- [ ] Verificar claro/oscuro del sistema

## Licencia

GPL-3.0-or-later (propuesta).
