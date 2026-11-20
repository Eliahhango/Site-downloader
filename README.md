# 🌐 Site Downloader & React App Converter (v2.0)

> **Autonomous Web-to-React Cloning Engine**  
> Download entire websites with all assets (images, fonts, stylesheets, scripts, CDNs) and automatically convert them into modern, production-ready **Vite + React** applications with an **OpenCode-style interactive Terminal UI**.

---

## ⚡ Quickstart (Zero Configuration)

You do **not** need to manually install dependencies or set up virtual environments. The script self-bootstraps everything.

### Windows (One Click / Terminal)
Double-click `run.bat` or run in terminal:
```cmd
run.bat
```
*(If Python is not installed, `run.bat` automatically installs Python 3.12 via Windows Package Manager).*

### macOS / Linux
```bash
chmod +x run.sh
./run.sh
```

### Standard Python Command
```bash
python site_downloader.py
```

---

## 🖥️ Modern Terminal UI (Like OpenCode)

When run without arguments, the interactive terminal wizard appears:

```text
╭────────────────────────────────────────────────────────────────────╮
│                                                                    │
│   ███████╗██╗████████╗███████╗    ██████╗ ██╗                      │
│   ██╔════╝██║╚══██╔══╝██╔════╝    ██╔══██╗██║                      │
│   ███████╗██║   ██║   █████╗      ██║  ██║██║                      │
│   ╚════██║██║   ██║   ██╔══╝      ██║  ██║██║                      │
│   ███████║██║   ██║   ███████╗    ██████╔╝███████╗                 │
│   ╚══════╝╚═╝   ╚═╝   ╚══════╝    ╚═════╝ ╚══════╝                 │
│                                                                    │
│   Autonomous Web-to-React Cloning Engine  •  v2.0                  │
│   Zero-Config Site Downloader & Full Component Generator           │
╰────────────────────────────────────────────────────────────────────╯

╭─ System Environment ───────────────────────────────────────────────╮
│ ✔ Python Runtime           v3.12+ (Active)                         │
│ ✔ Pip Package Manager      Up to date                              │
│ ✔ Core Dependencies        requests, beautifulsoup4 (Ready)        │
│ ✔ Node.js & npm            v20+ / npm v10+                         │
╰────────────────────────────────────────────────────────────────────╯

╭─ Project Setup Wizard ─────────────────────────────────────────────╮
│  Follow the steps below to download and convert any website:       │
╰────────────────────────────────────────────────────────────────────╯

  ? Target Website URL (e.g. https://example.com):
  › https://avenora.webflow.io/destination/tulum-beach-villa-retreat

  ? Convert website into a modern Vite + React SPA? (Y/n)
  › Y

  ? Output project folder name [avenora-react]:
  › 

  ? Automatically install npm packages & build production bundle? (Y/n)
  › Y

  ? Launch local preview server when finished? (Y/n)
  › Y
```

---

## 🚀 Key Features

- **Self-Bootstrapping**:
  - Automatically installs/upgrades required Python dependencies (`requests`, `beautifulsoup4`) via `pip` on first run.
  - Automatically verifies Node.js & npm environment.
- **Deep Site Crawl & Asset Localization**:
  - Discovers all internal pages via sitemaps and page link extraction.
  - Downloads and localizes all external CDN images, stylesheets, fonts, and scripts to `/public/assets/`.
- **Webflow Badge Neutralizer**:
  - Automatically disarms Webflow's internal `brand` module in runtime JS chunks.
  - Injects CSS rules to prevent "Made in Webflow" badges from displaying.
- **Complete React Conversion**:
  - Converts HTML body templates into clean React JSX components.
  - Generates `App.jsx` with code-split lazy routes (`React.lazy()`) and SPA link routing.
  - Dynamic Webflow interaction re-initialization hook (`useWebflow.js`).
- **Automated Build & Preview**:
  - Installs npm packages (`npm install`) and compiles production bundle (`npm run build`).
  - Launches local preview server (`http://localhost:5173/`) with zero manual commands.

---

## 🛠️ Headless CLI Usage (Advanced)

For automation, CI/CD, or batch processing, pass CLI arguments directly:

```bash
# Download and convert to React in one command:
python site_downloader.py https://example.com -o my_site --to-react

# Specify custom React output directory:
python site_downloader.py https://example.com -o my_site --to-react ./my-react-app

# Convert an already downloaded website folder:
python site_downloader.py --convert-dir ./downloaded_site --react-out ./my-react-app
```
