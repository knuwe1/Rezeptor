# app.py
import os
import uuid
import datetime
from flask import Flask, render_template, request, redirect, url_for, abort, flash
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from werkzeug.utils import secure_filename
# Stelle sicher, dass diese Importzeile alle benötigten Felder enthält:
from wtforms import StringField, TextAreaField, IntegerField, SubmitField, FloatField, SelectField # FloatField für IngredientForm hinzugefügt
from wtforms.validators import DataRequired, Optional, Length
from flask_wtf.file import FileField, FileAllowed, FileRequired
from collections import defaultdict # Nützlich für die Aggregation
from sqlalchemy.orm import joinedload # <--- DIESE ZEILE HINZUFÜGEN

basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)

# --- Upload Konfiguration ---
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads') # Pfad zum Upload-Ordner
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'} # Erlaubte Dateiendungen
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# Optional: Maximale Dateigröße (z.B. 16MB) - kann nützlich sein
# app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Stelle sicher, dass der Upload-Ordner existiert
if not os.path.exists(UPLOAD_FOLDER):
    os.makedirs(UPLOAD_FOLDER)
# --- Ende Upload Konfiguration ---

app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(basedir, 'rezepte.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
# !!! WICHTIG für Formulare: Füge einen Secret Key hinzu !!!
# Ersetze 'ein-sehr-geheimer-schluessel' durch eine zufällige Zeichenfolge
# In einer echten Anwendung sollte dieser nicht im Code stehen!
app.config['SECRET_KEY'] = 'ein-sehr-geheimer-schluessel'

db = SQLAlchemy(app)

#Context Processor, um Variablen global für Templates bereitzustellen
@app.context_processor
def inject_current_time():
    return {'current_time': datetime.datetime.now()} # Übergibt ein datetime-Objekt

# --- Formulare ---
class RecipeForm(FlaskForm):
    name = StringField('Rezeptname', validators=[DataRequired(), Length(min=3, max=150)])
    beschreibung = TextAreaField('Beschreibung (optional)')
    anleitung = TextAreaField('Anleitung', validators=[DataRequired()])
    kochzeit_minuten = IntegerField('Kochzeit (Minuten)', validators=[Optional()])
    portionen = IntegerField('Portionen', validators=[Optional()])
    quelle = StringField('Quelle (z.B. URL)', validators=[Optional(), Length(max=255)])
    # Hinweis: Zutaten werden hier noch nicht hinzugefügt. Das machen wir später.
    # NEUES FELD für Bild-Upload
    image = FileField('Rezeptbild (optional, max. 16MB)', validators=[
        FileAllowed(ALLOWED_EXTENSIONS, 'Nur Bilder sind erlaubt! (png, jpg, jpeg, gif)')
    ])
    # NEU: Kategorie Auswahlfeld
    # choices werden dynamisch in der Route gesetzt! coerce=int ist wichtig!
    category = SelectField('Kategorie', validators=[Optional()])

    submit = SubmitField('Rezept Speichern')

# Formular zum Hinzufügen/Bearbeiten einer Zutat zu einem Rezept
class IngredientForm(FlaskForm):
    zutat_name = StringField('Zutat', validators=[DataRequired(), Length(min=1, max=100)])
    menge = FloatField('Menge', validators=[Optional()]) # Optional, falls z.B. "Prise" ohne Zahl
    einheit = StringField('Einheit', validators=[Optional(), Length(max=50)]) # z.B. g, ml, Stück, Prise
    submit = SubmitField('Zutat hinzufügen')

# --- Datenbank Modelle (bleiben wie zuvor) ---
class RezeptZutat(db.Model):
    __tablename__ = 'rezept_zutat'
    rezept_id = db.Column(db.Integer, db.ForeignKey('rezept.id'), primary_key=True)
    zutat_id = db.Column(db.Integer, db.ForeignKey('zutat.id'), primary_key=True)
    menge = db.Column(db.Float, nullable=True)
    einheit = db.Column(db.String(50), nullable=True)
    rezept = db.relationship("Rezept", back_populates="zutaten_association")
    zutat = db.relationship("Zutat", back_populates="rezepte_association")

class Rezept(db.Model):
    __tablename__ = 'rezept'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    beschreibung = db.Column(db.Text, nullable=True)
    anleitung = db.Column(db.Text, nullable=False)
    kochzeit_minuten = db.Column(db.Integer, nullable=True)
    portionen = db.Column(db.Integer, nullable=True)
    quelle = db.Column(db.String(255), nullable=True)
    image_file = db.Column(db.String(100), nullable=True, default=None)

    # NEU: Fremdschlüssel zur Category Tabelle
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)

    zutaten_association = db.relationship("RezeptZutat", back_populates="rezept", cascade="all, delete-orphan")

    def __repr__(self):
        # Optional: Kategorie im repr anzeigen
        cat_name = self.category.name if self.category else 'None'
        return f'<Rezept {self.name} (Kategorie: {cat_name})>'


