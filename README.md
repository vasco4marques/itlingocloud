# itlingoodoo

Skeleton repository for the **ITLingo Cloud** Odoo deployment.

This repo is intentionally minimal: it pins the project layout, the Odoo
configuration template, and the `Makefile` that drives Odoo. The actual
Odoo source and the custom modules live in their own git repositories and
are pulled into this layout at setup time.

---

## Repository layout

```
itlingoodoo/
├── odoo/                  # Odoo 19 source (gitignored, clone separately)
│   └── Makefile           # The ONLY tracked file inside odoo/
├── custom-addons/         # ITLingo custom modules (gitignored, clone separately)
│   └── README.md          # Instructions for that repo
├── config/
│   ├── odoo.config.example
│   └── odoo.config        # Local config (gitignored)
└── README.md
```

---

## Requirements

### Python

- **Python 3.12.8** (pinned for this project).
- Odoo 19 officially requires Python **3.10 or later**; we standardize on
  3.12.8 to stay aligned with the upcoming Odoo 20 baseline.

### Odoo 19

Per the official Odoo 19 on-premise [source install
docs](https://www.odoo.com/documentation/19.0/administration/on_premise/source.html):

- **PostgreSQL 13.0 or above** (PostgreSQL 16 recommended).
  Odoo only supports PostgreSQL — MySQL/MariaDB/SQLite will not work.
  You must create a dedicated PostgreSQL user (Odoo cannot connect as
  `postgres`).
- **Node.js + npm** (Node.js 18 LTS recommended) for asset compilation.
- **`rtlcss`** for right-to-left languages:
  ```bash
  sudo npm install -g rtlcss
  ```
- **wkhtmltopdf 0.12.6** for PDF headers/footers (install manually from the
  upstream package, **not** via pip).
- Python dependencies from Odoo's `requirements.txt` (installed inside the
  Odoo checkout — see below).

System packages on Fedora/Debian-likes (PostgreSQL, Node.js, build tools,
libxml2/libxslt, libjpeg, etc.) are also required — follow the Odoo docs
linked above for the exact list for your distribution.

---

## Setup

### 1. Clone this skeleton

```bash
git clone <this-repo-url> itlingoodoo
cd itlingoodoo
```

After cloning, `odoo/` will contain only `Makefile` and `custom-addons/`
will contain only `README.md`.

### 2. Clone Odoo 19 into `./odoo`

The `odoo/` folder is gitignored except for `Makefile`. Clone the Odoo 19
source **into that folder** (preserving the existing `Makefile`):

```bash
# from the project root
git clone --depth=1 --branch 19.0 https://github.com/odoo/odoo.git odoo-tmp
# move the Odoo source in alongside the existing Makefile
mv odoo-tmp/.git odoo-tmp/* odoo-tmp/.[!.]* odoo/ 2>/dev/null
rmdir odoo-tmp
```

(Or clone elsewhere and copy the contents in, as long as `odoo/Makefile`
from this skeleton is preserved.)

### 3. Clone the custom addons into `./custom-addons`

```bash
# from the project root, remove the placeholder README first
rm custom-addons/README.md
git clone <custom-addons-repo-url> custom-addons
```

### 4. Create the Odoo config

```bash
cp config/odoo.config.example config/odoo.config
# then edit config/odoo.config and set:
#   - db_user / db_password / db_host / db_port
#   - admin_passwd
#   - addons_path  (absolute path to ./custom-addons in this checkout)
```

### 5. Python environment

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install --upgrade pip wheel
pip install -r odoo/requirements.txt
```

### 6. PostgreSQL user

```bash
sudo -u postgres createuser -s <your_db_user>
sudo -u postgres psql -c "ALTER USER <your_db_user> WITH PASSWORD '<your_db_password>';"
```

### 7. Run Odoo

The `odoo/Makefile` is preconfigured to use `../config/odoo.config` and the
`itlingo_dev` database:

```bash
cd odoo
make run            # start Odoo
make upgrade_custom # upgrade the ITLingo custom modules only
make upgrade_all    # upgrade every installed module
make upgrade        # upgrade custom modules then run Odoo
```

---

## Notes

- `config/odoo.config` is gitignored — never commit secrets. Always edit
  `config/odoo.config.example` if the template needs to change.
- `odoo/` and `custom-addons/` are gitignored except for the two tracked
  helper files (`odoo/Makefile`, `custom-addons/README.md`). This keeps
  the two upstream repositories cleanly decoupled from this skeleton.
