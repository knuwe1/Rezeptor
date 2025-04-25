# app.py
"""
Flask-Anwendung zur Verwaltung von Rezepten und Einkaufslisten.
"""

import os
import uuid
import datetime
from collections import defaultdict

# Third-party imports
from flask import (
    Flask, render_template, request, redirect, url_for,
    abort, flash, session # Session hinzugefügt für potenzielle spätere Nutzung
)
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
from flask_wtf.file import FileField, FileAllowed # FileRequired entfernt, da optional
from wtforms import (
    StringField, TextAreaField, IntegerField, SubmitField,
    FloatField, SelectField
)
from wtforms.validators import DataRequired, Optional, Length
from werkzeug.utils import secure_filename
from sqlalchemy.orm import joinedload

# --- Application Setup ---
basedir = os.path.abspath(os.path.dirname(__file__))
app = Flask(__name__)

# --- Configuration ---
# WICHTIG: In Produktion aus Umgebungsvariablen laden!
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'fallback-sehr-geheimer-schluessel') # Sicherer Standard
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get(
    'DATABASE_URL', # Heroku/Cloud Standard
    'sqlite:///' + os.path.join(basedir, 'rezepte.db') # Lokaler Fallback
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Upload Configuration
UPLOAD_FOLDER = os.path.join(basedir, 'static', 'uploads')
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER
# Optional: Maximale Dateigröße (z.B. 16MB)
# app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

# Ensure upload folder exists
os.makedirs(UPLOAD_FOLDER, exist_ok=True) # exist_ok=True verhindert Fehler, wenn Ordner schon da ist

# --- Database Setup ---
db = SQLAlchemy(app)

# --- Context Processors ---
@app.context_processor
def inject_current_time():
    """Inject current time into templates."""
    return {'current_time': datetime.datetime.now()}

# --- Forms ---
class RecipeForm(FlaskForm):
    """Form for adding or editing recipes."""
    name = StringField(
        'Rezeptname',
        validators=[DataRequired(), Length(min=3, max=150)]
    )
    beschreibung = TextAreaField('Beschreibung (optional)')
    anleitung = TextAreaField('Anleitung', validators=[DataRequired()])
    kochzeit_minuten = IntegerField('Kochzeit (Minuten)', validators=[Optional()])
    portionen = IntegerField('Portionen', validators=[Optional()])
    quelle = StringField(
        'Quelle (z.B. URL)',
        validators=[Optional(), Length(max=255)]
    )
    image = FileField(
        'Rezeptbild (optional, max. 16MB)',
        validators=[
            FileAllowed(ALLOWED_EXTENSIONS, 'Nur Bilder sind erlaubt! (png, jpg, jpeg, gif)')
        ]
    )
    # Choices are set dynamically in the route
    # coerce=int entfernt! Die Verarbeitung erfolgt in der Route.
    category = SelectField('Kategorie', validators=[Optional()])
    submit = SubmitField('Rezept Speichern')

class IngredientForm(FlaskForm):
    """Form for adding ingredients to a recipe."""
    zutat_name = StringField(
        'Zutat',
        validators=[DataRequired(), Length(min=1, max=100)]
    )
    # Menge can be float (e.g., 0.5) or omitted
    menge = FloatField('Menge', validators=[Optional()])
    einheit = StringField(
        'Einheit',
        validators=[Optional(), Length(max=50)] # e.g., g, ml, Stück, Prise
    )
    submit = SubmitField('Zutat hinzufügen')

# --- Database Models ---
class RezeptZutat(db.Model):
    """Association table between Rezept and Zutat with quantity and unit."""
    __tablename__ = 'rezept_zutat'
    rezept_id = db.Column(db.Integer, db.ForeignKey('rezept.id'), primary_key=True)
    zutat_id = db.Column(db.Integer, db.ForeignKey('zutat.id'), primary_key=True)
    menge = db.Column(db.Float, nullable=True)
    einheit = db.Column(db.String(50), nullable=True)

    # Relationships defined in Rezept and Zutat using back_populates

class Rezept(db.Model):
    """Represents a recipe."""
    __tablename__ = 'rezept'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(150), nullable=False)
    beschreibung = db.Column(db.Text, nullable=True)
    anleitung = db.Column(db.Text, nullable=False)
    kochzeit_minuten = db.Column(db.Integer, nullable=True)
    portionen = db.Column(db.Integer, nullable=True)
    quelle = db.Column(db.String(255), nullable=True)
    image_file = db.Column(db.String(100), nullable=True, default=None)

    # Foreign key to Category table
    category_id = db.Column(db.Integer, db.ForeignKey('category.id'), nullable=True)

    # Relationships
    zutaten_association = db.relationship(
        "RezeptZutat",
        backref=db.backref("rezept"), # Simplifies backref definition
        cascade="all, delete-orphan",
        lazy='joined' # Eagerly load association and zutat when loading rezept
    )
    # category relationship is defined via backref in Category model

    def __repr__(self):
        cat_name = self.category.name if self.category else 'None'
        return f'<Rezept {self.name} (Kategorie: {cat_name})>'