class Zutat(db.Model):
    __tablename__ = 'zutat'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    rezepte_association = db.relationship("RezeptZutat", back_populates="zutat")

    def __repr__(self):
        return f'<Zutat {self.name}>'

# NEUE Klasse für Kategorien
class Category(db.Model):
    __tablename__ = 'category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)
    # Beziehung zu Rezepten (optional, aber nützlich für spätere Filterung)
    rezepte = db.relationship('Rezept', backref='category', lazy=True)

    def __repr__(self):
        return f'<Category {self.name}>'

# Hilfsfunktion zum Prüfen der Dateiendung
def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# --- Routen ---
@app.route('/')
def index():
    # Lese alle Rezepte aus der Datenbank
    rezepte = Rezept.query.order_by(Rezept.name).all() # Nach Namen sortiert
    # Gib die Liste der Rezepte an das Template 'index.html'
    return render_template('index.html', rezepte=rezepte)

@app.route('/add', methods=['GET', 'POST'])
def add_recipe():
    form = RecipeForm()
    # Kategorien für das Auswahlfeld laden (immer, auch bei POST wegen evtl. Fehlern)
    categories = Category.query.order_by(Category.name).all()
    form.category.choices = [(c.id, c.name) for c in categories]
    # Standardauswahl hinzufügen (keine Kategorie)
    form.category.choices.insert(0, ('', '--- Bitte wählen ---'))
    if form.validate_on_submit():
        image_filename = None # Standardmäßig kein Bild
        if form.image.data: # Prüfen, ob eine Datei hochgeladen wurde
            file = form.image.data
            if allowed_file(file.filename):
                # Sicheren Dateinamen erstellen
                filename = secure_filename(file.filename)
                # Einzigartigen Namen generieren (UUID + Endung)
                ext = os.path.splitext(filename)[1]
                unique_filename = uuid.uuid4().hex + ext
                # Datei speichern
                try:
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                    image_filename = unique_filename # Dateinamen für DB speichern
                    # ÄNDERUNG: Manuelle Umwandlung zu int (falls nicht leer)
                    category_id=int(form.category.data) if form.category.data else None
                except Exception as e:
                    flash(f'Fehler beim Speichern des Bildes: {e}', 'danger')
                    # Hier entscheiden, ob man trotzdem speichert oder abbricht
                    # return render_template('rezept_form.html', form=form, title='Neues Rezept hinzufügen')
            else:
                flash('Ungültiger Dateityp für das Bild.', 'warning')
                # Formular erneut anzeigen, ohne zu speichern
                return render_template('rezept_form.html', form=form, title='Neues Rezept hinzufügen')

        # Rezept-Objekt erstellen (mit image_filename)
        neues_rezept = Rezept(
            name=form.name.data,
            beschreibung=form.beschreibung.data,
            anleitung=form.anleitung.data,
            kochzeit_minuten=form.kochzeit_minuten.data,
            portionen=form.portionen.data,
            quelle=form.quelle.data,
            image_file=image_filename, # Hier den Dateinamen übergeben
            # NEU: category_id aus dem Formular holen (None wenn leer)
            category_id=form.category.data if form.category.data else None
        )
        db.session.add(neues_rezept)
        try:
            db.session.commit()
            flash(f'Rezept "{neues_rezept.name}" wurde erfolgreich hinzugefügt!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Speichern des Rezepts: {e}', 'danger')

    return render_template('rezept_form.html', form=form, title='Neues Rezept hinzufügen')


@app.route('/rezept/<int:rezept_id>')
def recipe_detail(rezept_id):
    rezept = Rezept.query.get_or_404(rezept_id)
    # Erstelle eine Instanz des Zutaten-Formulars für die Anzeige
    ingredient_form = IngredientForm()
    # Übergib das Rezept UND das Formular an das Template
    return render_template('rezept_detail.html', rezept=rezept, ingredient_form=ingredient_form)

