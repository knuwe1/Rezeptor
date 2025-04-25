# Rezeptor - Deine Digitale Rezeptverwaltung

[![Lizenz](https://img.shields.io/badge/Lizenz-MIT-blue.svg)](https://opensource.org/licenses/MIT)

Rezeptor ist eine Webanwendung zur Verwaltung deiner Lieblingsrezepte. Füge neue Rezepte hinzu, bearbeite bestehende, organisiere sie nach Kategorien und generiere automatisch Einkaufslisten basierend auf ausgewählten Gerichten und der gewünschten Portionsanzahl.

## ✨ Features

* **Rezeptverwaltung (CRUD):** Erstellen, Anzeigen, Bearbeiten und Löschen von Rezepten.
* **Zutatenmanagement:** Hinzufügen und Entfernen von Zutaten zu/aus Rezepten, inklusive Mengenangaben und Einheiten.
* **Kategorisierung:** Organisiere Rezepte in Kategorien (z.B. Vorspeise, Hauptgericht, Dessert). Standardkategorien werden beim ersten Start angelegt.
* **Bild-Upload:** Füge Bilder zu deinen Rezepten hinzu.
* **Dynamische Einkaufsliste:** Wähle mehrere Rezepte und eine gewünschte Portionsanzahl aus, um eine aggregierte Einkaufsliste zu generieren. Die Mengen werden automatisch skaliert (sofern Ursprungsportionen im Rezept angegeben sind).
* **Einfache Navigation:** Übersichtliche Darstellung aller Rezepte und Detailansichten.
* **Responsive Oberfläche:** Dank Bootstrap ist die Anwendung auch auf verschiedenen Geräten nutzbar.

## 🛠️ Technologie-Stack

* **Backend:** Python
* **Framework:** Flask
* **Datenbank:** SQLite (über Flask-SQLAlchemy)
* **Formulare:** Flask-WTF / WTForms
* **Frontend:** HTML, Bootstrap 5
* **Templating:** Jinja2

## 🚀 Setup & Installation

1.  **Repository klonen (oder herunterladen):**
    ```bash
    git clone [https://github.com/knuwe1/Rezeptor.git](https://github.com/knuwe1/Rezeptor.git)
    cd Rezeptor
    ```
2.  **Virtuelle Umgebung erstellen (empfohlen):**
    ```bash
    python -m venv venv
    # Windows
    .\venv\Scripts\activate
    # macOS/Linux
    source venv/bin/activate
    ```
3.  **Abhängigkeiten installieren:**
    ```bash
    pip install -r requirements.txt
    ```
    *(Hinweis: Die `requirements.txt` enthält die notwendigen Pakete wie Flask, Flask-SQLAlchemy, Flask-WTF etc.)*

4.  **Datenbank initialisieren:**
    Die Anwendung versucht, die Datenbank (`rezepte.db`) und die Standardkategorien beim ersten Start automatisch zu erstellen, falls sie noch nicht existieren. Alternativ kannst du die Flask-Shell nutzen:
    ```bash
    flask shell
    ```
    Und darin ausführen:
    ```python
    from app import db, create_default_categories
    db.create_all()
    create_default_categories()
    exit()
    ```

## ▶️ Anwendung starten

Führe die Hauptanwendungsdatei aus:

```bash
python app.py