class Zutat(db.Model):
    """Represents an ingredient."""
    __tablename__ = 'zutat'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    # Relationships
    rezepte_association = db.relationship(
        "RezeptZutat",
        backref=db.backref("zutat", lazy='joined'), # Eagerly load zutat via association
        lazy='dynamic' # Use dynamic loading if many recipes per ingredient
    )

    def __repr__(self):
        return f'<Zutat {self.name}>'

class Category(db.Model):
    """Represents a recipe category."""
    __tablename__ = 'category'
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), unique=True, nullable=False)

    # Relationship to Rezepten
    # 'backref' creates a 'category' attribute on Rezept instances
    rezepte = db.relationship('Rezept', backref='category', lazy=True)

    def __repr__(self):
        return f'<Category {self.name}>'

# --- Helper Functions ---
def allowed_file(filename):
    """Checks if the file extension is allowed."""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def save_image(file_storage):
    """Saves an uploaded image file with a unique name and returns the filename."""
    if file_storage and allowed_file(file_storage.filename):
        filename = secure_filename(file_storage.filename)
        ext = os.path.splitext(filename)[1]
        unique_filename = uuid.uuid4().hex + ext
        try:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], unique_filename)
            file_storage.save(file_path)
            return unique_filename
        except Exception as e:
            app.logger.error(f"Fehler beim Speichern des Bildes {filename}: {e}")
            flash(f'Fehler beim Speichern des Bildes: {e}', 'danger')
            return None # Indicate error
    elif file_storage: # File was uploaded but not allowed
        flash('Ungültiger Dateityp für das Bild.', 'warning')
    return None # No file or error

def delete_image(filename):
    """Deletes an image file from the upload folder."""
    if filename:
        try:
            file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            if os.path.exists(file_path):
                os.remove(file_path)
                return True
        except Exception as e:
            app.logger.error(f"Fehler beim Löschen des Bildes {filename}: {e}")
            flash(f'Fehler beim Löschen des alten Bildes: {e}', 'warning')
    return False

def get_category_choices():
    """Returns a list of category choices for SelectFields."""
    categories = Category.query.order_by(Category.name).all()
    choices = [(c.id, c.name) for c in categories]
    choices.insert(0, ('', '--- Bitte wählen ---')) # Add default empty choice
    return choices

# --- Routes ---
@app.route('/')
def index():
    """Displays the list of all recipes."""
    # Eager load category and image information if frequently accessed on index
    rezepte = Rezept.query.options(joinedload(Rezept.category)).order_by(Rezept.name).all()
    return render_template('index.html', rezepte=rezepte)

@app.route('/add', methods=['GET', 'POST'])
def add_recipe():
    """Handles adding a new recipe."""
    form = RecipeForm()
    form.category.choices = get_category_choices() # Dynamically set choices

    if form.validate_on_submit():
        image_filename = save_image(form.image.data)
        # If save_image returned None due to an error, image_filename will be None

        neues_rezept = Rezept(
            name=form.name.data,
            beschreibung=form.beschreibung.data,
            anleitung=form.anleitung.data,
            kochzeit_minuten=form.kochzeit_minuten.data,
            portionen=form.portionen.data,
            quelle=form.quelle.data,
            image_file=image_filename,
            # WTForms coerces '' to None if coerce=int and Optional()
            category_id=form.category.data
        )
        db.session.add(neues_rezept)
        try:
            db.session.commit()
            flash(f'Rezept "{neues_rezept.name}" wurde erfolgreich hinzugefügt!', 'success')
            return redirect(url_for('index'))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Fehler beim Speichern des Rezepts {form.name.data}: {e}")
            flash(f'Fehler beim Speichern des Rezepts: {e}', 'danger')
            # Delete uploaded image if DB commit failed
            if image_filename:
                delete_image(image_filename)

    # Render form again if GET request or validation failed
    return render_template('rezept_form.html', form=form, title='Neues Rezept hinzufügen')