# Route zum Bearbeiten eines Rezepts
@app.route('/edit/<int:rezept_id>', methods=['GET', 'POST'])
def edit_recipe(rezept_id):
    rezept = Rezept.query.get_or_404(rezept_id)
    form = RecipeForm() # Beim POST wird das Formular mit Request-Daten gefüllt
    # Kategorien für Auswahlfeld laden (immer)
    categories = Category.query.order_by(Category.name).all()
    form.category.choices = [(c.id, c.name) for c in categories]
    form.category.choices.insert(0, ('', '--- Keine Kategorie ---')) # Keine Kategorie Option
    if form.validate_on_submit():
        # --- Bild-Upload-Logik für Bearbeiten ---
        new_image_filename = rezept.image_file # Standard: altes Bild behalten
        if form.image.data: # Neues Bild wurde hochgeladen
            file = form.image.data
            if allowed_file(file.filename):
                filename = secure_filename(file.filename)
                ext = os.path.splitext(filename)[1]
                unique_filename = uuid.uuid4().hex + ext
                try:
                    # Altes Bild löschen, falls vorhanden
                    if rezept.image_file:
                        old_path = os.path.join(app.config['UPLOAD_FOLDER'], rezept.image_file)
                        if os.path.exists(old_path):
                            os.remove(old_path)

                    # Neues Bild speichern
                    file.save(os.path.join(app.config['UPLOAD_FOLDER'], unique_filename))
                    new_image_filename = unique_filename # Neuen Dateinamen merken
                    # ÄNDERUNG: Manuelle Umwandlung zu int (falls nicht leer)
                    rezept.category_id = int(form.category.data) if form.category.data else None
                except Exception as e:
                    flash(f'Fehler beim Speichern des neuen Bildes: {e}', 'danger')
                    # Hier entscheiden: trotzdem restliche Änderungen speichern oder abbrechen?
                    new_image_filename = rezept.image_file # Im Fehlerfall altes Bild behalten
            else:
                 flash('Ungültiger Dateityp für das neue Bild. Bild wurde nicht geändert.', 'warning')
                 new_image_filename = rezept.image_file # Altes Bild behalten

        # --- Ende Bild-Upload-Logik ---

        # Rezeptdaten aktualisieren
        rezept.name = form.name.data
        rezept.beschreibung = form.beschreibung.data
        rezept.anleitung = form.anleitung.data
        rezept.kochzeit_minuten = form.kochzeit_minuten.data
        rezept.portionen = form.portionen.data
        rezept.quelle = form.quelle.data
        rezept.image_file = new_image_filename # Aktualisierten Bildnamen setzen
        # NEU: category_id aktualisieren
        rezept.category_id = form.category.data if form.category.data else None

        try:
            db.session.commit()
            flash('Rezept erfolgreich aktualisiert!', 'success')
            return redirect(url_for('recipe_detail', rezept_id=rezept.id))
        except Exception as e:
            db.session.rollback()
            flash(f'Fehler beim Aktualisieren des Rezepts: {e}', 'danger')

    elif request.method == 'GET':
        # Formular mit bestehenden Daten füllen (Bildfeld wird nicht vor-ausgefüllt)
        form.name.data = rezept.name
        form.beschreibung.data = rezept.beschreibung
        form.anleitung.data = rezept.anleitung
        form.kochzeit_minuten.data = rezept.kochzeit_minuten
        form.portionen.data = rezept.portionen
        form.quelle.data = rezept.quelle
        # Das image-Feld bleibt leer, der User muss ggf. neu auswählen
        # NEU: Gespeicherte Kategorie im Dropdown vorauswählen
        form.category.data = rezept.category_id

    # Vorhandenes Bild anzeigen (im Edit-Modus)
    current_image = None
    if rezept.image_file:
        current_image = url_for('static', filename='uploads/' + rezept.image_file)

    return render_template('rezept_form.html', form=form, title='Rezept bearbeiten', rezept=rezept, current_image=current_image)

# Route zum Löschen eines Rezepts (nur POST erlaubt)
@app.route('/delete/<int:rezept_id>', methods=['POST'])
def delete_recipe(rezept_id):
    # Hole das zu löschende Rezept oder 404
    rezept = Rezept.query.get_or_404(rezept_id)
    # Lösche das Rezept aus der Datenbank-Session
    db.session.delete(rezept)
    # Speichere die Änderungen
    db.session.commit()
    # Optional: flash(f'Rezept "{rezept.name}" wurde gelöscht.', 'success')
    # Leite zur Index-Seite um
    return redirect(url_for('index'))