@app.route('/rezept/<int:rezept_id>')
def recipe_detail(rezept_id):
    """Displays the details of a single recipe."""
    # Using joinedload here ensures ingredients and their names are loaded efficiently
    rezept = Rezept.query.options(
        joinedload(Rezept.zutaten_association).joinedload(RezeptZutat.zutat),
        joinedload(Rezept.category) # Also load category if displayed
    ).get_or_404(rezept_id)

    ingredient_form = IngredientForm() # For adding new ingredients
    return render_template('rezept_detail.html', rezept=rezept, ingredient_form=ingredient_form)

@app.route('/edit/<int:rezept_id>', methods=['GET', 'POST'])
def edit_recipe(rezept_id):
    """Handles editing an existing recipe."""
    rezept = Rezept.query.get_or_404(rezept_id)
    form = RecipeForm(obj=rezept) # Pre-populate form with recipe data on GET
    form.category.choices = get_category_choices()

    if form.validate_on_submit():
        original_image = rezept.image_file
        new_image_filename = original_image # Assume old image is kept

        if form.image.data: # New image uploaded
            # Attempt to save the new image
            uploaded_filename = save_image(form.image.data)
            if uploaded_filename:
                new_image_filename = uploaded_filename
                # Delete the old image *after* new one is saved successfully
                if original_image:
                    delete_image(original_image)
            else:
                # Keep old image if upload failed, flash message already shown by save_image
                new_image_filename = original_image


        # Update recipe fields from form
        rezept.name = form.name.data
        rezept.beschreibung = form.beschreibung.data
        rezept.anleitung = form.anleitung.data
        rezept.kochzeit_minuten = form.kochzeit_minuten.data
        rezept.portionen = form.portionen.data
        rezept.quelle = form.quelle.data
        rezept.image_file = new_image_filename
        # WTForms handles the conversion for category_id
        rezept.category_id = form.category.data


        try:
            db.session.commit()
            flash('Rezept erfolgreich aktualisiert!', 'success')
            return redirect(url_for('recipe_detail', rezept_id=rezept.id))
        except Exception as e:
            db.session.rollback()
            app.logger.error(f"Fehler beim Aktualisieren von Rezept {rezept.id}: {e}")
            flash(f'Fehler beim Aktualisieren des Rezepts: {e}', 'danger')
            # If DB commit failed, but a new image was saved and old one deleted,
            # we might be in an inconsistent state. Reverting image changes is complex.
            # Consider adding logic to restore the old image if needed.

    elif request.method == 'GET':
        # Ensure category is pre-selected correctly on GET
        form.category.data = rezept.category_id

    # Provide current image URL to template for display
    current_image_url = None
    if rezept.image_file:
        current_image_url = url_for('static', filename=f'uploads/{rezept.image_file}')

    return render_template(
        'rezept_form.html',
        form=form,
        title='Rezept bearbeiten',
        rezept=rezept, # Pass rezept for cancel button link
        current_image=current_image_url
    )


@app.route('/delete/<int:rezept_id>', methods=['POST'])
def delete_recipe(rezept_id):
    """Deletes a recipe."""
    rezept = Rezept.query.get_or_404(rezept_id)
    image_to_delete = rezept.image_file # Get image filename before deleting recipe
    recipe_name = rezept.name # Get name for flash message

    try:
        db.session.delete(rezept)
        db.session.commit()
        # Delete image only after successful DB commit
        if image_to_delete:
            delete_image(image_to_delete)
        flash(f'Rezept "{recipe_name}" wurde gelöscht.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Fehler beim Löschen von Rezept {rezept_id}: {e}")
        flash(f'Fehler beim Löschen des Rezepts: {e}', 'danger')

    return redirect(url_for('index'))

@app.route('/rezept/<int:rezept_id>/add_ingredient', methods=['POST'])
def add_ingredient(rezept_id):
    """Adds an ingredient to a specific recipe."""
    rezept = Rezept.query.get_or_404(rezept_id)
    form = IngredientForm() # Process data from the request

    if form.validate_on_submit():
        zutat_name = form.zutat_name.data.strip()
        menge = form.menge.data # WTForms FloatField handles conversion or None
        einheit = form.einheit.data.strip() if form.einheit.data else None

        # Find or create the Zutat globally (case-insensitive search)
        zutat = Zutat.query.filter(db.func.lower(Zutat.name) == db.func.lower(zutat_name)).first()
        if not zutat:
            zutat = Zutat(name=zutat_name.capitalize()) # Store capitalized
            db.session.add(zutat)
            # Flush to get the ID if needed immediately (SQLAlchemy often handles this)
            # db.session.flush()

        # Check if this ingredient is already linked to this recipe
        existing_assoc = RezeptZutat.query.filter_by(rezept_id=rezept.id, zutat_id=zutat.id).first()

        if existing_assoc:
            flash(f'Die Zutat "{zutat.name}" ist bereits in diesem Rezept vorhanden.', 'warning')
        else:
            # Create the association
            neue_zuordnung = RezeptZutat(
                rezept_id=rezept.id,
                zutat=zutat, # Pass the object, SQLAlchemy handles the ID
                menge=menge,
                einheit=einheit
            )
            db.session.add(neue_zuordnung)
            try:
                db.session.commit()
                flash(f'Zutat "{zutat.name}" hinzugefügt.', 'success')
            except Exception as e:
                db.session.rollback()
                app.logger.error(f"Fehler beim Hinzufügen Zutat zu Rezept {rezept_id}: {e}")
                flash(f'Fehler beim Hinzufügen der Zutat: {e}', 'danger')

    else:
        # Form validation failed, flash errors
        for field, errors in form.errors.items():
            for error in errors:
                # Use field label if available, otherwise field name
                label = getattr(getattr(form, field, None), 'label', None)
                field_name = label.text if label else field
                flash(f"Fehler im Feld '{field_name}': {error}", 'danger')

    # Redirect back to the recipe detail page regardless of success/failure
    return redirect(url_for('recipe_detail', rezept_id=rezept_id))

@app.route('/rezept/<int:rezept_id>/delete_ingredient/<int:zutat_id>', methods=['POST'])
def delete_ingredient(rezept_id, zutat_id):
    """Removes an ingredient association from a recipe."""
    # Find the specific association link
    assoc = RezeptZutat.query.filter_by(rezept_id=rezept_id, zutat_id=zutat_id).first_or_404()
    zutat_name = assoc.zutat.name # For flash message

    try:
        db.session.delete(assoc)
        db.session.commit()
        flash(f'Zutat "{zutat_name}" aus dem Rezept entfernt.', 'success')
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"Fehler beim Entfernen Zutat {zutat_id} von Rezept {rezept_id}: {e}")
        flash(f'Fehler beim Entfernen der Zutat: {e}', 'danger')

    return redirect(url_for('recipe_detail', rezept_id=rezept_id))

# --- Shopping List Logic ---
def calculate_shopping_list(recipe_ids, desired_portions):
    """
    Calculates an aggregated shopping list for selected recipes and portions.
    Returns a tuple: (aggregated_dict, warnings_list)
    """
    aggregated_list = defaultdict(lambda: defaultdict(float))
    scaling_warnings = []

    if not recipe_ids or desired_portions is None or desired_portions < 1:
        return None, ["Keine Rezepte ausgewählt oder ungültige Portionsanzahl."]

    # Efficiently load selected recipes with their ingredients and ingredient names
    selected_recipes = Rezept.query.filter(Rezept.id.in_(recipe_ids)).options(
        joinedload(Rezept.zutaten_association).joinedload(RezeptZutat.zutat)
    ).all()

    if not selected_recipes:
        return None, ["Ausgewählte Rezepte nicht gefunden."]

    for rezept in selected_recipes:
        recipe_portions = rezept.portionen
        scaling_factor = 1.0

        # Calculate scaling factor if possible
        if recipe_portions and recipe_portions > 0:
            scaling_factor = float(desired_portions) / float(recipe_portions)
        elif desired_portions > 0: # Only warn if scaling was requested but not possible
             scaling_warnings.append(
                 f"Für Rezept '{rezept.name}' konnte keine Skalierung vorgenommen werden "
                 f"(Standardportionen nicht definiert oder 0). Mengen wurden nicht angepasst."
            )

        # Aggregate ingredients
        for assoc in rezept.zutaten_association:
            zutat_name = assoc.zutat.name.strip().capitalize()
            # Treat None or empty string as the same 'unit' category
            einheit = (assoc.einheit or '').strip().lower()
            menge = assoc.menge
            scaled_menge = menge # Default: original quantity

            # Scale quantity if numeric and scaling is possible
            if isinstance(menge, (int, float)) and scaling_factor != 1.0:
                scaled_menge = menge * scaling_factor
            elif not isinstance(menge, (int, float)) and menge is not None:
                # Handle non-numeric quantities like "Prise", "n.B." -> Treat as string
                scaled_menge = str(menge) # Ensure it's a string

            # Aggregate: Sum numeric values, handle strings separately
            if isinstance(scaled_menge, (int, float)):
                aggregated_list[zutat_name][einheit] += scaled_menge
            elif isinstance(scaled_menge, str):
                # Combine unit and string amount for uniqueness, e.g., " ('1 Prise')"
                # Using a tuple key ensures 'Prise' and '1 Prise' are distinct if needed
                string_key = f"{einheit} ({scaled_menge})"
                aggregated_list[zutat_name][string_key] = aggregated_list[zutat_name].get(string_key, 0) + 1
            else: # Menge was None
                 # Ensure the Zutat/Einheit exists in the list even with 0 amount initially
                 aggregated_list[zutat_name][einheit] = aggregated_list[zutat_name].get(einheit, 0.0)


    # Convert defaultdicts back to regular dicts for the template
    final_list = {k: dict(v) for k, v in aggregated_list.items()}
    return final_list, scaling_warnings