# Route zum Hinzufügen einer Zutat zu einem Rezept (nur POST)
@app.route('/rezept/<int:rezept_id>/add_ingredient', methods=['POST'])
def add_ingredient(rezept_id):
    rezept = Rezept.query.get_or_404(rezept_id)
    form = IngredientForm() # Daten kommen vom Request, nicht als Objekt

    if form.validate_on_submit():
        zutat_name = form.zutat_name.data.strip() # Leerzeichen entfernen
        menge = form.menge.data
        einheit = form.einheit.data.strip()

        # 1. Finde oder erstelle die Zutat in der globalen Zutatenliste
        zutat = Zutat.query.filter(db.func.lower(Zutat.name) == db.func.lower(zutat_name)).first()
        if not zutat:
            zutat = Zutat(name=zutat_name)
            db.session.add(zutat)
            # Wir brauchen die ID der neuen Zutat sofort, daher flush (ohne commit)
            # db.session.flush() # SQLAlchemy ist oft schlau genug, das ohne flush zu verwalten

        # 2. Prüfe, ob diese Zutat bereits zu diesem Rezept hinzugefügt wurde
        existing_assoc = RezeptZutat.query.filter_by(rezept_id=rezept.id, zutat_id=zutat.id).first()
        if existing_assoc:
            flash(f'Die Zutat "{zutat.name}" ist bereits in diesem Rezept vorhanden.', 'warning')
        else:
            # 3. Erstelle die Verknüpfung zwischen Rezept und Zutat
            neue_zuordnung = RezeptZutat(
                rezept_id=rezept.id,
                zutat=zutat, # Hier können wir das Objekt übergeben
                menge=menge,
                einheit=einheit
            )
            db.session.add(neue_zuordnung)
            try:
                db.session.commit()
                flash(f'Zutat "{zutat.name}" hinzugefügt.', 'success')
            except Exception as e:
                db.session.rollback() # Änderungen rückgängig machen bei Fehler
                flash(f'Fehler beim Hinzufügen der Zutat: {e}', 'danger')

    else:
        # Formular war ungültig, zeige Fehler an
        for field, errors in form.errors.items():
            for error in errors:
                flash(f"Fehler im Feld '{getattr(form, field).label.text}': {error}", 'danger')

    # Leite immer zur Detailseite zurück, egal ob erfolgreich oder nicht
    return redirect(url_for('recipe_detail', rezept_id=rezept_id))

# Route zum Löschen einer Zutat aus einem Rezept (nur POST)
@app.route('/rezept/<int:rezept_id>/delete_ingredient/<int:zutat_id>', methods=['POST'])
def delete_ingredient(rezept_id, zutat_id):
    # Finde die spezifische Verknüpfung zwischen Rezept und Zutat
    assoc = RezeptZutat.query.filter_by(rezept_id=rezept_id, zutat_id=zutat_id).first_or_404()

    # Speichere den Namen für die Nachricht, bevor wir löschen
    zutat_name = assoc.zutat.name

    # Lösche die Verknüpfung
    db.session.delete(assoc)
    try:
        db.session.commit()
        flash(f'Zutat "{zutat_name}" aus dem Rezept entfernt.', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Fehler beim Entfernen der Zutat: {e}', 'danger')

    # Leite zurück zur Detailseite
    return redirect(url_for('recipe_detail', rezept_id=rezept_id))

# Route für die Einkaufsliste
@app.route('/einkaufsliste', methods=['GET', 'POST'])
def shopping_list():
    aggregated_list = None # Standardmäßig keine Liste

    if request.method == 'POST':
        # Hole die Liste der ausgewählten Rezept-IDs aus dem Formular
        selected_ids = request.form.getlist('recipe_ids', type=int) # type=int versucht Umwandlung
        # NEU: Gewünschte Portionen auslesen
        desired_portions = request.form.get('desired_portions', type=int)

        if not selected_ids:
            flash('Bitte wähle mindestens ein Rezept aus.', 'warning')
            return redirect(url_for('index')) # Zurück zur Auswahl
        if desired_portions is None or desired_portions < 1:
            flash('Bitte gib eine gültige Anzahl an Portionen (mindestens 1) an.', 'warning')
            return redirect(url_for('index'))

        desired_portions_display = desired_portions # Für Anzeige merken

        # --- Angepasste Aggregationslogik ---
        aggregated_list = defaultdict(lambda: defaultdict(float))

        # Hole die vollständigen Rezept-Objekte mit ihren Zutaten (effizient)
        selected_recipes = Rezept.query.filter(Rezept.id.in_(selected_ids)).options(joinedload(Rezept.zutaten_association).joinedload(RezeptZutat.zutat)).all()

        scaling_warnings = [] # Sammelt Warnungen für die Anzeige

        for rezept in selected_recipes:
            recipe_portions = rezept.portionen
            scaling_factor = 1.0 # Standard: Keine Skalierung

            # Berechne Skalierungsfaktor, wenn möglich
            if recipe_portions and recipe_portions > 0:
                scaling_factor = float(desired_portions) / float(recipe_portions)
            elif recipe_portions is None or recipe_portions <= 0:
                # Füge eine Warnung hinzu, wenn Skalierung nicht möglich
                scaling_warnings.append(f"Für Rezept '{rezept.name}' konnte keine Skalierung vorgenommen werden (Standardportionen nicht definiert oder 0). Mengen wurden nicht angepasst.")

            # Iteriere durch die Zutaten dieses Rezepts
            for assoc in rezept.zutaten_association:
                zutat_name = assoc.zutat.name.strip().capitalize()
                einheit = (assoc.einheit or '').strip().lower()
                menge = assoc.menge
                scaled_menge = menge # Standard: Originalmenge

                # Skaliere die Menge, wenn sie numerisch ist
                if menge is not None:
                    try:
                        numeric_menge = float(menge)
                        scaled_menge = numeric_menge * scaling_factor
                    except (ValueError, TypeError):
                        # Menge ist nicht numerisch (z.B. "Prise", "n.B.") - nicht skalieren
                        scaled_menge = menge # Behalte Originalwert (String) bei

                # Aggregiere die (skalierte) Menge
                if isinstance(scaled_menge, (int, float)):
                    aggregated_list[zutat_name][einheit] += scaled_menge
                elif isinstance(scaled_menge, str): # Nicht-skalierte Strings
                    # Füge String-Mengen separat hinzu, um Summierung zu vermeiden
                    einheit_str = f"{einheit} ({scaled_menge})" # Z.B. "Stück (1 Prise)"
                    aggregated_list[zutat_name][einheit_str] += 1 # Zähle, wie oft das vorkommt
                else: # Menge war None
                     aggregated_list[zutat_name][einheit] = aggregated_list[zutat_name].get(einheit, 0.0)


        # Zeige Skalierungswarnungen an
        for warning in scaling_warnings:
            flash(warning, 'warning')

        # Konvertiere defaultdict zurück in ein normales dict
        aggregated_list = {k: dict(v) for k, v in aggregated_list.items()}

    # Zeige die Einkaufslisten-Seite an
    # Wenn GET oder keine POST-Daten, ist aggregated_list = None
    return render_template('einkaufsliste.html', shopping_list=aggregated_list)

def create_default_categories():
    """Erstellt Standardkategorien, falls die Tabelle leer ist."""
    default_categories = ['Vorspeise', 'Hauptgericht', 'Dessert', 'Backen', 'Getränk', 'Salat', 'Suppe']
    try:
        if Category.query.count() == 0:
            print("Erstelle Standardkategorien...")
            for cat_name in default_categories:
                # Prüfe nochmal sicherheitshalber, ob Name schon existiert
                exists = Category.query.filter_by(name=cat_name).first()
                if not exists:
                    new_cat = Category(name=cat_name)
                    db.session.add(new_cat)
            db.session.commit()
            print("Standardkategorien erstellt.")
    except Exception as e:
        # Wichtig bei Start-Logik: Fehler abfangen, falls DB noch nicht bereit
        print(f"Fehler beim Erstellen der Kategorien (ignoriert): {e}")
        db.session.rollback()

# Führe die Funktion im App-Kontext aus
with app.app_context():
    # Erstelle Tabellen, falls sie nicht existieren (sicherer Aufruf)
    # db.create_all() # Sollte eigentlich schon durch flask shell passiert sein
    create_default_categories()



# --- Server Start (bleibt wie zuvor) ---
if __name__ == '__main__':
    # Wichtig: Initialisiere die Datenbank *innerhalb* des Kontexts, falls nötig
    # Normalerweise wird dies einmalig über `flask shell` gemacht.
    # with app.app_context():
    #    db.create_all() # Nur wenn die DB noch nicht existiert
    app.run(debug=True)