@app.route('/einkaufsliste', methods=['GET', 'POST'])
def shopping_list():
    """Displays the shopping list based on selected recipes."""
    aggregated_list = None
    desired_portions_display = None # For displaying in template

    if request.method == 'POST':
        selected_ids = request.form.getlist('recipe_ids', type=int)
        desired_portions = request.form.get('desired_portions', type=int)
        desired_portions_display = desired_portions # Store for template

        if not selected_ids:
            flash('Bitte wähle mindestens ein Rezept aus.', 'warning')
            return redirect(url_for('index'))
        if desired_portions is None or desired_portions < 1:
            flash('Bitte gib eine gültige Anzahl an Portionen (mindestens 1) an.', 'warning')
            return redirect(url_for('index'))

        aggregated_list, warnings = calculate_shopping_list(selected_ids, desired_portions)

        for warning in warnings:
            flash(warning, 'warning')

        if aggregated_list is None and not warnings: # Should not happen if checks above pass
             flash('Einkaufsliste konnte nicht erstellt werden.', 'danger')
        elif not aggregated_list and not warnings:
             flash('Keine Zutaten für die ausgewählten Rezepte gefunden.', 'info')


    # Render the shopping list page
    return render_template(
        'einkaufsliste.html',
        shopping_list=aggregated_list,
        desired_portions=desired_portions_display # Pass desired portions
    )

# --- Database Initialization ---
def create_default_categories():
    """Creates default categories if the category table is empty."""
    default_categories = [
        'Vorspeise', 'Hauptgericht', 'Dessert', 'Backen',
        'Getränk', 'Salat', 'Suppe'
    ]
    try:
        if Category.query.count() == 0:
            app.logger.info("Keine Kategorien gefunden. Erstelle Standardkategorien...")
            for cat_name in default_categories:
                # Check again just in case (though count() should be reliable)
                if not Category.query.filter_by(name=cat_name).first():
                    new_cat = Category(name=cat_name)
                    db.session.add(new_cat)
            db.session.commit()
            app.logger.info("Standardkategorien erstellt.")
    except Exception as e:
        # Log error during startup, but don't crash the app
        app.logger.error(f"Fehler beim Erstellen der Standardkategorien: {e}")
        db.session.rollback()

# Create tables and default categories within app context
# This ensures it runs after the app and db are configured
with app.app_context():
    try:
        # Create tables if they don't exist. Safe to run multiple times.
        db.create_all()
        # Populate default categories if needed
        create_default_categories()
    except Exception as e:
        app.logger.error(f"Fehler bei der Datenbankinitialisierung: {e}")


# --- Server Start ---
if __name__ == '__main__':
    # Debug mode should be False in production!
    # Use environment variable for debug setting
    debug_mode = os.environ.get('FLASK_DEBUG', 'False').lower() == 'true'
    app.run(debug=debug_mode, host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))